"""Read-only integrity and participation audit of a completed real search."""
import argparse
import json
from collections import Counter
from pathlib import Path

from app.preprocessing.schemas import MethodSpec
from app.preprocessing.storage import digest, file_hash, within
from app.search.catalog import entries_at, select
from app.search.io import read, write
from app.search.method_provenance import participation
from app.search.source_evidence import source_objects


def audit(root):
    state, protocol = read(root / "search.json"), read(root / "protocol.json")
    entries_at(root)
    assert state["status"] in {"completed", "stopped"}
    selected = select(state["candidates"], require_complete_assessment=True)
    assert selected == state["selected_candidate_id"] == read(root / "selection.json")["selected_candidate_id"]
    rows = []
    for candidate in state["candidates"]:
        directory = root / "candidates" / candidate["id"]
        receipt = candidate["receipt"]
        assert receipt == read(directory / "receipt.json")
        assessment = receipt.get("assessment") or {}
        count = 0
        assessment_directory = within(directory, receipt["assessment_path"])
        manifest_ref = assessment["artifact_manifest"]
        manifest_file = within(assessment_directory, manifest_ref["path"])
        assert file_hash(manifest_file) == manifest_ref["sha256"]
        for ref in read(manifest_file)["artifacts"]:
            path = within(manifest_file.parent, ref["path"])
            assert file_hash(path) == ref["sha256"] and path.stat().st_size == ref["bytes"], path
            count += 1
        method = MethodSpec.model_validate(read(directory / "method.json"))
        sources = source_objects(root, method)
        plan = read(directory / "plan.json")
        steps = [{"record_id": record["record_id"], "steps": [
            {k: step[k] for k in ("unit_id", "op", "params", "parameter_sources")} for step in record["steps"]]}
            for record in plan["records"]]
        rows.append({"id": candidate["id"], "title": candidate["title"], "status": candidate["status"],
            "score": assessment.get("selection_score"), "assessment_status": assessment.get("status"),
            "axes": {key: assessment[key]["status"] for key in ("utility", "quality", "reconstruction")},
            "coverage": assessment.get("coverage"), "seed_summary": assessment["utility"].get("seed_summary"),
            "quality_metric_statuses": dict(Counter(v["status"] for v in assessment["quality"]["summary"]["metrics"].values())),
            "verified_assessment_artifacts": count, "verified_source_objects": list(sources),
            "receipt_sha256": file_hash(directory / "receipt.json"), "plan_sha256": file_hash(directory / "plan.json"),
            "actual_record_steps": steps})
    parts = participation(state)
    subsequent = []
    for request in sorted((root / "decisions").glob("*/request.json")):
        value = read(request)
        context = json.loads(next(m["content"] for m in value["messages"] if m["role"] == "user"))
        for candidate in context.get("results", []):
            if candidate["id"] in parts["evaluated_candidate_ids"]:
                subsequent.append({"action_index": value["action_index"], "candidate_id": candidate["id"],
                    "score": candidate["receipt"]["assessment"]["selection_score"], "request": str(request.resolve()), "sha256": file_hash(request)})
    for fold in state["panel"].get("folds", []):
        assert not set(fold["train_subjects"]) & set(fold["development_subjects"])
    return {"search_id": state["id"], "root": str(root.resolve()), "status": state["status"],
        "stop_reason": state["stop_reason"], "business_version": protocol.get("business_version"),
        "protocol_sha256": file_hash(root / "protocol.json"), "selection_sha256": file_hash(root / "selection.json"),
        "selected_candidate_id": selected, "selection_recomputed": True, "usage": state["usage"],
        "panel_hash": state["panel"]["panel_hash"], "folds": state["panel"].get("folds", []),
        "candidates": rows, "literature_participation_review": parts, "subsequent_model_feedback": subsequent,
        "strict_minimum_met": bool(parts["substantive_literature_evaluated_ids"] and any(
            r["candidate_id"] in parts["substantive_literature_evaluated_ids"] for r in subsequent)),
        "full_release_accepted": False,
        "review_rule": "A source label or a shared resample/epoch-only control is insufficient evidence of executing a substantive source preprocessing method. Structural provenance is necessary; this audit is not scientific validity certification."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Audit output already exists; preserve previous evidence")
    result = audit(args.search)
    write(args.output, result)
    print("audit recorded; strict_minimum_met=", result["strict_minimum_met"])
