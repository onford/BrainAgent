"""Candidate provenance and scheduling are projections, never scoring rules."""


def is_current_literature(entry):
    return any(t.get("kind") == "literature" and t.get("workflow_id") for t in entry.get("lineage", []))


def validate_stop(state, proposal):
    attempted = {c["id"] for c in state["candidates"]}
    pending = {e["id"] for e in state["registry"] if e["id"] not in attempted}
    reasons = proposal.get("untried_candidate_reasons", {})
    if set(reasons) != pending or any(not r.strip() for r in reasons.values()):
        raise ValueError("提前停止必须用 untried_candidate_reasons 逐一说明尚未执行候选为何不值得当前预算；不得用固定尝试次数代替理由。待说明：" + ", ".join(sorted(pending)))


def participation(state):
    outcomes = {c["id"]: c for c in state["candidates"]}
    current = [e for e in state.get("registry", []) if is_current_literature(e)]
    evaluated = [e["id"] for e in current if outcomes.get(e["id"], {}).get("status") == "evaluated"]
    distinct = [e["id"] for e in current if e["id"] in evaluated and e.get("origin") != "basic"
                and not any(t.get("kind") == "basic" for t in e.get("lineage", []))]
    operators = {o["id"]: o for o in state.get("protocol", {}).get("space", {}).get("operators", [])}
    substantive = [e["id"] for e in current if e["id"] in distinct and any(
        operators.get(n["operator"], {}).get("op") not in {None, "resample", "epoch"}
        and any(t.get("method_ref") for t in n.get("trace", [])) for n in e["recipe"]["nodes"])]
    statement = ("本轮文献预处理操作已进入真实评价；不等于独立有效性确认。" if substantive else
        "本轮有文献来源记录进入评价，但尚未验证区别于基础对照和公共输出适配的文献预处理操作。" if evaluated else
        "本轮文献方法未进入评价；不能宣称调研驱动闭环已经完成。")
    return {"status": "evaluated" if evaluated else "not_evaluated", "evaluated_candidate_ids": evaluated,
            "distinct_from_controls_evaluated_ids": distinct,
            "substantive_literature_evaluated_ids": substantive,
            "eligible_candidate_ids": [e["id"] for e in current],
            "statement": statement}


def method_status(state):
    outcomes = {c["id"]: c for c in state["candidates"]}
    terminal = state.get("status", "completed") in {"completed", "stopped", "failed", "cancelled"}
    stop_reasons = next(((a.get("request") or {}).get("untried_candidate_reasons", {})
                         for a in reversed(state.get("actions", []))
                         if a["action"] == "finish" and a["status"] == "completed"), {})
    rows = []
    for entry in state.get("registry", []):
        outcome = outcomes.get(entry["id"])
        rows.append({"candidate_id": entry["id"], "title": entry["title"], "origin": entry["origin"],
            "parent_ids": entry.get("parent_ids", []), "lineage": entry.get("lineage", []),
            "adaptations": entry["deviations"], "issues": entry.get("issues", []),
            "status": outcome["status"] if outcome else "deferred" if terminal else "pending",
            "reason": outcome.get("error") if outcome else stop_reasons.get(entry["id"], state.get("stop_reason")) if terminal else "等待候选调度",
            "recipe_hash": entry["recipe_hash"], "edits": entry["edits"],
            "artifacts": {"policy": f"candidates/{entry['id']}/policy.json",
                          "method": f"candidates/{entry['id']}/method.json",
                          "plan": f"candidates/{entry['id']}/plan.json",
                          "evaluation": f"candidates/{entry['id']}/receipt.json"} if outcome else {}})
    rows.extend({**row, "origin": "literature", "candidate_id": None}
                for row in state["protocol"].get("method_intake", {}).get("methods", [])
                if row["status"] == "blocked")
    return {"methods": rows, "literature_participation": participation(state),
            "absence_reasons": state["protocol"].get("method_intake", {}).get("absence_reasons", [])}
