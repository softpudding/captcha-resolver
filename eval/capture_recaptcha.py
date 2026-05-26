"""Capture REAL Google reCAPTCHA challenges and freeze them as eval fixtures.

This is the "collect" half of the capture-and-replay design (see DESIGN.md).
It drives Google's own reCAPTCHA v2 demo with Playwright, and for every image
challenge it encounters it records:

  - the real instruction text (+ the bold target object word),
  - a screenshot of the real tile grid (real Google imagery)  -> grid.png,
  - the grid geometry (3x3 / 4x4) and whether tiles reload dynamically,
  - a per-tile screenshot for clean replay slicing                -> tiles/NN.png,

and writes it all to ``eval/tasks/<case_id>/`` as a fixture. Answer keys
(which tiles are correct) are NOT filled in here — a human labels them after,
by viewing grid.png, into ``answer_key.json``.

Usage:
    PYTHONPATH=. .venv/bin/python eval/capture_recaptcha.py --max 14 --out eval/tasks

Notes:
  - Uses the real Chrome channel, headful. An automation-flagged browser is
    usually challenged immediately, which is exactly what we want here.
  - We hit Google's *demo* sitekey (google.com/recaptcha/api2/demo), not live
    search, so we are not hammering search endpoints.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Frame, sync_playwright

DEMO_URL = "https://www.google.com/recaptcha/api2/demo"

# Selectors inside the two reCAPTCHA iframes.
ANCHOR_IFRAME = 'iframe[src*="recaptcha/api2/anchor"]'
BFRAME_IFRAME = 'iframe[src*="recaptcha/api2/bframe"]'
CHECKBOX = "#recaptcha-anchor"
INSTRUCTION = ".rc-imageselect-instructions"
DESC_STRONG = ".rc-imageselect-desc strong, .rc-imageselect-desc-no-canonical strong"
TILE = ".rc-imageselect-tile"
TABLE = "#rc-imageselect-target table"
TARGET = "#rc-imageselect-target"
PAYLOAD = "#rc-imageselect-payload"
VERIFY_BTN = "#recaptcha-verify-button"
RELOAD_BTN = "#recaptcha-reload-button"
AUDIO_BTN = "#recaptcha-audio-button"


def _bframe(page) -> Frame | None:
    """The challenge iframe's Frame object (None if not present yet)."""
    for fr in page.frames:
        if "api2/bframe" in (fr.url or ""):
            return fr
    return None


def _has_challenge(page) -> bool:
    bframe = _bframe(page)
    if not bframe:
        return False
    try:
        return bframe.query_selector(TILE) is not None
    except Exception:  # noqa: BLE001
        return False


