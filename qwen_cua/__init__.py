"""OS-level computer-use agent driven by a local Qwen3.6 VL model.

Public API:
    from qwen_cua import solve, Agent, RunResult, CONFIG
"""
from .agent import Agent, RunResult, StepRecord, solve
from .config import CONFIG

__all__ = ["solve", "Agent", "RunResult", "StepRecord", "CONFIG"]
