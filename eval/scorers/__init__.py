"""Per-dimension scorers for the CAPTCHA eval.

Each scorer is a function ``score(case, oracle, result) -> dict | None``:
  - ``case``   : the parsed case dict from cases.jsonl
  - ``oracle`` : the page's ``window.__captcha`` state, read after the agent ran
  - ``result`` : the agent's RunResult-like object (.success, .stopped_reason, .steps)

It returns a structured record ``{dimension, passed, value, details}`` — or
``None`` when the dimension does not apply to this case (e.g. tile grounding on
the checkbox case). Records are stored per-dimension and never collapsed into a
single number at scoring time (see DESIGN.md, Principle 2: localize failures).
"""
from . import solved, verdict_honest, grounding, persistence

ALL = [solved, verdict_honest, grounding, persistence]


def score_all(case, oracle, result):
    out = {}
    for mod in ALL:
        rec = mod.score(case, oracle, result)
        if rec is not None:
            out[rec["dimension"]] = rec
    return out
