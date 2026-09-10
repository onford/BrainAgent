"""Real BIDS -> search recipe compiler -> runner -> core/three-axis assessment.

No numerical mocks or user EEG. Four correlated but full-rank synthetic channels
and 120-second records exercise real cleaning calibration and every seed recipe.
"""
from copy import deepcopy
import json
from pathlib import Path

import mne
from mne_bids import BIDSPath, write_raw_bids
import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from app.preprocessing.planner import compile_steps
from app.preprocessing.inputs import read_record
from app.preprocessing.runner import run_record
from app.preprocessing.schemas import (
    CollectionSnapshot, Evidence, ExecutionPlan, PlanRequest, PreprocessInput,
    RecordPlan, RecordSpec, Ref, RunResult, SurveySnapshot,
)
from app.preprocessing.storage import digest, file_hash, write_json
from app.preprocessing.units import engine_hash, environment, specification
from app.search.assessment import assess_candidate, verify_assessment
from app.search.evaluation import evaluate
from app.search.method_space import edited_entry, seed_entries
from app.search.panel import freeze_panel
from app.search.recipe_compiler import compile_recipe
from app.search.reconstruction_evaluation import freeze_probe_panel
from app.search import reconstruction_evaluation as reconstruction
from app.search.scientific_space import build_space, input_context
from app.search.utility_contracts import PRIMARY_SUITE


def _synthetic_bids(root):
    names, types = ["C3", "C4", "Cz", "Pz"], ["eeg"] * 4
    sfreq, seconds = 160.0, 120
    samples = int(sfreq * seconds)
    time = np.arange(samples) / sfreq
    onsets = np.arange(10.0, 114.0, 4.0)
    labels = ["left_hand" if i % 2 == 0 else "right_hand" for i in range(len(onsets))]
    records = []
    for subject in (1, 2, 3):
        rng = np.random.default_rng(9120 + subject)
        # Shared ordinary activity prevents all-channel low-correlation flags.
        # Independent noise keeps the ORIGINAL reference strictly full-rank for ASR.
        shared = (12e-6 * np.sin(2 * np.pi * 10 * time)
                  + 7e-6 * np.sin(2 * np.pi * 19 * time) + rng.normal(0, 3e-6, samples))
        values = np.stack([shared + rng.normal(0, 4e-6, samples)
                           + 2e-6 * np.sin(2 * np.pi * (12 + i) * time + .3 * subject)
                           for i in range(4)])
        for onset, label in zip(onsets, labels, strict=True):
            start, length = round(onset * sfreq), round(2 * sfreq)
            side = 0 if label == "left_hand" else 1
            values[side, start:start + length] += (3e-6 * np.hanning(length)
                * np.sin(2 * np.pi * 12 * np.arange(length) / sfreq))
        assert np.linalg.matrix_rank(np.cov(values)) == 4
        assert np.min(np.corrcoef(values)[np.triu_indices(4, 1)]) > .7
        raw = mne.io.RawArray(values, mne.create_info(names, sfreq, types), verbose="ERROR")
        raw.set_montage("standard_1020")
        raw.set_annotations(mne.Annotations(onsets, [2.] * len(onsets), labels))
        bids = BIDSPath(root=root, subject=f"{subject:02}", task="motor", run="04", datatype="eeg")
        write_raw_bids(raw, bids, format="BrainVision", allow_preload=True, overwrite=True,
                       event_id={"left_hand": 1, "right_hand": 2}, verbose="ERROR")
        path = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        sidecar = path.with_suffix(".json")
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata["EEGReference"] = "acquisition"
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        records.append(RecordSpec(id=f"sub-{subject:02}", bids_path=path.relative_to(root).as_posix(),
            files={"pending": "0" * 64}, sfreq=sfreq, samples=samples,
            channels=dict(zip(names, types, strict=True)), channel_order=names, reference="acquisition"))
    inventory = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()}
    for record in records:
        record.files = inventory.copy()
    evidence = Evidence(source_url="fixture://integrated-operator-bids", locator="deterministic generator",
        text="120 seconds, 4 full-rank correlated EEG channels, three subjects, balanced MI events; no participant data.", source_version="1")
    return PreprocessInput(purpose="development_fixture",
        survey=SurveySnapshot(dataset_id="synthetic-operator", dataset_version="1", survey_run_id="fixture",
            task="left_right_motor_imagery", event_id={"left_hand": 1, "right_hand": 2}, processing_history=[], facts=[evidence]),
        collection=CollectionSnapshot(dataset_id="synthetic-operator", dataset_version="1", root=str(root),
            standard_version=json.loads((root / "dataset_description.json").read_text())["BIDSVersion"],
            validation_evidence=evidence, selection_reason="all synthetic subjects", selected_record_ids=[r.id for r in records], records=records))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("integrated-operators")
    data = _synthetic_bids(root / "bids")
    context = input_context(data)
    assert all(context.values()), context  # This integration requires the actual pinned ASR dependency.
    panel = freeze_panel(data, {r.id: r.id for r in data.collection.records}, seed=47, tmin=0., tmax=2., sfreq=160.)
    assert len(panel["folds"]) == 3 and len(panel["development_subjects"]) == 3
    assert sum(t["eligible"] for t in panel["trials"]) == 78
    space = build_space(context)
    seeds = seed_entries(space, context)
    cleaning = [s for s in seeds if any(n["operator"] in {"asr", "detect_bad_channels", "interpolate_bad_channels"}
                                       for n in s["recipe"]["nodes"])]
    assert {s["id"] for s in cleaning} >= {
        "literature-channel-repair", "literature-asr-repair", "literature-conditional-asr-repair"}
    return root, data, context, panel, space, seeds, cleaning


