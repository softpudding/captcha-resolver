"""Screen capture and coordinate mapping.

The model works in a normalized [0, coord_scale] space. The OS mouse works in
logical screen points (what pyautogui reports via ``size()`` / ``position()``).
These helpers translate between the two and grab screenshots via the macOS
``screencapture`` CLI (which honours the Screen Recording permission).
"""
from __future__ import annotations

import base64
import io
import subprocess
import tempfile
from pathlib import Path

import pyautogui
from PIL import Image

from .config import CONFIG


def screen_size() -> tuple[int, int]:
    """Logical screen size in points (the space pyautogui clicks in)."""
    s = pyautogui.size()
    return int(s.width), int(s.height)


def norm_to_screen(nx: float, ny: float) -> tuple[int, int]:
    """Map normalized [0, coord_scale] coords to logical screen points."""
    w, h = screen_size()
    scale = CONFIG.coord_scale
    x = int(round(nx / scale * w))
    y = int(round(ny / scale * h))
    # Clamp to the screen so a slightly out-of-range model output is harmless.
    x = max(0, min(w - 1, x))
    y = max(0, min(h - 1, y))
    return x, y


def grab_screenshot() -> Image.Image:
    """Capture the main display as a PIL image, downscaled for the model.

    Uses ``screencapture -x -m`` (no sound, main display only).
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        path = Path(tf.name)
    try:
        subprocess.run(
            ["screencapture", "-x", "-m", str(path)],
            check=True,
            capture_output=True,
        )
        img = Image.open(path).convert("RGB")
    finally:
        path.unlink(missing_ok=True)

    target_w = CONFIG.screenshot_width
    if target_w and img.width > target_w:
        ratio = target_w / img.width
        img = img.resize((target_w, int(round(img.height * ratio))), Image.LANCZOS)
    return img


def image_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
