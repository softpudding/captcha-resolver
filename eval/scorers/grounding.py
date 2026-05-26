"""Tile-selection grounding: did the agent click the RIGHT tiles?

Diagnostic (not the pass gate). We look at the agent's FIRST verify/skip attempt
on the first round and compare the selected tiles against the answer key, using
the required/forbidden/optional tolerance from DESIGN.md:

  - true positives  = required tiles that were selected
  - false negatives = required tiles that were missed
  - false positives = forbidden tiles that were wrongly selected
  - optional tiles are ignored (don't-care)

Reports precision / recall over the {required ∪ forbidden} set, plus whether the
first attempt was exactly correct. Only applies to image-grid cases.
"""

_GRID_KINDS = {"grid", "dynamic", "retry", "multiround", "skip"}


def _first_grid_attempt(oracle):
    for a in (oracle or {}).get("attempts", []):
        if a.get("kind") in ("verify", "skip"):
            return a
    return None


def score(case, oracle, result):
    if case.get("kind") not in _GRID_KINDS:
        return None
    round0 = (case.get("rounds") or [{}])[0]
    required = set(round0.get("required", []))
    forbidden = set(round0.get("forbidden", []))

    attempt = _first_grid_attempt(oracle)
    selected = set(attempt.get("selected", [])) if attempt else set()

    tp = len(required & selected)
    fn = len(required - selected)
    fp = len(forbidden & selected)
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not required else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    exact = required <= selected and not (forbidden & selected)

    return {
        "dimension": "tile_grounding",
        "passed": exact,
        "value": round((precision + recall) / 2, 3),
        "details": {
            "selected": sorted(selected),
            "required": sorted(required),
            "forbidden": sorted(forbidden),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "false_positives": sorted(forbidden & selected),
            "missed_required": sorted(required - selected),
            "made_first_attempt": attempt is not None,
        },
    }
