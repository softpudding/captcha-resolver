# Qwen Computer-Use CAPTCHA Solver

An OS-level **computer-use agent** that solves CAPTCHAs (and other on-screen
tasks) by looking at the **real screen** and driving the **real mouse and
keyboard**. It is powered by a locally-hosted **Qwen3.6-35B-A3B** vision-language
model and runs a ReAct tool-calling loop: *screenshot → reason → click/type →
new screenshot*.

Because it operates the actual OS input devices, it works on **any visible
window** — including browser reCAPTCHA checkboxes, image-grid challenges, slider
puzzles, and distorted-text boxes.

> Verified end-to-end: triggered a Google "unusual traffic" reCAPTCHA, clicked
> *I'm not a robot*, solved the image-grid challenge, and reached search results.

---

## Preconditions

You must satisfy **all** of these before calling the solver:

1. **Model server running.** Qwen3.6-35B-A3B served by llama.cpp at an
   OpenAI-compatible endpoint (default `http://127.0.0.1:8021/v1`). Start it with
   the `~/git/local-llms` runbook:
   ```bash
   cd ~/git/local-llms && ./scripts/start-llm qwen --background
   ./scripts/status-llm          # qwen3.6-35b-a3b must show as up on :8021
   ```
   The endpoint must support tool-calling and have the vision projector loaded
   (it does by default).

2. **macOS permissions granted to the controlling terminal/process.** The app
   that launches the Python process needs:
   - **Screen Recording** — for `screencapture` (otherwise screenshots are blank).
   - **Accessibility** — for `pyautogui` mouse/keyboard control.

   System Settings → Privacy & Security → Screen Recording / Accessibility.

3. **A graphical session.** This is **not headless** — it controls the physical
   display. Run it on the machine you can see, and **keep hands off the mouse and
   keyboard while it runs**. Slam the cursor into a screen corner to abort
   (pyautogui failsafe).

4. **Installed.**
   ```bash
   cd ~/git/captcha-solver
   uv venv --python 3.12 && uv pip install -e .
   ```
   (Playwright + the local Chrome channel are only needed for the bundled Google
   demo, not for calling the solver itself.)

---

## What "calling it" does

You pass a **goal** in plain English. The agent takes over the mouse/keyboard,
acts against **whatever is currently on screen**, and returns a result describing
whether it succeeded. It does **not** open windows or navigate for you — put the
target (e.g. the CAPTCHA page) in front first.

---

## Usage

The repo root must be on `PYTHONPATH` (the editable install resolves via cwd):

### 1. From another Python process (in-process)

```python
from qwen_cua import solve

result = solve("Solve the CAPTCHA visible on screen")
print(result.success, result.summary)
# result.to_dict() -> JSON-serializable dict with per-step actions
```

`solve()` blocks until the agent finishes (success, gives up, or hits the step
cap). For more control, use the `Agent` class:

```python
from qwen_cua import Agent

agent = Agent(run_dir="runs/job123", verbose=False)  # writes audit trail (see Auditing)
result = agent.run("Click the 'I'm not a robot' checkbox and pass any challenge")
```

### 2. From any process via the CLI (JSON contract)

```bash
cd ~/git/captcha-solver
PYTHONPATH=. .venv/bin/python -m qwen_cua.cli --json --quiet --delay 0 \
    "Solve the CAPTCHA visible on screen"
```

- **stdout**: a single JSON object (see schema below).
- **exit code**: `0` if the agent reported success, `1` otherwise.

Example consuming it from a shell script:

```bash
out=$(PYTHONPATH=. .venv/bin/python -m qwen_cua.cli --json --quiet --delay 0 "$GOAL")
echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["summary"])'
```

#### Result JSON schema

```jsonc
{
  "success": true,                 // agent's own success/failure verdict
  "summary": "…",                  // short natural-language outcome
  "stopped_reason": "done",        // done | max_steps | no_tool_call | api_error: …
  "run_dir": "runs/2026…",         // where per-step screenshots were saved
  "num_steps": 7,
  "steps": [
    {"index": 1, "tool": "click", "args": {"x": 500, "y": 513},
     "observation": "left-clicked at screen point (756, 504)"}
    // …
  ]
}
```

> **Verdict caveat:** `success` is the *model's* judgment of the final screen, not
> an independent oracle. For high-stakes flows, have the caller re-check ground
> truth (e.g. the page left the CAPTCHA state) before trusting it.

---

## Auditing (run logs)

Every run with a `run_dir` writes a complete, durable audit trail. Auditing is
**on by default**: `solve(...)` and the CLI create a timestamped directory under
`runs/` automatically. Pass an explicit path to choose the location, or
`solve(..., run_dir=False)` to disable all on-disk logging.

Each run directory contains:

