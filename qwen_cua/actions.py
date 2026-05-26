"""Low-level OS input actions, expressed in normalized model coordinates.

Every coordinate argument is in the model's [0, coord_scale] space; these
wrappers translate to logical screen points and drive the real mouse/keyboard
through pyautogui.
"""
from __future__ import annotations

import time

import pyautogui

from .config import CONFIG
from .screen import norm_to_screen

pyautogui.FAILSAFE = CONFIG.failsafe
# Small global pause between pyautogui primitives so the OS/UI keeps up.
pyautogui.PAUSE = 0.05


def _move(nx: float, ny: float) -> tuple[int, int]:
    x, y = norm_to_screen(nx, ny)
    pyautogui.moveTo(x, y, duration=0.15)
    return x, y


def move(nx: float, ny: float) -> str:
    x, y = _move(nx, ny)
    return f"moved cursor to screen point ({x}, {y})"


def click(nx: float, ny: float, button: str = "left", clicks: int = 1) -> str:
    x, y = _move(nx, ny)
    pyautogui.click(x=x, y=y, clicks=clicks, interval=0.08, button=button)
    label = {1: "", 2: "double-", 3: "triple-"}.get(clicks, f"{clicks}x ")
    return f"{label}{button}-clicked at screen point ({x}, {y})"


def double_click(nx: float, ny: float) -> str:
    return click(nx, ny, button="left", clicks=2)


def right_click(nx: float, ny: float) -> str:
    return click(nx, ny, button="right", clicks=1)


def drag(from_x: float, from_y: float, to_x: float, to_y: float) -> str:
    sx, sy = norm_to_screen(from_x, from_y)
    ex, ey = norm_to_screen(to_x, to_y)
    pyautogui.moveTo(sx, sy, duration=0.15)
    pyautogui.dragTo(ex, ey, duration=0.5, button="left")
    return f"dragged from ({sx}, {sy}) to ({ex}, {ey})"


def type_text(text: str) -> str:
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
