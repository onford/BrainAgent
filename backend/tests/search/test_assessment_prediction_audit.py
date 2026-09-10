"""Adversarial row edits with fresh hashes must not become trusted utility."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.preprocessing.storage import file_hash, write_json
from app.search import assessment as a
from app.search.utility_contracts import EEGNET_SEEDS, UtilityReceipt
from tests.search.test_assessment import case, utility, quality, reconstruction


def refresh_refs(value):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            path = Path(value["path"])
            value["sha256"] = file_hash(path)
        for item in value.values():
            refresh_refs(item)
    elif isinstance(value, list):
        for item in value:
            refresh_refs(item)


def corrupt(payload, mutation):
    learner = payload["learners"]["eegnet"]
    run = learner["seeds"][str(EEGNET_SEEDS[0])]
    path = Path(run["predictions"]["path"])
    rows = json.loads(path.read_text())
    if mutation == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif mutation in {"seed", "subject", "label", "fold_id"}:
        rows[0][mutation] = {"seed": EEGNET_SEEDS[1], "subject": "invented",
                             "label": "invented", "fold_id": "invented"}[mutation]
    elif mutation == "probability":
        rows[0]["proba_right"] = 1.5
    elif mutation == "argmax":
        rows[0]["prediction"] = "right_hand" if rows[0]["prediction"] == "left_hand" else "left_hand"
    elif mutation == "fold_file":
        target = Path(run["folds"][0]["predictions"]["path"])
        write_json(target, json.loads(Path(run["folds"][1]["predictions"]["path"]).read_text()))
    elif mutation == "combined":
        target = Path(learner["predictions"]["path"])
        combined = json.loads(target.read_text())
        combined[-1] = deepcopy(combined[0])
        write_json(target, combined)
    elif mutation == "metadata":
        target = Path(run["folds"][0]["metadata"]["path"])
        meta = json.loads(target.read_text())
        meta["seed"] = EEGNET_SEEDS[1]
        write_json(target, meta)
    elif mutation == "metrics":
        # Keep all three prediction layers mutually consistent and valid; the
        # unmodified receipt remains internally self-consistent but now lies.
        seed = EEGNET_SEEDS[0]
        targets = [path, Path(learner["predictions"]["path"])]
        targets += [Path(f["predictions"]["path"]) for f in run["folds"]]
        for target in targets:
            content = json.loads(target.read_text())
            for row in content:
                if row["seed"] == seed:
                    row["prediction"] = row["label"]
                    row["proba_right"] = 0.8 if row["label"] == "right_hand" else 0.2
                    row["proba_left"] = 1 - row["proba_right"]
                    row["decision_score"] = row["proba_right"]
            write_json(target, content)
        rows = json.loads(path.read_text())
    write_json(path, rows)
    refresh_refs(payload)


@pytest.mark.parametrize("mutation", [
    "duplicate", "seed", "subject", "label", "fold_id", "probability", "argmax",
    "fold_file", "combined", "metadata", "metrics",
])
def test_assessment_rejects_freshly_hashed_forged_prediction_files(tmp_path, monkeypatch, mutation):
    args, probe = case(tmp_path)

    def forged(*values):
        payload = utility(*values)
        corrupt(payload, mutation)
        # The receipt still validates: this is a file-content error, not a
        # deliberately invalid schema or stale-hash shortcut.
        UtilityReceipt.model_validate(payload)
        write_json(values[-1] / "utility.json", payload)
        return payload

    monkeypatch.setattr(a, "evaluate_dataset_utility", forged)
    monkeypatch.setattr(a, "evaluate_dataset_quality", quality)
    monkeypatch.setattr(a, "evaluate_dataset_reconstruction", reconstruction)
    summary = a.assess_candidate(*args, tmp_path / "assessment", probe)
    assert summary["utility"]["status"] == "failed"
    assert not summary["selection_ready"] and summary["selection_score"] is None
    assert "checksum" not in summary["utility"]["reason"]
    if mutation == "metrics":
        assert "metrics differ from predictions" in summary["utility"]["reason"]


def test_reuse_recomputes_predictions_even_after_all_artifacts_are_resealed(tmp_path, monkeypatch):
    args, probe = case(tmp_path)
    monkeypatch.setattr(a, "evaluate_dataset_utility", utility)
    monkeypatch.setattr(a, "evaluate_dataset_quality", quality)
    monkeypatch.setattr(a, "evaluate_dataset_reconstruction", reconstruction)
    out = tmp_path / "assessment"
    summary = a.assess_candidate(*args, out, probe)
    assert summary["selection_ready"]
    path = out / "utility/utility.json"
    payload = json.loads(path.read_text())
    corrupt(payload, "metrics")
    write_json(path, payload)
    summary["utility"]["receipt_artifact"] = a._ref(path, out).model_dump()
    content = {k: v for k, v in summary.items() if k not in {"artifacts", "artifact_manifest"}}
    write_json(out / "_assessment/summary.json", a.AssessmentSnapshot(content=content).model_dump())
    (out / "artifact-manifest.json").unlink()
    artifacts = a._inventory(out)
    write_json(out / "artifact-manifest.json", a.AssessmentManifest(bindings=summary["bindings"], artifacts=artifacts).model_dump())
    ref = a._ref(out / "artifact-manifest.json", out)
    artifacts.append(a.ArtifactEntry(**ref.model_dump(), component="assessment"))
    summary.update(artifact_manifest=ref.model_dump(), artifacts=[r.model_dump() for r in artifacts])
    write_json(out / "assessment.json", summary)
    with pytest.raises(ValueError, match="metrics differ from predictions"):
        a.verify_assessment(out, summary)
