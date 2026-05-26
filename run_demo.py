"""End-to-end demo:
  1. Drive the local Chrome to hammer Google search until a CAPTCHA appears.
  2. Hand the visible window to the OS-level Qwen agent to solve it.
  3. Report whether the page left the CAPTCHA / sorry state.

Usage:
  PYTHONPATH=. .venv/bin/python run_demo.py [--max-queries N] [--keep-open]
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from qwen_cua.agent import Agent
from qwen_cua.google_captcha import bring_chrome_front, launch_and_trigger, looks_like_captcha

GOAL = (
    "A Google 'unusual traffic' / reCAPTCHA verification page is open in Chrome. "
    "Solve it: if there is an 'I'm not a robot' checkbox, click it and wait. If an "
    "image grid challenge appears, read the instruction and click every matching "
    "tile, then click the verify/next button, repeating until it is accepted. "
    "When the verification is gone and normal search results (or the home page) are "
    "shown, call done(success=true). If it is clearly unsolvable, call done(success=false)."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-queries", type=int, default=60)
    ap.add_argument("--keep-open", action="store_true", help="Leave Chrome open at the end.")
    args = ap.parse_args()

    print("Phase 1: hammering Google search to trigger a CAPTCHA…")
    t = launch_and_trigger(max_queries=args.max_queries)
    print(f"  queries fired: {t.queries_used}  captcha detected: {t.detected}")
    print(f"  current url: {t.page.url}")

    try:
        if not t.detected:
            print("No CAPTCHA appeared within the query budget. "
                  "Try raising --max-queries, or run again later (depends on IP reputation).")
            return 2

        print("\nPhase 2: handing the visible window to the OS-level agent…")
        bring_chrome_front()
        time.sleep(1.0)

        run_dir = Path("runs") / ("captcha-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        agent = Agent(run_dir=str(run_dir), verbose=True)
        result = agent.run(GOAL)

        # After a solve the /sorry page redirects to the original search URL,
        # but the Playwright page object can lag the top-level navigation. Poll
        # (and reload once) before judging, to avoid a false "not solved".
        still = looks_like_captcha(t.page)
        for _ in range(6):
            if not still:
                break
            time.sleep(1.5)
            try:
                t.page.reload(wait_until="domcontentloaded", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            still = looks_like_captcha(t.page)
        print("\n" + "=" * 60)
        print(f"agent: success={result.success} reason={result.stopped_reason} steps={len(result.steps)}")
        print(f"agent summary: {result.summary}")
        print(f"captcha still present (page check): {still}")
        print(f"final url: {t.page.url}")
        print(f"screenshots: {run_dir}")
        solved = result.success and not still
        print(f"VERDICT: {'SOLVED' if solved else 'NOT SOLVED'}")
        return 0 if solved else 1
    finally:
        if not args.keep_open:
            try:
                t.context.close()
                t.playwright.stop()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
