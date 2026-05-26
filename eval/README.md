# CAPTCHA solver eval harness

An evaluation harness for the `qwen_cua` computer-use agent. It puts **real
Google reCAPTCHA challenges** (captured once, replayed locally and
deterministically) on screen, lets the agent operate the real mouse/keyboard to
solve them, then reads an **independent page oracle** to score the outcome —
separately from what the agent *claims*.

Read `DESIGN.md` first: it explains the four design decisions (capture-and-replay
sim env, static oracle scoring, result-primary with trace kept, the 10-case
dataset) in plain terms. This README is the operational how-to.

## Layout

```
eval/
  DESIGN.md            design rationale (read first)
  cases.jsonl          the 10 cases, as data — one JSON object per line
  capture_recaptcha.py captures real Google challenges -> tasks/ fixtures
  tasks/<fixture>/      captured fixture: meta.json, grid.png, tiles/NN.png
  replay/              index.html + app.js: faithful reCAPTCHA replica + oracle
  scorers/             one file per scored dimension
  run_agent.py         the seam: how the harness calls the real agent
  runner.py            the case loop + console report
  results/<version>/   JSONL run records (one line per case) — gitignored
```

## Running

```bash
# 1. Validate the harness itself (no model, no real mouse): a stub solves each
#    page programmatically via the DOM. Expect ~10/10 pass.
PYTHONPATH=. .venv/bin/python eval/runner.py --stub solve

# 2. Validate the fail path: a stub that does nothing. Expect 1/10 (audio only).
PYTHONPATH=. .venv/bin/python eval/runner.py --stub noop

# 3. The real run. Drives the ACTUAL mouse/keyboard via the qwen_cua agent.
#    Needs the Qwen model server up (see ../README.md) and macOS Screen
#    Recording + Accessibility permissions. KEEP HANDS OFF the mouse/keyboard
#    while it runs; slam the cursor into a screen corner to abort.
PYTHONPATH=. .venv/bin/python eval/runner.py

# Run a single case (handy while iterating):
PYTHONPATH=. .venv/bin/python eval/runner.py --case 04_dynamic_crosswalks_3x3
```

Each run prints a PASS/FAIL line per case and a headline: **cases passed**,
**solved-rate** (the ground-truth oracle, over solvable cases), **verdict-honesty**
(how often the agent's self-reported success matched reality), and median
steps/latency. Full per-dimension records (+ the agent's audit trail under
`results/<version>/runs/`) are written to `results/<version>/<timestamp>.jsonl`.

## What each score means

- **solved** — primary, the page's own verdict. The oracle flips to `solved`
  only when the correct tile set is selected and Verify pressed (or the checkbox
  passed / Skip pressed correctly). Cannot be gamed by random clicking.
- **verdict_honest** — does `done(success=…)` match the oracle? Flags
  `over_confident` (claims success when not solved) — the most dangerous mode.
- **tile_grounding** — precision/recall of the agent's first-attempt tile
  selection vs the answer key. Diagnostic, not a gate.
- **persistence** — for dynamic / retry / multiround / skip: did it complete
  every round, or give up early?

## Adding a case

1. Capture more real challenges: `PYTHONPATH=. .venv/bin/python eval/capture_recaptcha.py --max 12`.
   New fixtures land in `tasks/`.
2. **Label the answer key** by viewing `tasks/<fixture>/grid.png` and deciding,
   for each tile (row-major, 0-based): is it clearly the object (`required`),
   clearly not (`forbidden`), or ambiguous (`optional`)?
3. Add a line to `cases.jsonl` referencing the fixture and your tile sets. Pick
   a `kind`: `grid`, `dynamic`, `retry`, `multiround`, `skip`, `checkbox`,
   `interstitial`, or `audio`.
4. Run `--stub solve --case <id>` to confirm a perfect solver reaches `solved`
   (i.e. your answer key and the replay mode agree). Then run for real.

Cases are **data, not code** — review and hand-edit them in `cases.jsonl`.

## Adding a scored dimension

Add `scorers/<name>.py` with a `score(case, oracle, result) -> dict | None`
function returning `{dimension, passed, value, details}` (or `None` when it
doesn't apply to a case). Register it in `scorers/__init__.py`. Keep each
dimension separate — never collapse them into one number at scoring time.

## Note on the fixtures

`tasks/` holds real imagery captured from Google's public reCAPTCHA demo, used
locally only as a frozen, resettable test set. The answer keys are our own
human labels with reCAPTCHA-style tolerance (`required`/`forbidden`/`optional`),
so an honestly-debatable edge tile never forces every agent to fail.
