"""Runtime configuration.

All values can be overridden via environment variables so the package stays
usable without code edits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # --- Model endpoint (llama.cpp OpenAI-compatible server) ---
    # 8021 = direct qwen3.6-35b-a3b port; 8090 = local-llm-proxy.
    base_url: str = os.environ.get("QWEN_CUA_BASE_URL", "http://127.0.0.1:8021/v1")
    api_key: str = os.environ.get("QWEN_CUA_API_KEY", "sk-local")  # ignored by llama.cpp
    model: str = os.environ.get("QWEN_CUA_MODEL", "qwen3.6-35b-a3b")

    # --- Generation ---
    temperature: float = float(os.environ.get("QWEN_CUA_TEMPERATURE", "0"))
    max_tokens: int = int(os.environ.get("QWEN_CUA_MAX_TOKENS", "1536"))
    request_timeout: float = float(os.environ.get("QWEN_CUA_TIMEOUT", "300"))

    # --- Coordinate convention ---
    # Qwen3.6-VL emits pixel operations in a normalized [0, COORD_SCALE] space
    # regardless of the actual image resolution it is shown.
    coord_scale: int = int(os.environ.get("QWEN_CUA_COORD_SCALE", "1000"))

    # --- Screenshot handling ---
    # Downscale the captured screenshot to this width before sending to the
    # model (saves vision tokens). Normalized coords are resolution-independent,
    # so this does not affect click accuracy.
    screenshot_width: int = int(os.environ.get("QWEN_CUA_SHOT_WIDTH", "1512"))
    # Keep only the most-recent N screenshots in the message history as images;
    # older ones are replaced with a text placeholder to bound context size.
    keep_recent_images: int = int(os.environ.get("QWEN_CUA_KEEP_IMAGES", "2"))

    # --- Agent loop ---
    max_steps: int = int(os.environ.get("QWEN_CUA_MAX_STEPS", "25"))
    # Pause after each action before grabbing the observation screenshot, to let
    # the UI settle (animations, page repaint).
    settle_seconds: float = float(os.environ.get("QWEN_CUA_SETTLE", "0.6"))

    # --- Human-like input ---
    # Robotic, instant, evenly-timed input is a classic bot fingerprint. When
    # enabled, each action waits a randomized gap before acting and the cursor
    # glides with smooth easing at a randomized speed.
    human_like: bool = os.environ.get("QWEN_CUA_HUMAN", "1") != "0"
    # Inter-operation gap = op_gap_base + uniform(0, op_gap_jitter) seconds.
    op_gap_base: float = float(os.environ.get("QWEN_CUA_OP_GAP", "1.0"))
    op_gap_jitter: float = float(os.environ.get("QWEN_CUA_OP_GAP_JITTER", "0.5"))
    # Cursor travel time is drawn uniformly from [move_dur_min, move_dur_max] s.
    move_dur_min: float = float(os.environ.get("QWEN_CUA_MOVE_MIN", "0.35"))
    move_dur_max: float = float(os.environ.get("QWEN_CUA_MOVE_MAX", "0.85"))
    # Small random click-point jitter (logical px) so clicks aren't pixel-exact.
    click_jitter_px: int = int(os.environ.get("QWEN_CUA_CLICK_JITTER", "2"))

    # --- Safety ---
    # pyautogui failsafe: slamming the mouse into a screen corner aborts.
    failsafe: bool = os.environ.get("QWEN_CUA_FAILSAFE", "1") != "0"


CONFIG = Config()
