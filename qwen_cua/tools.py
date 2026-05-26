"""Tool schemas (OpenAI function-calling) and dispatch to OS actions.

All x/y coordinates are in the model's normalized [0, coord_scale] space.
"""
from __future__ import annotations

import json
from typing import Any

from . import actions

_COORD = "Normalized coordinate in [0, 1000], independent of screen resolution."

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a fresh screenshot of the screen WITHOUT acting. "
            "Use to re-examine the current state before deciding.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Left-click once at the given point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": _COORD},
                    "y": {"type": "number", "description": _COORD},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "double_click",
            "description": "Double left-click at the given point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": _COORD},
                    "y": {"type": "number", "description": _COORD},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "right_click",
            "description": "Right-click at the given point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": _COORD},
                    "y": {"type": "number", "description": _COORD},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move the cursor to a point without clicking (e.g. to reveal hover state).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": _COORD},
                    "y": {"type": "number", "description": _COORD},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drag",
            "description": "Press the left button at (from_x, from_y), drag to (to_x, to_y), and release. "
            "Use for slider CAPTCHAs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_x": {"type": "number", "description": _COORD},
                    "from_y": {"type": "number", "description": _COORD},
                    "to_x": {"type": "number", "description": _COORD},
                    "to_y": {"type": "number", "description": _COORD},
                },
                "required": ["from_x", "from_y", "to_x", "to_y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type literal text at the current keyboard focus. Click the target field first.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Press a key or chord, e.g. 'enter', 'escape', 'cmd+a', 'ctrl+shift+t'.",
            "parameters": {
                "type": "object",
                "properties": {"keys": {"type": "string"}},
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the mouse wheel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "description": "Number of wheel clicks (1-10)."},
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                    },
                },
                "required": ["amount", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait for the UI to settle (seconds, max 10). Use after triggering a verification.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Finish the task. Call when the goal is achieved or is impossible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "summary": {"type": "string", "description": "Short outcome description."},
                },
                "required": ["success", "summary"],
            },
        },
    },
]


class Done(Exception):
    """Raised by the `done` tool to terminate the loop."""

    def __init__(self, success: bool, summary: str):
        self.success = success
        self.summary = summary
        super().__init__(summary)


def dispatch(name: str, args: dict[str, Any]) -> str:
    """Execute one tool call and return a short text observation."""
    if name == "screenshot":
        return "captured a fresh screenshot"
    if name == "click":
        return actions.click(args["x"], args["y"])
    if name == "double_click":
        return actions.double_click(args["x"], args["y"])
    if name == "right_click":
        return actions.right_click(args["x"], args["y"])
    if name == "move":
        return actions.move(args["x"], args["y"])
    if name == "drag":
        return actions.drag(args["from_x"], args["from_y"], args["to_x"], args["to_y"])
    if name == "type_text":
        return actions.type_text(args["text"])
    if name == "press_key":
        return actions.press_key(args["keys"])
    if name == "scroll":
        return actions.scroll(args["amount"], args.get("direction", "down"))
    if name == "wait":
        return actions.wait(args["seconds"])
    if name == "done":
        raise Done(bool(args.get("success", False)), str(args.get("summary", "")))
    return f"ERROR: unknown tool {name!r}"


def parse_args(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
