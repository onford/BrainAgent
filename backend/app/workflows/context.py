"""Lossless grouping for repeated measurements sent to the reasoning model."""

import json
from collections import Counter


def _assessment_context(value):
    if isinstance(value, dict):
        return {k: _assessment_context(v) for k, v in value.items()
                if k not in {"artifacts", "artifact_manifest", "bindings", "receipt_artifact", "failure_artifact"}}
    if isinstance(value, list):
        return [_assessment_context(v) for v in value]
    return value


def evaluation_context(data):
    """Report interpretation needs measured summaries, not duplicated array indexes."""
    receipt = data.get("selected_receipt") or {}
    panel = data.get("panel") or {}
    protocol = data.get("evaluation_protocol") or {}
    representation = data.get("representation") or {}
    return {
        **{
            key: data[key]
            for key in (
                "selection_policy",
                "score",
                "evaluation_scope",
                "selected_candidate_id",
                "selected_method_ref",
                "reason",
                "candidate_summary",
                "literature_participation",
                "conclusion_eligibility",
            )
            if key in data
        },
        "protocol": {
            key: protocol[key]
            for key in (
                "version",
                "evaluator",
                "secondary_evaluator",
                "evaluation_mode",
                "metric",
                "information_permissions",
                "parameter_provenance",
                "confirmation",
                "assessment",
                "utility_protocol",
            )
            if key in protocol
        },
        "panel": {
            "train_subject_count": len(panel.get("train_subjects", [])),
            "development_subject_count": len(panel.get("development_subjects", [])),
            "record_count": len(panel.get("records", {})),
            "trial_count": panel.get("trial_count"),
            "eligible_count": panel.get("eligible_count"),
            "folds": [
                {
                    "id": f["id"],
                    "train_subject_count": len(f["train_subjects"]),
                    "development_subject_count": len(f["development_subjects"]),
                }
                for f in panel.get("folds", [])
            ],
        },
        "metrics": {
            key: receipt[key]
            for key in (
                "secondary_learner",
                "secondary_macro_ba",
                "mean_delta",
                "paired_subject_ci",
                "coverage",
            )
            if key in receipt
        },
        "core_anchor": {"learner": receipt.get("primary_learner"), "macro_ba": receipt.get("macro_ba"),
                        "role": "CSP/LDA anchor; selection uses assessment.selection_score"},
        "assessment": _assessment_context(receipt.get("assessment") or {}),
        "diagnostics": (receipt.get("diagnostics") or {}).get("summary"),
        "representation": {key: representation[key] for key in ("version", "unit", "channels") if key in representation},
    }


def grouped_records(records, identity="id", omit=()):
    groups = {}
    for record in records:
        observed = {k: v for k, v in record.items() if k not in {identity, *omit}}
        key = json.dumps(observed, sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(key, {"record_ids": [], "values": observed})
        group["record_ids"].append(record[identity])
    return list(groups.values())


def results_context(outputs):
    result = {}
    for stage, data in outputs.items():
        if stage == "data_evaluation":
            result[stage] = evaluation_context(data)
            continue
        result[stage] = {
            k: v for k, v in data.items() if k not in {"records", "channel_sets"}
        }
        if "records" in data:
            if stage == "data_survey":
                result[stage]["record_groups"] = grouped_records(
                    data["records"], omit=("source_path", "sha256", "subject")
                )
            elif stage == "data_preprocessing":
                result[stage]["record_groups"] = grouped_records(
                    data["records"], "record_id", ("artifact_root",)
                )
            else:
                result[stage]["records"] = data["records"]
    return result