| File | Contents |
| --- | --- |
| `transcript.jsonl` | Append-only, one JSON event per line: the **system prompt**, every **user message**, every **assistant message** (including `reasoning`, `content`, `tool_calls`, `finish_reason`, token `usage`), and every **tool result** (name, args, observation). |
| `step_NN.png` | The exact **screenshot** sent to the model at each turn. User-message events reference these by filename (the image isn't inlined as base64, to keep the log small). |
| `result.json` | The final `RunResult` (same shape as the CLI's `--json` output). |

Event kinds in `transcript.jsonl` (each has `seq`, `ts` (UTC ISO-8601), `kind`):

- `run_start` — `goal`, `model`, `base_url`, `coord_scale`, `screen`, `max_steps`, full `system_prompt`.
- `message` — `role` (`system`/`user`/`assistant`) with the fields above; user messages carry `screenshot`.
- `tool_result` — `tool_call_id`, `name`, `args`, `observation`.
- `error` — an API failure during a turn.
- `run_end` — the final result summary.

Reconstruct the full conversation for an audit:

```bash
python3 - <<'PY'
import json
for line in open("runs/<timestamp>/transcript.jsonl"):
    e = json.loads(line)
    print(e["seq"], e["ts"], e["kind"], e.get("role",""), e.get("screenshot") or "")
PY
```

> The screenshots are the literal images the model saw; pairing each `message`
> (user) event's `screenshot` with the following `assistant` event shows exactly
> what the model was looking at when it chose each action.

## Configuration

All settings are env-overridable (see `qwen_cua/config.py`). Common ones:

| Env var | Default | Purpose |
| --- | --- | --- |
| `QWEN_CUA_BASE_URL` | `http://127.0.0.1:8021/v1` | Model endpoint (use `…:8090/v1` for the local-llm proxy). |
| `QWEN_CUA_MODEL` | `qwen3.6-35b-a3b` | Model id. |
| `QWEN_CUA_MAX_STEPS` | `25` | Hard cap on agent turns. |
| `QWEN_CUA_SHOT_WIDTH` | `1512` | Screenshot downscale width (tokens vs. detail). |
| `QWEN_CUA_KEEP_IMAGES` | `2` | Recent screenshots kept in the model's context. |
| `QWEN_CUA_SETTLE` | `0.6` | Seconds to wait after each action before observing. |
| `QWEN_CUA_FAILSAFE` | `1` | Corner-slam abort (set `0` to disable). |
| `QWEN_CUA_HUMAN` | `1` | Human-like input: randomized gaps + smooth, random-speed cursor (set `0` for instant/robotic). |
| `QWEN_CUA_OP_GAP` / `QWEN_CUA_OP_GAP_JITTER` | `1.0` / `0.5` | Per-action gap = base + `uniform(0, jitter)` seconds. |
| `QWEN_CUA_MOVE_MIN` / `QWEN_CUA_MOVE_MAX` | `0.35` / `0.85` | Cursor travel time range (eased, randomized). |
| `QWEN_CUA_CLICK_JITTER` | `2` | Random click-point jitter in logical px (avoids pixel-exact clicks). |

The model's coordinate convention (`[0,1000]` normalized grid, mapped to logical
screen points) is handled internally — callers never deal with pixels.

---

## Tools the agent can use

`click`, `double_click`, `right_click`, `move`, `drag` (sliders), `type_text`,
`press_key` (e.g. `cmd+a`, `enter`), `scroll`, `wait`, `screenshot`, and `done`.

---

## Bundled demo & test (optional)

- **End-to-end Google demo** — drives a local Chrome to hammer Google search
  until a CAPTCHA appears, then hands the window to the agent:
  ```bash
  PYTHONPATH=. .venv/bin/python run_demo.py --max-queries 40
  ```
- **Smoke test** — opens a local page and checks the agent can OS-click a button:
  ```bash
  PYTHONPATH=. .venv/bin/python tests/smoke_click.py
  ```

---

## Package layout

| Path | Purpose |
| --- | --- |
| `qwen_cua/__init__.py` | Public API: `solve`, `Agent`, `RunResult`, `CONFIG`. |
| `qwen_cua/agent.py` | The ReAct loop. |
| `qwen_cua/tools.py` | Tool schemas + dispatch. |
| `qwen_cua/actions.py` | pyautogui input wrappers. |
| `qwen_cua/screen.py` | Screenshot + `0–1000`↔screen coordinate mapping. |
| `qwen_cua/config.py` | Env-overridable settings. |
| `qwen_cua/cli.py` | CLI / JSON entrypoint. |
| `qwen_cua/google_captcha.py` | Playwright Google-CAPTCHA trigger (demo only). |
| `run_demo.py` | Full trigger→solve→verify demo. |
| `tests/smoke_click.py` | Self-checking OS-control smoke test. |

---

## Limitations

- **Not headless / not concurrent.** One agent owns the single physical display
  and input devices at a time. Don't run two solvers at once, and don't use the
  machine while it works.
- **reCAPTCHA varies run-to-run.** Automation-flagged browsers (CDP/Playwright)
  are penalized, so image challenges can loop; success is not guaranteed.
- **Grounding is imperfect.** A 35B VL model occasionally misreads small grid
  tiles or misjudges the final state. The per-step re-screenshotting helps it
  self-correct, but verify critical outcomes downstream.
