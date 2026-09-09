"""Real BIDS + runner artifacts, event identity and subject-equal statistics."""

from copy import deepcopy
import json

import mne
from mne_bids import BIDSPath, write_raw_bids
import numpy as np
import pytest

from app.preprocessing.runner import run_record
from app.preprocessing.schemas import ExecutionPlan, PlanRequest, PreprocessInput, RecordPlan, Ref, RunResult, Step
from app.preprocessing.storage import digest, file_hash, write_json
from app.search.panel import freeze_panel
from app.search.quality_evaluation import METRIC_IDS, STAGES, evaluate_dataset_quality


CHANNELS = ["C3", "Cz", "C4"]


def make_case(tmp_path, counts=(2, 4, 2), *, post_reference=True, task_duration=2.0, first_cue=5.0):
    root, store = tmp_path / "bids", tmp_path / "store"
    specs = []
    subjects = {}
    for index, count in enumerate(counts):
        subject = "01" if index < len(counts)-1 else "02"
        rid = f"record-{index}"
        fs = 160.0
        samples = int((8*count+8)*fs)
        times = np.arange(samples) / fs
        onsets = np.arange(count)*8 + first_cue
        envelope = np.ones(samples)
        for onset in onsets:
            envelope[(times >= onset) & (times <= onset+2)] = 0.5
        amp = (8, 16, 100)[index] * 1e-6
        base = amp*envelope*np.sin(2*np.pi*10*times)
        data = np.array([base, 0.3*base, -0.7*base])
        data += np.random.default_rng(index).normal(0, 1e-7, data.shape)
        raw = mne.io.RawArray(data, mne.create_info(CHANNELS, fs, "eeg"), verbose="ERROR")
        raw.set_montage("standard_1020")
        raw.set_annotations(mne.Annotations(onsets, np.full(count, task_duration), ["left", "right"]*(count//2)))
        bids = BIDSPath(root=root, subject=subject, run=str(index+1), task="mi", datatype="eeg")
        write_raw_bids(raw, bids, format="BrainVision", allow_preload=True,
                       event_id={"left": 1, "right": 2}, overwrite=True, verbose="ERROR")
        path = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        meta = json.loads(path.with_suffix(".json").read_text())
        meta.update(EEGReference="acquisition", SoftwareFilters={}, HardwareFilters={}, PowerLineFrequency=50)
        write_json(path.with_suffix(".json"), meta)
        specs.append(dict(id=rid, bids_path=path.relative_to(root).as_posix(), files={"pending": "0"*64},
                          sfreq=fs, samples=samples, channels=dict.fromkeys(CHANNELS, "eeg"),
                          channel_order=CHANNELS, reference="acquisition"))
        subjects[rid] = "subject-"+subject
    inventory = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob("*") if p.is_file()}
    for spec in specs:
        spec["files"] = inventory.copy()
    evidence = dict(source_url="fixture:quality", locator="generator", text="Synthetic signal, no clinical truth", source_version="1")
    data = PreprocessInput.model_validate(dict(
        purpose="development_fixture",
        survey=dict(dataset_id="quality-fixture", dataset_version="1", survey_run_id="test", task="mi",
                    event_id={"left": 1, "right": 2}, processing_history=[], facts=[evidence]),
        collection=dict(dataset_id="quality-fixture", dataset_version="1", root=str(root),
                        standard_version=json.loads((root / "dataset_description.json").read_text())["BIDSVersion"],
                        validation_evidence=evidence, selection_reason="all", selected_record_ids=list(subjects), records=specs)))
    panel = freeze_panel(data, subjects, seed=42, tmin=0.0, tmax=2.0, sfreq=160)
    method = Ref(id="a"*64, sha256="a"*64)
    steps = [
        Step(id="resample", unit_id="EEG-RESAMPLE", op="resample", params={"sfreq": 160.0}, evidence_indices=[0]),
        Step(id="filter", unit_id="EEG-FILTER", op="filter", input="resample",
             params={"l_freq": 0.5, "h_freq": 60.0, "method": "iir", "phase": "zero", "picks": CHANNELS}, evidence_indices=[0]),
        Step(id="epoch", unit_id="EEG-EPOCH", op="epoch", input="filter",
             params={"tmin": 0.0, "tmax": 2.0, "picks": CHANNELS, "event_id": {"left": 1, "right": 2}}, evidence_indices=[0]),
    ]
    nodes = [dict(id="r", operator="resample", parameters={}),
             dict(id="f", operator="bandpass", parameters={"l_freq": 0.5, "h_freq": 60.0}),
             dict(id="e", operator="epoch", parameters={})]
    if post_reference:
        steps.append(Step(id="reference", unit_id="EEG-REREFERENCE", op="reference", input="epoch",
                          params={"ref_channels": "average"}, evidence_indices=[0]))
        nodes.append(dict(id="a", operator="average_reference", parameters={}))
    entry = dict(id="fixture", recipe=dict(nodes=nodes, adaptation={"adaptation": "euclidean_alignment"}))
    plan = ExecutionPlan(request=PlanRequest(input_ref=Ref(id=panel["input_hash"], sha256=panel["input_hash"]),
                                           methods=[method], mode="validation"),
                         input_snapshot=data, screening=[], environment={}, engine_sha256="b"*64,
                         records=[RecordPlan(method_ref=method, record_id=r.id, steps=deepcopy(steps),
                                             output=steps[-1].id, code_hashes={}) for r in data.collection.records])
    results = []
    for config in plan.records:
        produced = run_record(plan, config, root, store / config.record_id, store)
        results.append(dict(record_id=config.record_id, method_id=method.id, status="completed", result=produced))
    h = digest(plan.model_dump(mode="json"))
    result = RunResult(job_id="test", plan_ref=Ref(id=h, sha256=h), status="completed", records=results,
                       completed=len(results), total=len(results), cancel_requested=False)
    return plan, result, store, panel, entry


def evaluate(case, output):
    return evaluate_dataset_quality(*case, output)


def detail(receipt, output, rid="record-0"):
    artifact = next(a for a in receipt["detail_artifacts"] if a["record_id"] == rid)
    path = output / artifact["path"]
    assert file_hash(path) == artifact["sha256"]
    return json.loads(path.read_text(encoding="utf-8"))


def metric(d, stage, mid):
    return next(m for m in d["stages"][stage]["metrics"] if m["metricID"] == mid)


def change_artifact(case, rid, name, mutate):
    _, result, store, _, _ = case
    item = next(i for i in result.records if i["record_id"] == rid)
    artifact = next(a for a in item["result"]["artifacts"] if a["name"] == name)
    path = store / artifact["path"]
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    write_json(path, value)
    artifact["sha256"] = file_hash(path)
    artifact["bytes"] = path.stat().st_size
    if name == "delta.json":
        item["result"]["delta"] = value


def test_real_bids_all_records_subject_equal_summary_and_read_only(tmp_path):
    case = make_case(tmp_path)
    snapshot = {p: file_hash(p) for p in (tmp_path / "bids").rglob("*") if p.is_file()}
    out = tmp_path / "evaluation"
    receipt = evaluate(case, out)
    s = receipt["summary"]
    assert s["status"] == "evaluated", s["bysubject"]
    assert s["coverage"]["subjects_expected"] == s["coverage"]["subjects_visited"] == 2
    assert s["coverage"]["records_expected"] == s["coverage"]["records_verified"] == 3
    assert s["coverage"]["eligible_trials"] == s["coverage"]["available_trials"] == 8
    assert set(s["metrics"]) == set(METRIC_IDS)
    assert s["composite_score"] is None
    a, b = (s["bysubject"][key]["metrics"]["oha"]["value"][0] for key in ("subject-01", "subject-02"))
    assert a != b
    assert s["metrics"]["oha"]["value"][0] == pytest.approx((a+b)/2)
    assert s["metrics"]["oha"]["value"][0] != pytest.approx((6*a+2*b)/8)
    for rid in ("record-0", "record-1", "record-2"):
        d = detail(receipt, out, rid)
        for stage in STAGES:
            assert {m["metricID"] for m in d["stages"][stage]["metrics"]} == set(METRIC_IDS)
        oha = metric(d, "processed_task", "oha")
        assert len(oha["details"]["window_curves"]) == d["coverage"]["eligible_trials"]
        assert len(oha["denominator"]["original_trial_ids"]) == d["coverage"]["eligible_trials"]
    assert json.loads((out / "data-quality.json").read_text(encoding="utf-8")) == s
    json.dumps(receipt, allow_nan=False)
    assert snapshot == {p: file_hash(p) for p in snapshot}


@pytest.mark.parametrize("post_reference", [True, False])
def test_erds_uses_same_processed_precue_and_replays_postepoch_reference(tmp_path, post_reference):
    case = make_case(tmp_path, counts=(2, 2), post_reference=post_reference)
    out = tmp_path / "quality"
    receipt = evaluate(case, out)
    d = detail(receipt, out)
    assert not d["errors"], d["errors"]
    assert d["baseline_provenance"]["same_task_reextraction_verified"]
    assert d["baseline_provenance"]["postepoch_reference_steps"] == (["reference"] if post_reference else [])
    erd = metric(d, "processed_task", "erds_mu")
    assert erd["status"] == "ok", erd
    assert np.median(erd["value"]) < -50
    assert erd["unit"] == "%"
    assert metric(d, "processed_task", "psd")["unit"] == "µV²/Hz"
    # Adaptation in candidate recipe must not change the physical artifact unit.
    assert d["stages"]["processed_task"]["unit"] == "V"


def test_missing_continuous_keeps_raw_precue_but_never_substitutes_it(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    item = case[1].records[0]
    item["result"]["artifacts"] = [a for a in item["result"]["artifacts"] if a["name"] != "continuous-raw.fif"]
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    d = detail(receipt, out)
    assert metric(d, "source_precue", "psd")["status"] == "ok"
    erd = metric(d, "processed_task", "erds_mu")
    assert erd["value"] is None and erd["status"] == "not_applicable"
    assert erd["reason"] == "same_processed_continuous_artifact_unavailable"
    assert metric(d, "processed_task", "oha")["status"] == "ok"
    assert receipt["summary"]["coverage"]["records_visited"] == 2


@pytest.mark.parametrize("damage, reason", [
    ("duplicate", "duplicate_original_trial_id"),
    ("drop", "eligible_trial_retention_mismatch"),
    ("onset", "original_event_identity_mismatch"),
    ("units", "genuine_physical_voltage_epochs_required"),
])
def test_bad_record_identity_or_units_stays_in_fixed_denominator(tmp_path, damage, reason):
    case = make_case(tmp_path, counts=(2, 2))
    if damage == "units":
        change_artifact(case, "record-0", "delta.json", lambda d: d["after"].update(unit="dimensionless"))
    else:
        def mutate(rows):
            if damage == "duplicate":
                rows[1]["event_id"] = rows[0]["event_id"]
            elif damage == "drop":
                rows[0].update(retained=False, epoch_index=None)
            else:
                rows[0]["original_sample"] += 1
        change_artifact(case, "record-0", "events.json", mutate)
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    d = detail(receipt, out)
    assert d["errors"]["processed"] == reason
    s = receipt["summary"]
    assert s["coverage"]["records_visited"] == 2
    assert s["coverage"]["missing_trials"] == 2
    assert s["metrics"]["oha"]["status"] == "partial"
    assert s["metrics"]["oha"]["denominator"]["expected_subjects"] == 2
    assert s["metrics"]["oha"]["denominator"]["available_subjects"] == 1


def test_changed_continuous_lineage_and_wrong_signal_cannot_create_erd(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    change_artifact(case, "record-0", "provenance.json",
                    lambda p: p["continuous_raw"].update(source_node_id="raw"))
    # Another record has a physically scaled NPY but a stale continuous view.
    item = case[1].records[1]
    a = next(a for a in item["result"]["artifacts"] if a["name"] == "signal_V.npy")
    path = case[2] / a["path"]
    values = np.load(path)
    np.save(path, 2*values)
    a["sha256"] = file_hash(path)
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    d0, d1 = detail(receipt, out), detail(receipt, out, "record-1")
    assert metric(d0, "processed_task", "erds_mu")["reason"] == "continuous_epoch_provenance_mismatch"
    assert metric(d1, "processed_task", "erds_mu")["reason"] == "signal_V_does_not_match_fiff_epoch_rows"


def test_recipe_history_gates_line_hf_and_drift_without_spectral_guess(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    # The actual recipe LP=60 covers 50Hz sidebands, not 60Hz sidebands.
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    d = detail(receipt, out)
    assert metric(d, "processed_task", "line_ratio_50hz")["status"] == "ok"
    line60 = metric(d, "processed_task", "line_ratio_60hz")
    assert line60["value"] is None
    assert line60["reason"] == "frozen_filter_history_does_not_cover_metric_band"
    assert metric(d, "processed_continuous", "drift_power_ratio")["value"] is None
    h = metric(d, "processed_task", "psd")["details"]["history"]
    assert h["nominal_band_hz"] == [0.5, 60.0]
    assert h["bandwidth_inferred_from_signal"] is False


def test_unknown_postepoch_operation_is_explicitly_unsupported(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    plan, result, _, _, entry = case
    entry["recipe"]["nodes"][-1].update(operator="detrend", parameters={"type": "constant"})
    for cfg in plan.records:
        cfg.steps[-1].unit_id = "EEG-DETREND"
        cfg.steps[-1].op = "detrend"
        cfg.steps[-1].params = {"type": "constant"}
        def mutate(p):
            p["steps"][-1].update(unit_id="EEG-DETREND", op="detrend", parameters={"type": "constant"})
            p["continuous_raw"]["post_epoch_steps"] = [cfg.steps[-1].model_dump(mode="json")]
        change_artifact(case, cfg.record_id, "provenance.json", mutate)
    h = digest(plan.model_dump(mode="json"))
    result.plan_ref = Ref(id=h, sha256=h)
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    assert metric(detail(receipt, out), "processed_task", "erds_mu")["reason"] == "unsupported_postepoch_operation"


def test_recipe_or_output_root_cannot_bypass_contract(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    with pytest.raises(ValueError, match="disjoint_from_source"):
        evaluate(case, tmp_path / "bids" / "quality")
    case[4]["recipe"]["nodes"][1]["parameters"]["h_freq"] = 30
    out = tmp_path / "q"
    receipt = evaluate(case, out)
    assert detail(receipt, out)["errors"]["processed"] == "candidate_recipe_frozen_parameters_mismatch"


def test_signal_and_bids_inputs_are_never_opened_for_write(tmp_path, monkeypatch):
    case = make_case(tmp_path, counts=(2, 2))
    import app.search.quality_evaluation as qe
    original = qe.read_record
    visited = []
    def read(*args, **kwargs):
        raw, events, mapping = original(*args, **kwargs)
        visited.append(args[1].id)
        raw._data.flags.writeable = False
        return raw, events, mapping
    monkeypatch.setattr(qe, "read_record", read)
    receipt = evaluate(case, tmp_path / "q")
    assert visited == ["record-0", "record-1"]
    assert receipt["summary"]["coverage"]["records_verified"] == 2


@pytest.mark.parametrize("options, expected", [
    ({"task_duration": 8.0}, "precue_overlaps_original_task_event"),
    ({"first_cue": 1.0}, "precue_outside_record"),
    ({"task_duration": 0.0}, "precue_rest_unverified_zero_duration_prior_task"),
])
def test_precue_requires_true_rest_and_complete_record_support(tmp_path, options, expected):
    case = make_case(tmp_path, counts=(2, 2), **options)
    out = tmp_path / "q"
    d = detail(evaluate(case, out), out)
    audit = d["processed_precue_audit"]
    missing = next(i for i, row in enumerate(audit) if row["reason"] == expected)
    erd = metric(d, "processed_task", "erds_mu")
    assert erd["status"] == "partial"
    assert erd["value"][missing] == [None]*len(CHANNELS)
    assert erd["denominator"]["total_epochs"] == 2


def test_missing_whole_record_does_not_shrink_panel_or_stop_other_subjects(tmp_path):
    case = make_case(tmp_path)
    case[1].records = case[1].records[1:]
    case[1].status = "partial"
    out = tmp_path / "q"
    s = evaluate(case, out)["summary"]
    assert s["coverage"]["records_expected"] == s["coverage"]["records_visited"] == 3
    assert s["coverage"]["missing_trials"] == 2
    assert s["bysubject"]["subject-01"]["metrics"]["oha"]["denominator"]["expected_records"] == 2
    assert s["bysubject"]["subject-01"]["metrics"]["oha"]["denominator"]["available_records"] == 1
    assert s["metrics"]["oha"]["status"] == "partial"
    assert s["metrics"]["oha"]["denominator"]["expected_subjects"] == 2


def test_continuous_task_mismatch_is_distinct_from_valid_npys(tmp_path):
    case = make_case(tmp_path, counts=(2, 2))
    item = case[1].records[0]
    artifact = next(a for a in item["result"]["artifacts"] if a["name"] == "continuous-raw.fif")
    path = case[2] / artifact["path"]
    raw = mne.io.read_raw_fif(path, preload=True, verbose="ERROR")
    raw._data *= 2
    raw.save(path, fmt="double", overwrite=True, verbose="ERROR")
    raw.close()
    artifact.update(sha256=file_hash(path), bytes=path.stat().st_size)
    change_artifact(case, "record-0", "provenance.json",
                    lambda p: p["continuous_raw"].update(sha256=artifact["sha256"], bytes=artifact["bytes"]))
    out = tmp_path / "q"
    d = detail(evaluate(case, out), out)
    assert metric(d, "processed_task", "oha")["status"] == "ok"
    assert metric(d, "processed_task", "erds_mu")["reason"] == "continuous_reextracted_task_does_not_match_signal_V"
