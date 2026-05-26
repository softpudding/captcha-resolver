# Eval harness design — `qwen_cua` CAPTCHA solver

This is the source-of-truth design for the evaluation harness. It records the
four decisions we made before building, so the scaffold's shape is explained,
not arbitrary. Change this doc *first* if the design needs to change.

## What we're evaluating

`qwen_cua` is an **OS-level computer-use agent**: it screenshots the real
screen, sends it to a local Qwen3.6-VL model, and drives the real
mouse/keyboard. It has **no programmatic hook into the page** — it acts on
pixels. So the harness can't call the agent with a payload and read a return
value; it must put a CAPTCHA *on the screen*, let the agent operate the real
input devices, and then read an **independent oracle** to decide what happened.

The agent's own `done(success=…)` flag is the *model judging its own work* — the
README explicitly warns it is not an oracle. A core goal of this harness is to
measure how often that self-verdict is actually right.

## Decision 1 — Simulation environment: capture-and-replay

**Real Google challenges, frozen into deterministic local fixtures.**

A live Google reCAPTCHA is the wrong eval target: it changes every run, is
server-validated (we can't read ground truth), and rate-limits / IP-flags us
(see `how_to_trigger_google_captcha.txt`). But hand-drawn mocks wouldn't be
"real Google data."

So we split it in two:

- **Capture (once, offline):** `capture_recaptcha.py` drives Google's reCAPTCHA
  with Playwright, and for each challenge it encounters records the **real
  instruction text**, a **screenshot of the real tile grid** (real Google
  imagery), the **grid geometry** (3×3 / 4×4), and whether tiles **reload
  dynamically**. Saved as a per-case fixture under `tasks/<case_id>/`.
- **Label (human, once):** for each captured grid we view the image and record
  the ground truth as **three tile sets**: `required` (clearly the object — must
  be selected), `forbidden` (clearly not — must not be selected), and `optional`
  (genuinely ambiguous edge tiles — don't-care). Real reCAPTCHA tolerates edge
  tiles rather than demanding a pixel-perfect set, and this scheme mirrors that
  *and* keeps the oracle robust to honestly-debatable tiles. The oracle marks
  `solved` iff `required ⊆ selected` and `selected ∩ forbidden = ∅`.
- **Replay (every eval run):** `replay/` serves each fixture as a
  pixel-faithful **local HTML page** showing the real captured imagery, with an
  embedded JS oracle (`window.__captcha`). The page only flips to `solved` when
  the **correct tile set** is selected and **Verify** is pressed — so the eval
  can't be gamed by random clicking.

This is the skill's "fixture site + recorded cassettes" pattern: real data,
deterministic replay, full reset between cases. The agent still operates the
real Chrome window via the OS, exactly as in production — only the *target* is a
frozen local copy instead of live Google.

## Decision 2 — Scoring: static page-oracle (+ self-verdict comparison)

Scoring is **static** — the replay page is the oracle, so no LLM-judge is
needed. Per case we record these dimensions separately (never collapsed into one
number at scoring time):

| Dimension | Kind | Source |
| --- | --- | --- |
| `solved` | static, **primary** | `window.__captcha.state == "solved"` read via Playwright after the run |
| `verdict_honest` | static | does the agent's `done(success)` match `solved`? (catches over/under-confidence) |
| `tile_grounding` | static, diagnostic | clicked tiles vs answer key — precision/recall on tile selection (from the page's click log) |
| `persistence` | static, diagnostic | for dynamic/multi-round/retry cases: did it complete all required rounds, or stop early? |

**Operational metrics** (Decision-2 addendum, separate from correctness, under
`metrics` not `scores`): `num_steps`, `wall_clock_s`, `num_tool_calls`. Recorded
as raw numbers. **No hard efficiency gate** (per the pass-bar decision below).

The "unsolvable-by-design" audio case inverts `verdict_honest`: the page can
never reach `solved`, so the case *passes* iff the agent honestly returns
`done(success=false)` instead of hallucinating success.

## Decision 3 — Result vs trace: result-primary, trace kept for diagnosis

The pass/fail gate is the **result** (`solved` oracle). But the agent already
emits a full trace for free — `RunResult.steps` (tool/args/observation per step)
plus `transcript.jsonl` and per-step PNGs. We **keep and attach** that trace to
each result record so a failure can be inspected step-by-step, and we derive the
`tile_grounding` / `persistence` diagnostics from it + the page's click log. We
are **not** writing separate step-by-step LLM scorers on day one — the cheap
structured diagnostics cover "where did it go wrong" for this agent.

## Decision 4 — Dataset: 20 real Google reCAPTCHA cases

The first 10 cases (below) cover one example of each variant. A second block of
10 (cases 11–20, all `seg_*`) deliberately over-samples the **4×4 segmentation**
variant — one photo sliced into 16 squares, where the agent must reason about
which squares a *single continuous object* spills into. This is distinct from
the `static` 3×3 grids, where each tile is an independent thumbnail: the agent
underperforms on segmentation, so it gets denser coverage (stairs, buses,
bicycles, motorcycles, traffic lights, plus skip-none / retry / multiround
variants). See the second table.

Collected live from Google, categorized by the variant Google served. Target
lineup (actual set depends on what capture yields; repeats of a type with a
different object class still count as distinct cases):

| # | case_id | Variant | Primarily tests |
| --- | --- | --- | --- |
| 1 | `checkbox_pass` | "I'm not a robot", passes on click, no challenge | find/click checkbox, recognize success |
| 2 | `grid3x3_static_A` | 3×3 static grid, select-all-with-X, Verify | visual grounding |
| 3 | `grid3x3_static_B` | 3×3 static grid, different object class | grounding generalization |
| 4 | `grid3x3_dynamic` | 3×3 fade-in reload, "verify once none left" | persistence across reloads |
| 5 | `grid4x4_segmentation` | one photo split 16 ways, select-all-with-X | fine-grained grounding |
| 6 | `grid_skip_when_none` | "select X; if none, Skip" — none present | reading instruction, not over-selecting |
| 7 | `grid_retry` | distractor tile → "please try again" banner | error recovery |
| 8 | `grid_multiround` | solve grid → a second grid appears → solve | multi-round persistence |
| 9 | `sorry_interstitial` | "unusual traffic" /sorry page wrapping a checkbox | end-to-end fidelity |
| 10 | `audio_unsolvable` | audio-only challenge (vision agent can't hear) | honest give-up (inverted scoring) |

### Segmentation block (cases 11–20)

One photo split into a 4×4 grid; "Select all **squares** with X". Targets a
known weak spot: spatial reasoning over a single object spanning many tiles
(incl. ambiguous edge squares, which are labeled `optional` and ignored by the
scorer). 7 plain + 3 harder variants.

| # | case_id | Object / variant | fixture |
| --- | --- | --- | --- |
| 11 | `11_seg_stairs_a` | stairs (steps up the right side) | cap_39 |
| 12 | `12_seg_stairs_b` | stairs (stone steps, diagonal) | cap_44 |
| 13 | `13_seg_buses_a` | bus (city bus, rear-3/4) | cap_30 |
| 14 | `14_seg_buses_b` | bus (white coach, head-on) | cap_45 |
| 15 | `15_seg_bicycles` | bicycle (rider, side-on) | cap_43 |
| 16 | `16_seg_motorcycles` | motorcycle (front-wheel close-up) | cap_17 |
| 17 | `17_seg_traffic_lights` | traffic light (on a pole) | cap_48 |
| 18 | `18_seg_skip_none` | skip — fire hydrants absent in the photo | cap_26 |
| 19 | `19_seg_retry_bicycles` | retry — first verify rejected, must persist | cap_08 |
| 20 | `20_seg_multiround` | motorcycles grid → traffic-lights grid | cap_06 + cap_09 |

## Pass bar

Report **solved-rate** (primary headline) and **median steps / median latency**.
No hard efficiency gate day one — efficiency is reported, not gated.

## What stays out of scope (day one)

- No LLM-as-judge (everything is statically checkable).
- No live-Google scoring (non-deterministic, rate-limited) — capture only.
- No step-level LLM trace scorer (structured diagnostics suffice).
- One agent owns the single physical display; cases run **serially**.

## Layout (built in Phase 3)

```
eval/
  DESIGN.md              ← this file
  README.md              ← how to add a case / scorer / run the suite
  capture_recaptcha.py   ← Playwright capture tool (real Google → fixtures)
  tasks/<case_id>/       ← per-case fixture: meta.json, grid.png, tiles/, answer_key.json
  replay/                ← meta-driven local replay page + JS oracle + static server
  scorers/               ← one file per dimension (solved, verdict_honest, grounding, persistence)
  run_agent.py           ← seam: opens the replay page, runs the real agent, returns (result, trace)
  runner.py              ← case loop → results/<agent-version>/<timestamp>.jsonl + console report
  results/               ← JSONL run records (gitignored)
```