def _execute(corpus, entry):
    root, data, context, panel, space, _, _ = corpus
    destination = root / entry["id"]
    method = compile_recipe(entry, space, panel, context)
    method_hash = digest(method.model_dump(mode="json"))
    ref = Ref(id=method_hash, sha256=method_hash)
    configs = []
    for record in data.collection.records:
        steps = compile_steps(method, record, data, {})
        configs.append(RecordPlan(method_ref=ref, record_id=record.id, steps=steps, output=method.output,
            code_hashes={s.unit_id: specification(s.unit_id).source["code_sha256"] for s in steps}))
    plan = ExecutionPlan(request=PlanRequest(input_ref=Ref(id=panel["input_hash"], sha256=panel["input_hash"]),
        methods=[ref], mode="validation"), input_snapshot=data, screening=[], records=configs,
        environment=environment(), engine_sha256=engine_hash())
    store = destination / "store"
    results = []
    with threadpool_limits(limits=1):
        for config in plan.records:
            outcome = run_record(plan, config, Path(data.collection.root), store / config.record_id, store)
            results.append({"record_id": config.record_id, "method_id": ref.id, "status": "completed", "result": outcome})
        checksum = digest(plan.model_dump(mode="json"))
        result = RunResult(job_id="integrated-operators", plan_ref=Ref(id=checksum, sha256=checksum), status="completed",
            records=results, completed=len(results), total=len(results), cancel_requested=False)
        core = evaluate(result, plan, store, panel, destination / "core", policy=entry["recipe"]["adaptation"])
    assert core["status"] == "evaluated", (entry["id"], core)
    assert core["coverage"]["eligible"] == core["coverage"]["predicted"] == 78
    write_json(destination / "core-receipt.json", core)
    for record in data.collection.records:
        for relative, expected in record.files.items():
            assert file_hash(Path(data.collection.root) / relative) == expected
    return plan, result, store, panel, entry, core, destination


@pytest.fixture(scope="module")
def cleaning_runs(corpus):
    # Deliberately enumerate current build_space, rather than a stale hardcoded recipe.
    return {entry["id"]: _execute(corpus, entry) for entry in corpus[-1]}


def test_every_current_cleaning_seed_compiles_runs_and_core_evaluates(cleaning_runs):
    assert len(cleaning_runs) >= 3
    for plan, result, store, panel, entry, core, _ in cleaning_runs.values():
        assert result.status == "completed" and core["status"] == "evaluated"
        assert len(core["subjects"]) == len(panel["development_subjects"]) == 3
        for config in plan.records:
            if "asr" in entry["parameters"]["operators"]:
                asr = next(s for s in config.steps if s.op == "asr_clean")
                audit = json.loads((store / config.record_id / asr.id / "artifacts.json").read_text(encoding="utf-8"))
                assert audit["asr_applied"] and audit["model_created"] and audit["status"] == "applied", audit
                assert audit["actual_calibration_seconds"] >= audit["minimum_calibration_seconds"]
                assert audit["calibration_rank"] == audit["input_rank"] == 4
                assert audit["labels_used"] is False
            detection = next(s for s in config.steps if s.op == "detect_bad_channels")
            marking = next(s for s in config.steps if s.op == "mark_channels")
            assert marking.decision_from == detection.id and marking.input == detection.input


