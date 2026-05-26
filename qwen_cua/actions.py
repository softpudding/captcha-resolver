"""Low-level OS input actions, expressed in normalized model coordinates.

Every coordinate argument is in the model's [0, coord_scale] space; these
wrappers translate to logical screen points and drive the real mouse/keyboard
through pyautogui.
"""
from __future__ import annotations

import random
import time

import pyautogui

from .config import CONFIG
from .screen import norm_to_screen

pyautogui.FAILSAFE = CONFIG.failsafe
# Small global pause between pyautogui primitives so the OS/UI keeps up.
pyautogui.PAUSE = 0.05

# Smooth accel/decel tween — a constant-velocity drag looks robotic; a human
# hand eases in and out.
_TWEEN = pyautogui.easeInOutQuad


def _human_gap() -> None:
    """Wait a randomized beat before an action, so operations aren't machine-gun
    evenly timed. No-op when human_like is disabled."""
    if CONFIG.human_like:
        time.sleep(CONFIG.op_gap_base + random.uniform(0, CONFIG.op_gap_jitter))


def _jitter(x: int, y: int) -> tuple[int, int]:
    """Nudge a click point by a few pixels so it isn't suspiciously pixel-exact."""
    j = CONFIG.click_jitter_px
    if CONFIG.human_like and j > 0:
        x += random.randint(-j, j)
        y += random.randint(-j, j)
    return x, y


def _glide(x: int, y: int) -> None:
    """Move the cursor to absolute screen coords, smoothly + at random speed."""
    if CONFIG.human_like:
        dur = random.uniform(CONFIG.move_dur_min, CONFIG.move_dur_max)
        pyautogui.moveTo(x, y, duration=dur, tween=_TWEEN)
    else:
        pyautogui.moveTo(x, y, duration=0.15)


def _move(nx: float, ny: float) -> tuple[int, int]:
    x, y = norm_to_screen(nx, ny)
    _glide(x, y)
    return x, y


def move(nx: float, ny: float) -> str:
    _human_gap()
    x, y = _move(nx, ny)
    return f"moved cursor to screen point ({x}, {y})"


def click(nx: float, ny: float, button: str = "left", clicks: int = 1) -> str:
    _human_gap()
    x, y = _jitter(*norm_to_screen(nx, ny))
    _glide(x, y)
    pyautogui.click(x=x, y=y, clicks=clicks, interval=0.08, button=button)
    label = {1: "", 2: "double-", 3: "triple-"}.get(clicks, f"{clicks}x ")
    return f"{label}{button}-clicked at screen point ({x}, {y})"


def double_click(nx: float, ny: float) -> str:
    return click(nx, ny, button="left", clicks=2)


def right_click(nx: float, ny: float) -> str:
    return click(nx, ny, button="right", clicks=1)


def drag(from_x: float, from_y: float, to_x: float, to_y: float) -> str:
    _human_gap()
    sx, sy = norm_to_screen(from_x, from_y)
    ex, ey = norm_to_screen(to_x, to_y)
    _glide(sx, sy)
    if CONFIG.human_like:
        # Slower, eased drag with random speed — slider puzzles especially are
        # scored on the motion profile, not just the endpoint.
        pyautogui.dragTo(ex, ey, duration=random.uniform(0.6, 1.2), button="left", tween=_TWEEN)
    else:
        pyautogui.dragTo(ex, ey, duration=0.5, button="left")
    return f"dragged from ({sx}, {sy}) to ({ex}, {ey})"


def type_text(text: str) -> str:
    _human_gap()
    if CONFIG.human_like:
        # Per-keystroke jitter instead of a fixed cadence.
        for ch in text:
            pyautogui.write(ch)
            time.sleep(random.uniform(0.04, 0.18))
    else:
        pyautogui.write(text, interval=0.03)
    preview = text if len(text) <= 60 else text[:57] + "..."
    return f"typed text: {preview!r}"


# Friendly aliases the model may emit -> pyautogui key names.
_KEY_ALIASES = {
    "cmd": "command",
    "win": "winleft",
    "control": "ctrl",
    "return": "enter",
    "esc": "escape",
    "del": "delete",
}


def _norm_key(k: str) -> str:
    k = k.strip().lower()
    return _KEY_ALIASES.get(k, k)


def press_key(keys: str) -> str:
    """Press a key or a chord like 'enter', 'cmd+a', 'ctrl+shift+t'."""
    _human_gap()
    parts = [_norm_key(p) for p in keys.replace(" ", "").split("+") if p]
    if not parts:
        return "no key given"
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return f"pressed key(s): {'+'.join(parts)}"


def scroll(amount: int, direction: str = "down") -> str:
    """Scroll the wheel. Positive `amount` is the number of clicks."""
    _human_gap()
    direction = direction.lower()
    mag = abs(int(amount)) * 100  # pyautogui scroll units are coarse
    if direction in ("up", "down"):
        pyautogui.scroll(mag if direction == "up" else -mag)
    elif direction in ("left", "right"):
        pyautogui.hscroll(mag if direction == "right" else -mag)
    else:
        return f"unknown scroll direction: {direction}"
    return f"scrolled {direction} by {amount}"


def wait(seconds: float) -> str:
    seconds = max(0.0, min(10.0, float(seconds)))
    time.sleep(seconds)
    return f"waited {seconds:g}s"