def ensure_challenge(page, tries: int = 6) -> bool:
    """Make sure an image challenge is showing; reload + re-click as needed.

    The checkbox sometimes passes straight to a green check with no challenge
    (depends on cookies / IP reputation), so we reload the demo and re-click
    until a tile grid appears.
    """
    for attempt in range(tries):
        if _has_challenge(page):
            return True
        try:
            page.goto(DEMO_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(1.0)
            page.frame_locator(ANCHOR_IFRAME).locator(CHECKBOX).click(timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        # Wait for tiles to populate.
        for _ in range(10):
            if _has_challenge(page):
                return True
            time.sleep(0.6)
    return _has_challenge(page)


def _classify(instruction: str, n_tiles: int, table_class: str) -> dict:
    """Derive geometry + mode from the live challenge DOM."""
    text = instruction.lower()
    # Geometry from the table class Google sets (…-33, -44, -42) or tile count.
    if "table-44" in table_class or n_tiles == 16:
        rows, cols = 4, 4
    elif "table-33" in table_class or n_tiles == 9:
        rows, cols = 3, 3
    else:
        # Fallback: assume square-ish.
        side = round(n_tiles ** 0.5)
        rows = cols = side
    # Dynamic = correct tiles fade out and are replaced; phrased "none left".
    dynamic = "none left" in text or "dynamic" in table_class
    # Single-image segmentation (4x4) vs distinct thumbnails (3x3).
    mode = "segmentation" if (rows, cols) == (4, 4) else ("dynamic" if dynamic else "static")
    skip_when_none = "if there are none" in text or "click skip" in text
    return {
        "rows": rows, "cols": cols, "n_tiles": n_tiles,
        "dynamic": dynamic, "mode": mode, "skip_when_none": skip_when_none,
    }


def _target_word(bframe: Frame) -> str:
    try:
        el = bframe.query_selector(DESC_STRONG)
        return (el.inner_text().strip() if el else "") or ""
    except Exception:  # noqa: BLE001
        return ""


def capture_one(page, out_dir: Path, idx: int) -> dict | None:
    """Capture the challenge currently shown in the bframe, if any."""
    bframe = _bframe(page)
    if not bframe:
        return None
    try:
        bframe.wait_for_selector(TILE, timeout=4000)
    except Exception:  # noqa: BLE001
        return None  # checkbox passed with no challenge, or audio-only

    instruction = ""
    try:
        instruction = (bframe.inner_text(INSTRUCTION, timeout=2000) or "").strip()
    except Exception:  # noqa: BLE001
        pass
    instruction = re.sub(r"\s+", " ", instruction)

    tiles = bframe.query_selector_all(TILE)
    n = len(tiles)
    table_class = ""
    try:
        tbl = bframe.query_selector(TABLE)
        table_class = (tbl.get_attribute("class") if tbl else "") or ""
    except Exception:  # noqa: BLE001
        pass

    geo = _classify(instruction, n, table_class)
    case_id = f"cap_{idx:02d}_{geo['mode']}_{geo['rows']}x{geo['cols']}"
    cdir = out_dir / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "tiles").mkdir(exist_ok=True)

    # Full grid screenshot (real Google imagery).
    try:
        bframe.locator(TARGET).first.screenshot(path=str(cdir / "grid.png"))
    except Exception:  # noqa: BLE001
        bframe.locator(PAYLOAD).first.screenshot(path=str(cdir / "grid.png"))

    # Per-tile screenshots for clean replay rendering.
    for i, t in enumerate(tiles):
        try:
            t.screenshot(path=str(cdir / "tiles" / f"{i:02d}.png"))
        except Exception:  # noqa: BLE001
            pass

    meta = {
        "case_id": case_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": DEMO_URL,
        "instruction": instruction,
        "target_word": _target_word(bframe),
        **geo,
        "has_audio_fallback": bool(bframe.query_selector(AUDIO_BTN)),
    }
    (cdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    # answer_key.json is left for the human labeler.
    ak = cdir / "answer_key.json"
    if not ak.exists():
        ak.write_text(json.dumps(
            {"correct_tiles": [], "labeled": False,
             "_note": f"View grid.png. List 0-based indices (row-major, {geo['rows']}x{geo['cols']}) "
                      f"of tiles matching: {meta['target_word'] or instruction!r}."},
            indent=2))
    print(f"  [{idx:02d}] {case_id}: {instruction!r}  ({n} tiles, dynamic={geo['dynamic']})")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=14, help="Max challenges to attempt to capture.")
    ap.add_argument("--out", default="eval/tasks", help="Fixture output directory.")
    ap.add_argument("--user-data-dir", default="/tmp/qwen-cua-capture")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    captured = 0
    seen_signatures: set[str] = set()

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=args.user_data_dir, channel="chrome", headless=False,
        locale="en-US",  # force English instructions
        viewport=None, args=["--window-position=80,60", "--window-size=1100,900",
                             "--lang=en-US"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        for idx in range(1, args.max + 1):
            if not ensure_challenge(page):
                print(f"  [{idx:02d}] could not summon a challenge — retrying")
                continue
            meta = capture_one(page, out, captured + 1)
            if meta:
                sig = f"{meta['mode']}|{meta['target_word'].lower()}|{meta['rows']}x{meta['cols']}"
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    captured += 1
                else:
                    print(f"       (duplicate signature {sig!r} — kept but not counted)")
            # Rotate to a fresh challenge via the reload button (stays in challenge mode).
            bframe = _bframe(page)
            if bframe:
                try:
                    bframe.click(RELOAD_BTN, timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(2.2)
    finally:
        print(f"\nCaptured {captured} distinct challenge signatures into {out}/")
        print("Next: view each grid.png and fill answer_key.json, then build replay pages.")
        ctx.close()
        pw.stop()
    return 0 if captured else 1


if __name__ == "__main__":
    raise SystemExit(main())
