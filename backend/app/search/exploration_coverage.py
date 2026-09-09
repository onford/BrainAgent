"""Track explored methods and edit mechanisms separately from their scores."""

from collections import Counter


EDIT_FAMILIES = (
    "set_parameter",
    "swap_adjacent",
    "insert_operator",
    "remove_operator",
    "set_adaptation",
)


def coverage(state):
    outcomes = {c["id"]: c for c in state["candidates"]}
    attempted = set(outcomes)
    measured = {k for k, c in outcomes.items() if c["status"] == "evaluated"}
    entries = state["registry"]
    seeds = state["protocol"]["catalog"]
    edits, measured_edits, operators = Counter(), Counter(), Counter()
    for entry in entries:
        if entry["id"] in attempted:
            edits.update({e["action"] for e in entry.get("edits", [])})
            operators.update({n["operator"] for n in entry["recipe"]["nodes"]})
        if entry["id"] in measured:
            measured_edits.update({e["action"] for e in entry.get("edits", [])})
    return {
        "schema_version": "1",
        "methods": [
            {
                "id": s["id"],
                "title": s["title"],
                "origin": s["origin"],
                "attempted": s["id"] in attempted,
                "evaluated": s["id"] in measured,
                "descendants": sum(
                    e["seed_id"] == s["id"]
                    and e["id"] != s["id"]
                    and e["id"] in attempted
                    for e in entries
                ),
            }
            for s in seeds
        ],
        "edit_families": {
            name: {"attempted": edits[name], "evaluated": measured_edits[name]}
            for name in EDIT_FAMILIES
        },
        "operators": dict(operators),
        "unexplored_methods": [s["id"] for s in seeds if s["id"] not in attempted],
        "unexplored_edit_families": [name for name in EDIT_FAMILIES if not edits[name]],
        "interpretation": "覆盖范围与实测效用分开；未尝试或执行失败不等于无效。参数域连续，不能宣称穷尽全部组合。",
    }
