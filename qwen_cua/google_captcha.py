"""Drive the local Chrome (via Playwright) to hammer Google search until a
CAPTCHA / "unusual traffic" page appears.

The browser is launched headful with the real Chrome channel so the window is
visible on screen — that is what the OS-level agent will then operate on.
"""
from __future__ import annotations

import random
import subprocess
import time
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright

# Varied query terms; rapid heterogeneous querying tends to trip the bot check.
_TERMS = [
    "weather", "python list comprehension", "best ramen tokyo", "quantum entanglement",
    "how to tie a tie", "rust vs go", "macos screenshot shortcut", "fibonacci sequence",
    "longest river", "espresso ratio", "kubernetes pod", "newton's third law",
    "tallest mountain", "jazz chords", "regex lookahead", "sourdough starter",
    "black hole radius", "typescript generics", "marathon world record", "tea types",
]


def looks_like_captcha(page: Page) -> bool:
    url = page.url or ""
    if "/sorry/" in url or "captcha" in url.lower():
        return True
    try:
        if page.locator('iframe[src*="recaptcha"]').count() > 0:
            return True
        body = (page.inner_text("body", timeout=1500) or "").lower()
    except Exception:  # noqa: BLE001
        return False
    needles = [
        "unusual traffic", "not a robot", "our systems have detected",
        "i'm not a robot", "异常流量", "检测到", "verify you're human",
    ]
    return any(n in body for n in needles)


def bring_chrome_front() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to activate'],
        capture_output=True,
    )


@dataclass
class Triggered:
    playwright: object
    context: object
    page: Page
    detected: bool
    queries_used: int


def launch_and_trigger(max_queries: int = 60, user_data_dir: str = "/tmp/qwen-cua-chrome") -> Triggered:
    """Launch Chrome and search Google rapidly until a CAPTCHA appears.

    Returns the live Playwright handles with the browser left OPEN so the caller
    can hand the visible window to the OS agent. Caller must close them.
    """
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        channel="chrome",
        headless=False,
        viewport=None,  # use real window size
        args=["--window-position=120,80", "--window-size=1280,900"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    bring_chrome_front()

    # Handle the EU consent interstitial once, if present.
    try:
        page.goto("https://www.google.com/", wait_until="domcontentloaded", timeout=15000)
        for label in ("Accept all", "I agree", "Reject all", "全部接受"):
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                break
    except Exception:  # noqa: BLE001
        pass

    detected = False
    used = 0
    for i in range(max_queries):
        used = i + 1
        term = random.choice(_TERMS) + f" {random.randint(1, 9999)}"
        try:
            page.goto(
                f"https://www.google.com/search?q={term.replace(' ', '+')}&num=20",
                wait_until="domcontentloaded",
                timeout=15000,
            )
        except Exception:  # noqa: BLE001
            pass
        if looks_like_captcha(page):
            detected = True
            break
        time.sleep(random.uniform(0.05, 0.25))  # rapid-fire

    bring_chrome_front()
    time.sleep(0.5)
    return Triggered(pw, context, page, detected, used)