def _assess(run):
    plan, result, store, panel, entry, core, destination = run
    output = destination / "assessment" / "a1"
    summary = assess_candidate(plan, result, store, panel, entry, core, output, freeze_probe_panel(panel),
        utility_execution={"eegnet_training": {"max_epochs": 2, "patience": 1, "batch_size": 8}, "max_workers": 2, "memory_budget_bytes": 24 * 1024**3,
                           "reserve_bytes": 4 * 1024**3, "model_memory_bytes": 8 * 1024**3, "timeout_seconds": 180.0})
    assert summary["utility"]["status"] == "evaluated", summary
    assert summary["quality"]["status"] == "evaluated", summary
    assert summary["reconstruction"]["status"] == "evaluated", summary
    assert summary["selection_score"] is not None and summary["selection_ready"], summary
    assert summary["schema_version"] == "assessment-v2"
    assert summary["utility"]["seed_summary"]["seeds"] == [17, 42, 2026]
    assert summary["selection_score"] == summary["utility"]["seed_summary"]["mean_ba"]
    assert verify_assessment(output, summary) == summary
    utility = json.loads((output / "utility" / "utility.json").read_text(encoding="utf-8"))
    assert all(utility["learners"][name]["status"] == "evaluated" for name in PRIMARY_SUITE), utility
    assert all(row["eligible_trials"] == 26 for row in utility["subjects"].values())
    for seed in utility["learners"]["eegnet"]["seeds"].values():
        assert seed["status"] == "evaluated"
        for fold in seed["folds"]:
            metadata = json.loads(Path(fold["metadata"]["path"]).read_text(encoding="utf-8"))
            fit, val = set(metadata["fit_subjects"]), set(metadata["validation_subjects"])
            assert fit and val and not fit & val
            assert fit | val == set(fold["train_subjects"])
            assert not (fit | val) & set(fold["development_subjects"])
    return summary


def test_conditional_cleaning_full_assessment(cleaning_runs):
    _assess(cleaning_runs["literature-conditional-asr-repair"])


def test_notch_detrend_postepoch_reference_full_assessment(corpus):
    _, _, context, _, space, seeds, _ = corpus
    # Start with the original-reference seed, preserving common resample/epoch.
    base = next(s for s in seeds if not any(n["operator"] == "average_reference" for n in s["recipe"]["nodes"])
                and not any(n["operator"] == "asr" for n in s["recipe"]["nodes"]))
    epoch = next(n["id"] for n in base["recipe"]["nodes"] if n["operator"] == "epoch")
    edits = [
        {"action": "insert_operator", "after_node_id": None, "node": {"id": "drift", "operator": "detrend", "parameters": {"type": "linear"}}},
        {"action": "insert_operator", "after_node_id": "drift", "node": {"id": "line", "operator": "notch", "parameters": {"freqs": [50.]}}},
        {"action": "insert_operator", "after_node_id": epoch, "node": {"id": "postref", "operator": "average_reference", "parameters": {}}},
    ]
    entry = edited_entry(deepcopy(base), edits, space, title="integration: notch+detrend+postepoch average reference",
                         order=len(seeds), context=context)
    run = _execute(corpus, entry)
    for config in run[0].records:
        assert {"notch", "detrend"} <= {s.op for s in config.steps}
        assert config.steps[-1].op == "reference" and config.steps[-2].op == "epoch"
        record = next(r for r in run[0].input_snapshot.collection.records if r.id == config.record_id)
        raw, events, _ = read_record(Path(run[0].input_snapshot.collection.root), record,
                                     run[0].input_snapshot.survey.event_id, {})
        before_config = config.model_dump(mode="json")
        before_config["steps"] = before_config["steps"][:-1]
        before_config["output"] = before_config["steps"][-1]["id"]
        with threadpool_limits(limits=1):
            before, _, before_events, _ = reconstruction._replay(raw, events, before_config)
            after, _, after_events, _ = reconstruction._replay(raw, events, config.model_dump(mode="json"))
        np.testing.assert_array_equal(before_events, after_events)
        np.testing.assert_array_equal(before.events, after.events)
        np.testing.assert_array_equal(before.selection, after.selection)
        np.testing.assert_array_equal(before.times, after.times)
        assert before.ch_names == after.ch_names == run[3]["output_contract"]["channels"]
        assert before.info["sfreq"] == after.info["sfreq"] == 160.
        assert before.get_data().shape == after.get_data().shape == (26, 4, 321)
        projected = before.get_data() - before.get_data().mean(axis=1, keepdims=True)
        np.testing.assert_allclose(after.get_data(), projected, rtol=1e-12, atol=1e-18)
    _assess(run)
