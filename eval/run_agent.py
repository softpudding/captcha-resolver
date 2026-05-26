"""The agent seam: how the harness invokes the real qwen_cua agent.

The runner hands us a goal (plain English) and a run_dir for the audit trail.
The agent then operates the REAL mouse/keyboard against whatever Chrome window
is currently in front — which the runner has already navigated to the replay
page and positioned. We return the agent's RunResult.

This is the one file to change if you swap in a different computer-use agent:
keep the ``run_case(goal, run_dir) -> result`` contract, where ``result`` has
``.success``, ``.summary``, ``.stopped_reason`` and ``.steps`` (list of records
with ``.tool``, ``.args``, ``.observation``).
"""
from __future__ import annotations

from pathlib import Path


def run_case(goal: str, run_dir: str | Path):
    # Imported lazily so --stub runs need neither the model server nor pyautogui.
    from qwen_cua.agent import Agent

    agent = Agent(run_dir=str(run_dir), verbose=False)
    return agent.run(goal)
