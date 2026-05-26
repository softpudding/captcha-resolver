"""ReAct tool-calling agent loop.

Each turn: the model sees the latest screenshot, emits tool call(s); we execute
them on the real OS, then feed back a fresh screenshot as the observation.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from .config import CONFIG
from .screen import grab_screenshot, image_to_data_url, screen_size
from .tools import TOOLS, Done, dispatch, parse_args

SYSTEM_PROMPT = """\
You are a computer-use agent operating a real macOS computer through screenshots \
and input tools. You can see the screen only through the screenshots you are given.

COORDINATE SYSTEM (critical):
- Every screenshot is mapped to a normalized grid. The top-left of the image is \
(0, 0) and the bottom-right is (1000, 1000), REGARDLESS of the image's pixel size.
- All x/y arguments you pass to tools MUST be integers in [0, 1000] in that grid.
- Aim for the CENTER of the element you want to interact with.

HOW TO WORK:
- Look at the current screenshot, reason briefly, then call exactly one tool.
- After each action you receive an updated screenshot as the observation. Use it \
to verify the effect before the next step.
- To type into a field, click it first to focus, then call type_text.
- Call `done` when the goal is achieved, or if it is genuinely impossible.

SOLVING CAPTCHAS:
- reCAPTCHA checkbox ("I'm not a robot"): click the checkbox square once and wait.
- Image grid challenge: read the instruction (e.g. "select all squares with \
traffic lights"), click EACH matching tile, then click the verify/next/skip button. \
If new images fade in after a click, re-examine and keep selecting until none match.
- Slider/puzzle: use `drag` to move the slider handle to the gap.
- Distorted text: read the characters and type them into the answer field.
Be precise and deliberate. One tool call per turn.
"""


@dataclass
class StepRecord:
    index: int
    reasoning: str
    tool: str
    args: dict[str, Any]
    observation: str


@dataclass
class RunResult:
    success: bool
    summary: str
    steps: list[StepRecord] = field(default_factory=list)
    stopped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view, for cross-process callers."""
        return {
            "success": self.success,
            "summary": self.summary,
            "stopped_reason": self.stopped_reason,
            "num_steps": len(self.steps),
            "steps": [
                {"index": s.index, "tool": s.tool, "args": s.args, "observation": s.observation}
                for s in self.steps
            ],
        }


def solve(
    goal: str,
    *,
    run_dir: str | Path | bool | None = None,
    verbose: bool = False,
) -> RunResult:
    """One-shot convenience: run the agent against the current screen.

    >>> from qwen_cua import solve
    >>> r = solve("Solve the CAPTCHA on screen")
    >>> r.success, r.summary

    The agent operates the REAL mouse/keyboard on whatever is on screen now.

    Auditing is on by default: when ``run_dir`` is None a timestamped directory
    under ``runs/`` is created with ``transcript.jsonl``, per-step screenshots,
    and ``result.json``. Pass an explicit path to choose the location, or
    ``run_dir=False`` to disable all on-disk logging.
    """
    if run_dir is False:
        rd: str | Path | None = None
    elif run_dir is None:
        rd = Path(__file__).resolve().parent.parent / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    else:
        rd = run_dir
    return Agent(run_dir=rd, verbose=verbose).run(goal)


