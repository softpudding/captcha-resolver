"""Persistence: did the agent push through multi-step challenges?

Some cases require more than one verify to solve — fade-in reloads (dynamic),
"please try again" rejections (retry), and second grids (multiround). A weak
agent solves the first screen then stops, or gives up at the first rejection.

This dimension applies only to those kinds. It passes iff the page reached
`solved` (which, for these kinds, is only possible by completing every round),
and reports how many verify attempts and rounds the agent actually went through
so a near-miss ("gave up after round 1") is visible.
"""

_PERSIST_KINDS = {"dynamic", "retry", "multiround", "skip"}


def score(case, oracle, result):
    if case.get("kind") not in _PERSIST_KINDS:
        return None
    attempts = (oracle or {}).get("attempts", [])
    n_verify = sum(1 for a in attempts if a.get("kind") in ("verify", "skip"))
    rounds_reached = (oracle or {}).get("round", 0) + 1
    solved = (oracle or {}).get("state") == "solved"
    gave_up = getattr(result, "stopped_reason", "") in ("no_tool_call",) or (
        getattr(result, "success", False) is False and not solved
    )
    return {
        "dimension": "persistence",
        "passed": solved,
        "value": f"{rounds_reached}/{(oracle or {}).get('total_rounds', 1)} rounds",
        "details": {
            "verify_attempts": n_verify,
            "rounds_reached": rounds_reached,
            "solved": solved,
            "stopped_reason": getattr(result, "stopped_reason", ""),
            "likely_gave_up_early": bool(gave_up and not solved),
        },
    }
