"""Command-line entrypoint: run the computer-use agent against the live screen.

Human use:    python -m qwen_cua.cli "Solve the CAPTCHA on screen"
Process use:  python -m qwen_cua.cli --json --quiet "..."   # result JSON on stdout
Exit code: 0 if the agent reported success, 1 otherwise, 2 on bad usage.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .agent import Agent

DEFAULT_GOAL = (
    "Solve the CAPTCHA visible on screen. If it is a reCAPTCHA checkbox, click "
    "'I'm not a robot' and complete any image challenge that appears. Call done "
    "when the page indicates verification succeeded."
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Qwen3.6 OS-level computer-use agent")
    p.add_argument("goal", nargs="?", default=DEFAULT_GOAL, help="Task for the agent.")
    p.add_argument("--delay", type=float, default=3.0,
                   help="Seconds to wait before starting (bring the target window to front).")
    p.add_argument("--run-dir", default=None,
                   help="Directory for per-step screenshots (default: runs/<timestamp>).")
    p.add_argument("--json", action="store_true",
                   help="Print the result as a single JSON object on stdout (for callers).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress the step-by-step log (recommended with --json).")
    args = p.parse_args(argv)

    run_dir = args.run_dir or str(
        Path(__file__).resolve().parent.parent / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )

    if args.delay > 0 and not args.json:
        print(f"Starting in {args.delay:g}s — bring the target window to the front…")
    if args.delay > 0:
        time.sleep(args.delay)

    agent = Agent(run_dir=run_dir, verbose=not (args.quiet or args.json))
    result = agent.run(args.goal)

    if args.json:
        payload = result.to_dict()
        payload["run_dir"] = run_dir
        print(json.dumps(payload))
    else:
        print("\n" + "=" * 60)
        print(f"success={result.success}  stopped={result.stopped_reason}")
        print(f"summary: {result.summary}")
        print(f"steps: {len(result.steps)}  screenshots: {run_dir}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
