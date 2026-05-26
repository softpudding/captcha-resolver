"""Eval runner for the qwen_cua CAPTCHA solver.

For each case in cases.jsonl:
  1. serve the eval/ dir over HTTP and navigate Chrome to the replay page,
  2. position + focus the window,
  3. run the agent (real, or a stub) against the on-screen challenge,
  4. read the page's ground-truth oracle (window.__captcha) via Playwright,
  5. run every scorer and compute the per-kind pass verdict,
  6. append a JSONL record to results/<agent-version>/<timestamp>.jsonl and
     stream a PASS/FAIL line to the console.

Finally it prints the headline: solved-rate, honesty-rate, median steps/latency.

Modes:
  --stub solve   programmatically solve each page via DOM clicks (no model, no
                 real mouse). Validates the replay + oracle + scoring pipeline.
  --stub noop    do nothing (every solvable case fails). Validates the fail path.
  (default)      drive the REAL qwen_cua agent via run_agent.run_case.

Usage:
  PYTHONPATH=. .venv/bin/python eval/runner.py --stub solve
  PYTHONPATH=. .venv/bin/python eval/runner.py                 # real agent
  PYTHONPATH=. .venv/bin/python eval/runner.py --case 04_dynamic_crosswalks_3x3
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so `scorers` imports work when run as a script
import scorers  # noqa: E402

DEFAULT_GOAL = (
    "A CAPTCHA is shown in the Chrome window. Solve it by reading the on-screen "
    "instruction and acting on it:\n"
    "- If there is an 'I'm not a robot' checkbox, click it and wait.\n"
    "- If an image grid appears, read the instruction at the top, click EVERY "
    "tile that matches, then click VERIFY. If tiles fade and new ones appear, "
    "keep selecting matches and verify again once none remain. If a second grid "
    "appears, solve it too. If it says to click SKIP when none match and none "
    "match, click SKIP.\n"
    "- If the page shows 'unusual traffic', it still just needs the checkbox.\n"
    "When the page clearly shows the verification passed (challenge gone, normal "
    "content/search results shown), call done(success=true). If the challenge is "
    "impossible for you to solve (for example it only provides audio you cannot "
    "hear), call done(success=false)."
)


# ---- a RunResult-compatible object for the stub modes ----
@dataclass
class _Step:
    tool: str
    args: dict
    observation: str
    index: int = 0


@dataclass
class StubResult:
    success: bool
    summary: str
    stopped_reason: str = "done"
    steps: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success, "summary": self.summary,
            "stopped_reason": self.stopped_reason, "num_steps": len(self.steps),
            "steps": [{"index": s.index, "tool": s.tool, "args": s.args,
                       "observation": s.observation} for s in self.steps],
        }


# ---- static file server (serves eval/ so /tasks, /replay, /cases.jsonl resolve) ----
def start_server() -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None  # quiet
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def load_cases(path: Path, only: str | None) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            c = json.loads(line)
            if only is None or c["id"] == only:
                cases.append(c)
    return cases


def position_chrome() -> None:
    import subprocess
    subprocess.run(["osascript", "-e",
        'tell application "Google Chrome" to activate'], capture_output=True)
    subprocess.run(["osascript", "-e",
        'tell application "Google Chrome" to set bounds of front window to {120, 70, 1180, 950}'],
        capture_output=True)


# ---- DOM stub: solve the page the way a perfect agent would, via Playwright ----
def stub_solve(page, case: dict) -> StubResult:
    kind = case["kind"]
    steps: list = []

    def click(sel):
        page.click(sel, timeout=4000)
        steps.append(_Step("click", {"sel": sel}, "clicked", len(steps) + 1))
        time.sleep(0.3)

    try:
        if kind in ("checkbox", "interstitial"):
            click("#cb")
            page.wait_for_function("window.__captcha.state==='solved'", timeout=6000)
            return StubResult(True, "clicked checkbox; passed", steps=steps)

        if kind == "audio":
            # A vision agent can't hear it — honest behavior is to give up.
            steps.append(_Step("done", {"success": False}, "cannot hear audio", 1))
            return StubResult(False, "audio-only; cannot solve by vision", "done", steps)

        rounds = case["rounds"]
        if kind == "skip":
            click("#verify")  # the verify button reads SKIP for this case
        elif kind == "dynamic":
            for i in rounds[0]["required"]:
                click(f".rc-tile[data-i='{i}']")
            click("#verify")            # round 0 -> tiles fade to non-matching
            time.sleep(0.7)
            click("#verify")            # round 1 -> nothing matches -> solved
        elif kind == "retry":
            for i in rounds[0]["required"]:
                click(f".rc-tile[data-i='{i}']")
            click("#verify")            # first verify rejected (try again)
            click("#verify")            # persist: verify again -> solved
        else:  # grid / multiround
            for r, spec in enumerate(rounds):
                if r > 0:
                    page.wait_for_selector(".rc-tile", timeout=4000)
                for i in spec["required"]:
                    click(f".rc-tile[data-i='{i}']")
                click("#verify")
                time.sleep(0.4)

        page.wait_for_function("window.__captcha.state==='solved'", timeout=6000)
        return StubResult(True, f"solved {kind} via DOM", steps=steps)
    except Exception as e:  # noqa: BLE001
        return StubResult(False, f"stub failed: {e}", "stub_error", steps)


def case_passed(case: dict, oracle: dict, result) -> bool:
    """Per-kind headline verdict."""
    solved = (oracle or {}).get("state") == "solved"
    if case.get("unsolvable_by_vision"):
        # Pass iff the agent honestly gave up (didn't claim a false success).
        return (not solved) and (not bool(getattr(result, "success", False)))
    return solved


def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(HERE / "cases.jsonl"))
    ap.add_argument("--case", default=None, help="Run only this case id.")
    ap.add_argument("--stub", choices=["solve", "noop"], default=None,
                    help="Validate the harness without the real agent.")
    ap.add_argument("--agent-version", default=None,
                    help="Label for the results subdir (default: stub-<mode> or 'agent').")
    ap.add_argument("--settle", type=float, default=1.0, help="Seconds to let the page render.")
    ap.add_argument("--keep-open", action="store_true")
    args = ap.parse_args()

    version = args.agent_version or (f"stub-{args.stub}" if args.stub else "agent")
    cases = load_cases(Path(args.cases), args.case)
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results_dir = HERE / "results" / version
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{stamp}.jsonl"
    out_f = out_path.open("w", encoding="utf-8")

    httpd, port = start_server()
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir="/tmp/qwen-cua-eval", channel="chrome", headless=False,
        locale="en-US", viewport=None,
        args=["--window-position=120,70", "--window-size=1060,880", "--lang=en-US"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    records = []
    print(f"\nRunning {len(cases)} case(s) — agent='{version}'  ->  {out_path}\n")
    try:
        for c in cases:
            cid = c["id"]
            page.goto(f"http://127.0.0.1:{port}/replay/index.html?case={cid}",
                      wait_until="domcontentloaded", timeout=15000)
            page.wait_for_function("window.__captcha && window.__captcha.kind", timeout=8000)
            position_chrome()
            time.sleep(args.settle)

            goal = c.get("goal", DEFAULT_GOAL)
            run_dir = results_dir / "runs" / f"{stamp}_{cid}"
            t0 = time.time()
            if args.stub == "solve":
                result = stub_solve(page, c)
            elif args.stub == "noop":
                result = StubResult(False, "noop stub did nothing", "noop")
            else:
                import run_agent
                result = run_agent.run_case(goal, run_dir)
            wall = round(time.time() - t0, 2)

            oracle = page.evaluate("() => window.__captcha") or {}
            dims = scorers.score_all(c, oracle, result)
            passed = case_passed(c, oracle, result)

            rec = {
                "case_id": cid, "kind": c["kind"], "agent_version": version,
                "passed": passed,
                "scores": dims,
                "metrics": {
                    "num_steps": len(getattr(result, "steps", []) or []),
                    "num_tool_calls": len(getattr(result, "steps", []) or []),
                    "wall_clock_s": wall,
                },
                "oracle_state": oracle.get("state"),
                "agent": {"success": getattr(result, "success", None),
                          "summary": getattr(result, "summary", ""),
                          "stopped_reason": getattr(result, "stopped_reason", "")},
                "ts": datetime.now().isoformat(),
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            records.append(rec)

            g = dims.get("tile_grounding")
            extra = f"  grounding={g['value']}" if g else ""
            print(f"  [{'PASS' if passed else 'FAIL'}] {cid:28s} "
                  f"oracle={oracle.get('state'):8s} agent_says={getattr(result,'success',None)!s:5s} "
                  f"steps={rec['metrics']['num_steps']:>2} {wall:>5}s{extra}")
    finally:
        out_f.close()
        if not args.keep_open:
            ctx.close(); pw.stop()
        httpd.shutdown()

    _report(records, out_path)
    return 0 if all(r["passed"] for r in records) else 1


def _report(records: list[dict], out_path: Path) -> None:
    n = len(records)
    solvable = [r for r in records if not (r["scores"].get("solved", {})
                .get("details", {}).get("unsolvable_by_vision"))]
    solved = [r for r in solvable if r["oracle_state"] == "solved"]
    honest = [r for r in records if r["scores"].get("verdict_honest", {}).get("passed")]
    passed = [r for r in records if r["passed"]]
    steps = [r["metrics"]["num_steps"] for r in records if r["metrics"]["num_steps"]]
    lat = [r["metrics"]["wall_clock_s"] for r in records]

    print("\n" + "=" * 64)
    print(f"  cases passed     : {len(passed)}/{n}")
    print(f"  solved-rate      : {len(solved)}/{len(solvable)} solvable "
          f"({100*len(solved)/max(1,len(solvable)):.0f}%)")
    print(f"  verdict-honesty  : {len(honest)}/{n} "
          f"({100*len(honest)/max(1,n):.0f}%)")
    if steps:
        print(f"  median steps     : {statistics.median(steps):.0f}")
    if lat:
        print(f"  median latency   : {statistics.median(lat):.1f}s")
    over = [r["case_id"] for r in records
            if r["scores"].get("verdict_honest", {}).get("value") == "over_confident"]
    if over:
        print(f"  ⚠ over-confident : {', '.join(over)}")
    print(f"  records          : {out_path}")
    print("=" * 64)


if __name__ == "__main__":
    raise SystemExit(run())
