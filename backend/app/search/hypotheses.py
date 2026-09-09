"""Check preregistered observable predictions without converting them to causes."""

import math


def metric(receipt, path):
    value = receipt
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"不存在的实测指标：{path}")
        value = value[key]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"指标必须是已测量的有限数值：{path}")
    return value


def validate_hypothesis(proposal, candidates):
    hypothesis = proposal["hypothesis"]
    measured = {c["id"]: c["receipt"] for c in candidates if c["status"] == "evaluated"}
    for reference in hypothesis["observations"]:
        if reference["candidate_id"] not in measured:
            raise ValueError("假设依据必须来自已完成的候选实验")
        metric(measured[reference["candidate_id"]], reference["metric"])
    parent = measured[proposal["base_candidate_id"]]
    for prediction in hypothesis["predictions"]:
        metric(parent, prediction["metric"])


def check_predictions(proposal, parent, receipt):
    checks = []
    for prediction in (proposal.get("hypothesis") or {}).get("predictions", []):
        row = {
            **prediction,
            "status": "unavailable",
            "before": None,
            "after": None,
            "difference": None,
        }
        if receipt.get("status") == "evaluated":
            try:
                before, after = (
                    metric(parent, prediction["metric"]),
                    metric(receipt, prediction["metric"]),
                )
                difference = after - before
                tolerance = prediction.get("tolerance", 1e-9)
                expected = prediction["direction"]
                matched = (
                    (expected == "increase" and difference > tolerance)
                    or (expected == "decrease" and difference < -tolerance)
                    or (expected == "unchanged" and abs(difference) <= tolerance)
                )
                row.update(
                    before=before,
                    after=after,
                    difference=difference,
                    status="matched" if matched else "contradicted",
                )
            except ValueError:
                pass
        checks.append(row)
    return {
        "checks": checks,
        "interpretation": "实测变化是否符合提前预测；不构成生理原因确认。",
    }
