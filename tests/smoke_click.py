"""Smoke test: open a local page in Chrome and have the agent OS-click a button.

Verifies the full loop end-to-end (screenshot -> model 0-1000 coords -> OS click)
by checking the page turns green ('SUCCESS') after the agent acts.
"""
import subprocess
import time
from pathlib import Path

from PIL import Image

from qwen_cua.agent import Agent
from qwen_cua.screen import grab_screenshot

HERE = Path(__file__).resolve().parent
PAGE = HERE / "click_target.html"


def position_chrome():
    script = '''
    tell application "Google Chrome"
        activate
        set bounds of front window to {100, 80, 1400, 920}
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def green_fraction(img: Image.Image) -> float:
    small = img.resize((120, 78))
    px = list(small.getdata())
    green = sum(1 for r, g, b in px if g > 110 and r < 90 and b < 90)
    return green / len(px)


def main():
    subprocess.run(["open", "-a", "Google Chrome", str(PAGE)], check=True)
    time.sleep(2.5)
    position_chrome()
    time.sleep(1.0)

    before = green_fraction(grab_screenshot())
    print(f"green fraction before: {before:.3f}")

    agent = Agent(run_dir=str(HERE.parent / "runs" / "smoke"), verbose=True)
    result = agent.run(
        "There is a single large blue button labeled 'CLICK ME' in the browser page. "
        "Click it once. When the page background turns green, call done(success=true)."
    )

    time.sleep(0.8)
    after = green_fraction(grab_screenshot())
    print(f"\ngreen fraction after: {after:.3f}")
    clicked = after > 0.4
    print("=" * 50)
    print(f"agent: success={result.success} reason={result.stopped_reason} steps={len(result.steps)}")
    print(f"VERDICT: {'PASS — button was clicked' if clicked else 'FAIL — page did not turn green'}")
    return 0 if clicked else 1


if __name__ == "__main__":
    raise SystemExit(main())
