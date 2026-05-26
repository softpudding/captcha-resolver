"""Overlay a numbered NxM grid on a fixture's grid.png for accurate labeling.

Usage: .venv/bin/python eval/_annotate_grid.py <fixture_dir> [<fixture_dir> ...]
Writes <fixture_dir>/grid_annotated.png (upscaled, gridlines + 0-based index per cell).
Throwaway tooling for the human/agent labeling step; not part of the harness.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def annotate(fixture_dir: Path) -> None:
    meta = json.loads((fixture_dir / "meta.json").read_text())
    rows, cols = meta["rows"], meta["cols"]
    img = Image.open(fixture_dir / "grid.png").convert("RGB")
    scale = max(1, 980 // img.width)
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    w, h = img.size
    cw, ch = w / cols, h / rows
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    except Exception:
        font = ImageFont.load_default()
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cw, r * ch
            draw.rectangle([x0, y0, x0 + cw, y0 + ch], outline=(255, 0, 0), width=2)
            idx = r * cols + c
            tx, ty = x0 + 4, y0 + 4
            for dx in (-1, 1):
                for dy in (-1, 1):
                    draw.text((tx + dx, ty + dy), str(idx), font=font, fill=(0, 0, 0))
            draw.text((tx, ty), str(idx), font=font, fill=(255, 255, 0))
    out = fixture_dir / "grid_annotated.png"
    img.save(out)
    print(f"{fixture_dir.name}: target={meta.get('target_word')!r} -> {out}")


if __name__ == "__main__":
    for d in sys.argv[1:]:
        annotate(Path(d))