class Agent:
    def __init__(self, run_dir: str | Path | None = None, verbose: bool = True):
        self.client = OpenAI(base_url=CONFIG.base_url, api_key=CONFIG.api_key)
        self.verbose = verbose
        self.run_dir = Path(run_dir) if run_dir else None
        if self.run_dir:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._transcript = (self.run_dir / "transcript.jsonl").open("a", encoding="utf-8")
        else:
            self._transcript = None
        self.messages: list[dict[str, Any]] = []
        self._shot_count = 0
        self._seq = 0

    # ---- audit transcript ----
    def _record(self, kind: str, **fields: Any) -> None:
        """Append one audit event to transcript.jsonl (no-op without a run_dir)."""
        if not self._transcript:
            return
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        self._transcript.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._transcript.flush()

    # ---- screenshot / observation helpers ----
    def _capture(self, note: str) -> tuple[list[dict[str, Any]], str | None]:
        """Grab a screenshot, persist it as a PNG, and build the message content.

        Returns the OpenAI content blocks and the saved screenshot's filename
        (None if no run_dir), so the caller can reference it in the transcript.
        """
        img = grab_screenshot()
        fname = None
        if self.run_dir:
            self._shot_count += 1
            fname = f"step_{self._shot_count:02d}.png"
            img.save(self.run_dir / fname)
        content = [
            {"type": "text", "text": note},
            {"type": "image_url", "image_url": {"url": image_to_data_url(img)}},
        ]
        return content, fname

    def _prune_old_images(self) -> None:
        """Keep only the most recent N images; replace older ones with text."""
        keep = CONFIG.keep_recent_images
        img_msgs = [
            m for m in self.messages
            if isinstance(m.get("content"), list)
            and any(c.get("type") == "image_url" for c in m["content"])
        ]
        for m in img_msgs[:-keep] if keep > 0 else img_msgs:
            m["content"] = [
                {"type": "text", "text": "[earlier screenshot omitted to save context]"}
                if c.get("type") == "image_url" else c
                for c in m["content"]
            ]

    def _log(self, *a: Any) -> None:
        if self.verbose:
            print(*a, flush=True)

    # ---- main loop ----
    def run(self, goal: str) -> RunResult:
        w, h = screen_size()
        # Audit: capture the full run context up front.
        self._record(
            "run_start",
            goal=goal,
            model=CONFIG.model,
            base_url=CONFIG.base_url,
            coord_scale=CONFIG.coord_scale,
            screen=[w, h],
            max_steps=CONFIG.max_steps,
            system_prompt=SYSTEM_PROMPT,
        )

        init_content, init_shot = self._capture("(initial screenshot)")
        intro = (
            f"Screen is {w}x{h} logical points, normalized to a 0-1000 grid.\n\n"
            f"Goal: {goal}\n\nHere is the current screen:"
        )
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [{"type": "text", "text": intro}, init_content[1]]},
        ]
        self._record("message", role="system", text=SYSTEM_PROMPT)
        self._record("message", role="user", text=intro, screenshot=init_shot)

        result = RunResult(success=False, summary="", stopped_reason="max_steps")
        nudges = 0

        for step in range(1, CONFIG.max_steps + 1):
            self._prune_old_images()
            try:
                resp = self.client.chat.completions.create(
                    model=CONFIG.model,
                    messages=self.messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=CONFIG.temperature,
                    max_tokens=CONFIG.max_tokens,
                    timeout=CONFIG.request_timeout,
                )
            except Exception as e:  # noqa: BLE001
                result.stopped_reason = f"api_error: {e}"
                self._log(f"[step {step}] API error: {e}")
                self._record("error", step=step, message=str(e))
                break

            msg = resp.choices[0].message
            reasoning = getattr(msg, "reasoning_content", None) or ""
            tool_calls = msg.tool_calls or []

            if reasoning:
                self._log(f"\n[step {step}] think: {reasoning.strip()[:400]}")

            # Record the assistant turn verbatim (preserving tool_calls).
            tc_log = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
            assistant_entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if tool_calls:
                assistant_entry["tool_calls"] = tc_log
            self.messages.append(assistant_entry)

            usage = getattr(resp, "usage", None)
            self._record(
                "message",
                role="assistant",
                step=step,
                reasoning=reasoning,
                content=msg.content or "",
                tool_calls=tc_log,
                finish_reason=resp.choices[0].finish_reason,
                usage=usage.model_dump() if usage else None,
            )

            if not tool_calls:
                # The model answered in prose instead of acting.
                content = (msg.content or "").strip()
                self._log(f"[step {step}] (no tool call) {content[:300]}")
                if nudges < 2:
                    nudges += 1
                    nudge = ("Please act using a tool, or call `done` if the task is "
                             "complete or impossible.")
                    self.messages.append({"role": "user", "content": nudge})
                    self._record("message", role="user", step=step, text=nudge)
                    continue
                result.summary = content or "model stopped without acting"
                result.stopped_reason = "no_tool_call"
                break

            # Execute each tool call; collect observations.
            terminated = False
            for tc in tool_calls:
                name = tc.function.name
                args = parse_args(tc.function.arguments)
                self._log(f"[step {step}] action: {name}({args})")
                try:
                    obs = dispatch(name, args)
                except Done as d:
                    result.success = d.success
                    result.summary = d.summary
                    result.stopped_reason = "done"
                    result.steps.append(StepRecord(step, reasoning, name, args, "done"))
                    self.messages.append({
                        "role": "tool", "tool_call_id": tc.id, "content": "task ended",
                    })
                    self._record("tool_result", step=step, tool_call_id=tc.id, name=name,
                                 args=args, observation="task ended")
                    terminated = True
                    self._log(f"[step {step}] DONE success={d.success}: {d.summary}")
                    break
                except Exception as e:  # noqa: BLE001
                    obs = f"ERROR executing {name}: {e}"

                result.steps.append(StepRecord(step, reasoning, name, args, obs))
                self._log(f"[step {step}] result: {obs}")
                # Tool-role ack (text only — keep images in user messages).
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": obs})
                self._record("tool_result", step=step, tool_call_id=tc.id, name=name,
                             args=args, observation=obs)

            if terminated:
                break

            # Settle, then feed back a fresh screenshot as the observation.
            time.sleep(CONFIG.settle_seconds)
            obs_content, obs_shot = self._capture("Screen after the action(s):")
            self.messages.append({"role": "user", "content": obs_content})
            self._record("message", role="user", step=step,
                         text="Screen after the action(s):", screenshot=obs_shot)

        self._record("run_end", **result.to_dict())
        if self.run_dir:
            (self.run_dir / "result.json").write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if self._transcript:
            self._transcript.close()
            self._transcript = None
        return result
