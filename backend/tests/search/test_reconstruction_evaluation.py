from copy import deepcopy
import json
from pathlib import Path

import mne
import numpy as np
import pytest

from app.preprocessing import inputs, units
from app.preprocessing.runner import run_record
from app.preprocessing.schemas import (
    ExecutionPlan,
    PlanRequest,
    RecordPlan,
    Ref,
    RunResult,
    Step,
)
from app.preprocessing.storage import digest, file_hash, write_json
from app.search import reconstruction_evaluation as reval
from app.search.hypotheses import metric as resolve_metric
from app.search.panel import freeze_panel
from tests.preprocessing.conftest import make_dataset
from tests.search.test_panel import make_input


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("reconstruction-integration")
    data = make_dataset(root / "source", subjects=2)
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=912,
        tmin=-0.2,
        tmax=0.5,
        sfreq=160,
    )
    method = Ref(id="c" * 64, sha256="c" * 64)
    steps = [
        Step(
            id="filter",
            unit_id="EEG-FILTER",
            op="filter",
            params={
                "l_freq": 1.0,
                "h_freq": 60.0,
                "method": "iir",
                "phase": "zero",
                "picks": panel["output_contract"]["channels"],
            },
            evidence_indices=[0],
        ),
        Step(
            id="resample",
            input="filter",
            unit_id="EEG-RESAMPLE",
            op="resample",
            params={"sfreq": 160.0},
            evidence_indices=[0],
        ),
        Step(
            id="epoch",
            input="resample",
            unit_id="EEG-EPOCH",
            op="epoch",
            params={
                "event_id": data.survey.event_id,
                "tmin": -0.2,
                "tmax": 0.5,
                "picks": panel["output_contract"]["channels"],
            },
            evidence_indices=[0],
        ),
    ]
    plan = ExecutionPlan(
        request=PlanRequest(
            input_ref=Ref(id=panel["input_hash"], sha256=panel["input_hash"]),
            methods=[method],
            mode="validation",
        ),
        input_snapshot=data,
        screening=[],
        records=[
            RecordPlan(
                method_ref=method,
                record_id=r.id,
                steps=deepcopy(steps),
                output="epoch",
                code_hashes={},
            )
            for r in data.collection.records
        ],
        environment={},
        engine_sha256="b" * 64,
    )
    store = root / "store"
    records = []
    for config in plan.records:
        value = run_record(
            plan, config, root / "source", store / config.record_id, store
        )
        records.append(
            {
                "record_id": config.record_id,
                "method_id": method.id,
                "status": "completed",
                "result": value,
            }
        )
    checksum = digest(plan.model_dump(mode="json"))
    result = RunResult(
        job_id="reconstruction-fixture",
        plan_ref=Ref(id=checksum, sha256=checksum),
        status="completed",
        records=records,
        completed=2,
        total=2,
        cancel_requested=False,
    )
    return plan, result, store, panel


def run(completed, out, *, design="full_factorial", **changes):
    plan, result, store, panel = completed
    args = dict(
        plan=plan,
        result=result,
        store_root=store,
        panel=panel,
        candidate_entry={"id": "physical-filter", "score": -999},
        probe_panel=reval.freeze_probe_panel(panel, design=design),
        output_dir=out,
    )
    args.update(changes)
    value = reval.evaluate_dataset_reconstruction(**args)
    json.dumps(value, allow_nan=False)
    return value


def case_file(result, out, subject="sub-01", case="line-r05"):
    entry = next(
        c
        for c in result["details"]["subjects"][subject]["cases"]
        if c["case_id"] == case
    )
    path = out / entry["path"]
    assert file_hash(path) == entry["sha256"]
    return json.loads(path.read_text(encoding="utf-8"))


def rebind(plan, result):
    result = deepcopy(result)
    checksum = digest(plan)
    result["plan_ref"] = {"id": checksum, "sha256": checksum}
    return result


def test_real_bids_replay_all_cases_source_once_and_no_arrays_written(
    completed, tmp_path, monkeypatch
):
    plan, _, _, panel = completed
    original = {
        p: file_hash(p)
        for p in Path(plan.input_snapshot.collection.root).rglob("*")
        if p.is_file()
    }
    read = inputs.read_record
    reads, source_objects, calls = [], [], []
    invoke = units.invoke

    def observed_read(*args, **kwargs):
        output = read(*args, **kwargs)
        reads.append(args[1].id)
        source_objects.append((output[0], output[0].get_data().copy()))
        return output

    def observed_invoke(unit, op, x, model=None, **params):
        assert model is None
        calls.append(op)
        return invoke(unit, op, x, model=model, **params)

    monkeypatch.setattr(inputs, "read_record", observed_read)
    monkeypatch.setattr(units, "invoke", observed_invoke)
    out = tmp_path / "evaluation"
    result = run(completed, out)
    assert result["summary"]["status"] == "evaluated", result["summary"][
        "status_counts"
    ]
    assert result["summary"]["status_counts"] == {"evaluated": 20}
    assert reads == ["sub-01", "sub-02"]
    assert calls.count("filter") == calls.count("epoch") == 22
    assert result["summary"]["resources"]["clean_replays"] == 2
    assert result["summary"]["resources"]["corrupted_replays"] == 20
    assert result["summary"]["scope"] == reval.SCOPE
    assert result["summary"]["trial_cases_expected"] == 10 * sum(
        t["eligible"] for t in panel["trials"]
    )
    assert all(p.suffix == ".json" for p in out.rglob("*") if p.is_file())
    for path, checksum in original.items():
        assert file_hash(path) == checksum
    for raw, original_values in source_objects:
        np.testing.assert_array_equal(raw.get_data(), original_values)
    detail = case_file(result, out)
    assert (
        detail["verification"]["max_abs_error_V"]
        <= detail["verification"]["tolerance"]["atol_V"]
    )
    assert detail["negative_controls_verified"] is True
    assert (
        detail["negative_controls"]["zero"]["summary"]["clean_retention_nrmse"]["value"]
        == 1
    )
    assert detail["negative_controls"]["scaling"]["summary"]["clean_retention_gain"][
        "value"
    ] == pytest.approx(0.5)
    assert set(detail["array_hashes"]) == set(reval.ARRAY_NAMES)
    assert len(detail["receipt"]["windows"]) == 7
    # Exercise the actual LLM hypothesis path resolver on every exported condition.
    envelope = {"assessment": {"reconstruction": result}}
    for condition_id, row in result["summary"]["by_case"].items():
        path = f"assessment.reconstruction.summary.by_case.{condition_id}.metrics.input_nrmse.value"
        assert resolve_metric(envelope, path) == row["metrics"]["input_nrmse"]["value"]
    with pytest.raises(ValueError):
        resolve_metric(
            envelope,
            "assessment.reconstruction.summary.by_case.eog-0.5.metrics.input_nrmse.value",
        )
    print("integration_resources", result["summary"]["resources"])


def test_freeze_109_subjects_327_records_never_uses_candidate_score(tmp_path):
    data = make_input(tmp_path / "tsv", counts=(2,) * 109)
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=73,
        tmin=-0.1,
        tmax=0.1,
        sfreq=160,
    )
    for rid, record in list(panel["records"].items()):
        originals = [t for t in panel["trials"] if t["record_id"] == rid]
        for suffix in ("-run-02", "-run-03"):
            identity = rid + suffix
            panel["records"][identity] = {**record, "record_id": identity}
            panel["trials"].extend(
                {
                    **t,
                    "record_id": identity,
                    "event_id": t["event_id"].replace(rid + ":", identity + ":"),
                }
                for t in originals
            )
    panel["panel_hash"] = digest({k: v for k, v in panel.items() if k != "panel_hash"})
    before = deepcopy(panel)
    probe = reval.freeze_probe_panel(panel)
    assert panel == before
    assert probe["primary_evaluation_record_count"] == 327
    assert len(probe["subjects"]) == 109
    assert all(s["record_id"] == subject for subject, s in probe["subjects"].items())
    assert all(
        len(s["cases"]) == 1 and len(s["trial_ids"]) == 2
        for s in probe["subjects"].values()
    )
    reversed_panel = deepcopy(panel)
    reversed_panel["records"] = dict(reversed(list(panel["records"].items())))
    assert reval.freeze_probe_panel(reversed_panel) == probe
    assert probe["design"] == "balanced"
    assert probe["primary_evaluation_subject_count"] == 109
    counts = [c["subjects_expected"] for c in probe["conditions"].values()]
    assert sorted(counts) == [10] + [11] * 9
    members = [s for c in probe["conditions"].values() for s in c["subjects"]]
    assert len(members) == len(set(members)) == 109
    for subject, selection in probe["subjects"].items():
        assert subject in probe["conditions"][selection["cases"][0]["id"]]["subjects"]
    full = reval.freeze_probe_panel(panel, design="full_factorial")
    assert full["probe_hash"] != probe["probe_hash"]
    assert all(c["subjects_expected"] == 109 for c in full["conditions"].values())
    assert all(len(s["cases"]) == 10 for s in full["subjects"].values())
    for subject, selection in probe["subjects"].items():
        assert selection["cases"][0] in full["subjects"][subject]["cases"]
    cases = full["subjects"]["sub-01"]["cases"]
    assert cases[0]["seed"] == cases[1]["seed"]  # same waveform, two strengths


def test_frozen_probe_changes_are_rejected_before_source_read(
    completed, tmp_path, monkeypatch
):
    probe = reval.freeze_probe_panel(completed[3])
    probe["subjects"]["sub-01"]["cases"][0]["rms_ratio"] = 0.25
    monkeypatch.setattr(
        inputs, "read_record", lambda *a, **k: pytest.fail("must not read")
    )
    with pytest.raises(reval.ProbeError, match="deterministic frozen policy"):
        run(completed, tmp_path / "out", probe_panel=probe)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("damage", ["signal", "events"])
def test_clean_replay_mismatch_keeps_failed_subject_denominator(
    completed, tmp_path, damage
):
    plan, result, _, _ = completed
    result = result.model_dump(mode="json")
    original_entry = next(
        a
        for a in result["records"][0]["result"]["artifacts"]
        if a["name"] == ("signal_V.npy" if damage == "signal" else "events.json")
    )
    path = completed[2] / original_entry["path"]
    alternate = completed[2] / ("damaged-" + damage + "-" + tmp_path.name + path.suffix)
    # Test fixture artifacts only; restore through a per-test new inventory entry.
    if damage == "signal":
        np.save(alternate, np.load(path, allow_pickle=False) * 0.5, allow_pickle=False)
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
        retained = [r for r in rows if r["retained"]]
        retained[0]["epoch_index"], retained[1]["epoch_index"] = (
            retained[1]["epoch_index"],
            retained[0]["epoch_index"],
        )
        write_json(alternate, rows)
    original_entry.update(
        path=alternate.relative_to(completed[2]).as_posix(), sha256=file_hash(alternate)
    )
    out = tmp_path / "out"
    value = run(completed, out, result=result)
    assert value["summary"]["status_counts"] == {"failed": 10, "evaluated": 10}
    assert value["summary"]["resources"]["corrupted_replays"] == 10
    detail = case_file(value, out)
    assert detail["reason_code"] == "CLEAN_REPLAY_MISMATCH"
    metric = value["summary"]["by_case"]["line-r05"]["metrics"]["clean_retention_nrmse"]
    assert metric == {"value": None, "status": "incomplete", "n_valid": 1, "n_total": 2}


@pytest.mark.parametrize("damage", ["model", "decision", "branch", "unsupported"])
def test_unsupported_dag_is_not_identity_cleaning(completed, tmp_path, damage):
    plan = completed[0].model_dump(mode="json")
    step = plan["records"][0]["steps"][0]
    if damage == "model":
        step["model_from"] = "fit"
    elif damage == "decision":
        step["decision_from"] = "detector"
    elif damage == "branch":
        step["input"] = "another_node"
    else:
        step["op"] = "not_implemented"
    result = rebind(plan, completed[1].model_dump(mode="json"))
    value = run(completed, tmp_path / "out", plan=plan, result=result)
    assert value["summary"]["status_counts"] == {"not_applicable": 10, "evaluated": 10}
    assert value["summary"]["resources"]["source_records_read"] == 1
    assert case_file(value, tmp_path / "out")["reason_code"] == "UNSUPPORTED_RECIPE"


def test_failed_existing_record_does_not_fall_back_or_drop_subject(completed, tmp_path):
    result = completed[1].model_dump(mode="json")
    result["records"][0].update(status="failed", result=None)
    value = run(completed, tmp_path / "out", result=result)
    assert value["summary"]["status_counts"] == {"failed": 10, "evaluated": 10}
    assert (
        case_file(value, tmp_path / "out")["reason_code"] == "CANDIDATE_RECORD_FAILED"
    )


def test_no_applicable_noise_retains_cases_and_null_reasons(
    completed, tmp_path, monkeypatch
):
    def no_noise(raw, case, subject, rid, probe):
        return raw.copy(), {
            "seed": case["seed"],
            "kind": case["kind"],
            "rms_ratio": case["rms_ratio"],
        }

    monkeypatch.setattr(reval, "_noise", no_noise)
    value = run(completed, tmp_path / "out")
    assert value["summary"]["status_counts"] == {"not_applicable": 20}
    assert value["summary"]["resources"]["corrupted_replays"] == 0
    row = case_file(value, tmp_path / "out")
    assert row["reason_code"] == "NO_APPLICABLE_CONTAMINATION"
    assert len(row["inapplicable_trials"]) == row["expected_trials"]
    assert (
        value["summary"]["by_case"]["line-r05"]["metrics"]["input_nrmse"]["n_total"]
        == 2
    )


def test_noise_is_frozen_shared_by_amplitudes_and_leaves_auxiliary_untouched(completed):
    plan, _, _, panel = completed
    raw, _, _ = inputs.read_record(
        Path(plan.input_snapshot.collection.root),
        plan.input_snapshot.collection.records[0],
        plan.input_snapshot.survey.event_id,
    )
    probe = reval.freeze_probe_panel(panel, design="full_factorial")
    original = raw.get_data()
    cases = probe["subjects"]["sub-01"]["cases"]
    for a, b in zip(cases[::2], cases[1::2], strict=True):
        low, manifest = reval._noise(raw, a, "sub-01", "sub-01", probe)
        repeat, repeated = reval._noise(raw, a, "sub-01", "sub-01", probe)
        high, _ = reval._noise(raw, b, "sub-01", "sub-01", probe)
        assert manifest == repeated
        np.testing.assert_array_equal(low.get_data(), repeat.get_data())
        np.testing.assert_array_equal(
            low.get_data(picks=["VEOG"]), raw.get_data(picks=["VEOG"])
        )
        np.testing.assert_allclose(
            high.get_data() - original, 2 * (low.get_data() - original), atol=1e-19
        )
        eeg = raw.get_data(picks="eeg")
        assert np.linalg.norm(low.get_data(picks="eeg") - eeg) / np.linalg.norm(
            eeg
        ) == pytest.approx(0.5)
    np.testing.assert_array_equal(raw.get_data(), original)


@pytest.mark.parametrize("kind", ["eog", "emg"])
@pytest.mark.parametrize("tail", [0, 1, 160])
@pytest.mark.parametrize("count_type", [np.int32, np.int64])
def test_block_noise_numpy_sample_count_has_json_manifest(
    tmp_path, monkeypatch, kind, tail, count_type
):
    # BrainVision on Windows supplies np.int32 n_times. A partial final block
    # used to retain that scalar in stop, making an otherwise scored case fail.
    original_count = mne.io.BaseRaw.n_times.fget
    monkeypatch.setattr(
        mne.io.BaseRaw, "n_times", property(lambda raw: int(original_count(raw)))
    )
    data = np.random.default_rng(19).normal(0, 1e-5, (3, 640 + tail))
    raw = mne.io.RawArray(
        data.copy(),
        mne.create_info(["C3", "C4", "EOG"], 160, ["eeg", "eeg", "eog"]),
        verbose="ERROR",
    )
    case = {"kind": kind, "seed": 123, "rms_ratio": 0.5}
    probe = {
        "injection": {
            "eog_emg_block_seconds": 2.0,
            "line_frequency": 50.0,
            "strength_scope": "whole_source_EEG_record_RMS_ratio",
        }
    }
    expected, native_manifest = reval._noise(raw, case, "S003", "S003R04", probe)
    monkeypatch.setattr(
        mne.io.BaseRaw, "n_times", property(lambda raw: count_type(original_count(raw)))
    )
    actual, manifest = reval._noise(raw, case, "S003", "S003R04", probe)
    path = tmp_path / "injection.json"
    write_json(path, manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == native_manifest
    assert manifest["blocks"][-1]["stop"] == data.shape[-1]
    assert all(
        type(block[k]) is int for block in manifest["blocks"] for k in ("start", "stop")
    )
    if tail == 1:
        assert manifest["blocks"][-1]["start"] == data.shape[-1] - 2
    np.testing.assert_array_equal(actual.get_data(), expected.get_data())
    np.testing.assert_array_equal(raw.get_data(), data)
    np.testing.assert_array_equal(actual.get_data(picks=["EOG"]), data[2:])
    assert np.linalg.norm(actual.get_data()[:2] - data[:2]) / np.linalg.norm(
        data[:2]
    ) == pytest.approx(0.5)


def test_resample_uses_returned_events_instead_of_guessing_grid(completed, monkeypatch):
    plan = completed[0]
    raw, events, _ = inputs.read_record(
        Path(plan.input_snapshot.collection.root),
        plan.input_snapshot.collection.records[0],
        plan.input_snapshot.survey.event_id,
    )
    invoke = units.invoke

    def shifted(unit, op, x, model=None, **params):
        result = invoke(unit, op, x, model=model, **params)
        if op == "resample":
            result["artifacts"]["events"][:, 0] += 1
        if op == "epoch":
            assert params["events"][1, 0] == round(events[1, 0] * 160 / 200) + 1
        return result

    monkeypatch.setattr(units, "invoke", shifted)
    epochs, _, synchronized, _ = reval._replay(
        raw, events, plan.records[0].model_dump(mode="json")
    )
    np.testing.assert_array_equal(epochs.events, synchronized[epochs.selection])


@pytest.fixture
def diagnostic_chain():
    sfreq = 160.0
    rng = np.random.default_rng(23)
    values = rng.normal(0, 10e-6, (6, 3200))
    values[0] = 0
    names = ["C3", "C4", "Cz", "Pz", "F3", "F4"]
    raw = mne.io.RawArray(values, mne.create_info(names, sfreq, "eeg"), verbose="ERROR")
    raw.set_montage("standard_1020")
    steps = [
        dict(
            id="detect",
            input="raw",
            unit_id="EEG-AUTO-BAD-CHANNEL",
            op="detect_bad_channels",
            params={
                "adaptation_scope": "record_unlabeled",
                "correlation_threshold": 0.0,
                "deviation_z": 10.0,
            },
        ),
        dict(
            id="mark",
            input="raw",
            decision_from="detect",
            unit_id="EEG-BAD-CHANNEL-MARK",
            op="mark_channels",
            params={"max_fraction": 0.25},
        ),
        dict(
            id="repair",
            input="mark",
            unit_id="EEG-AUTO-BAD-CHANNEL",
            op="interpolate_bad_channels",
            params={"max_fraction": 0.25},
        ),
        dict(
            id="epoch",
            input="repair",
            unit_id="EEG-EPOCH",
            op="epoch",
            params={"picks": names, "tmin": 0.0, "tmax": 1.0, "event_id": {"left": 1}},
        ),
    ]
    return raw, np.array([[320, 0, 1]]), {"steps": steps, "output": "epoch"}


def test_real_detect_marks_info_before_real_interpolation(diagnostic_chain):
    raw, events, config = diagnostic_chain
    values = raw.get_data()
    reval._supported(
        config, {"channels": raw.ch_names, "tmin": 0.0, "tmax": 1.0}, {"left": 1}
    )
    epochs, physical, _, trace = reval._replay(raw, events, config)
    assert trace[0]["bads"] == []
    assert trace[1]["bads"] == ["C3"]
    assert trace[1]["parameters"]["bads"] == ["C3"]
    assert trace[1]["decision_binding"] == trace[0]["decision_binding"]
    assert trace[1]["decision_binding"]["input_node"] == "raw"
    assert physical.info["bads"] == []
    assert np.linalg.norm(epochs.get_data()[:, 0]) > 0
    np.testing.assert_array_equal(raw.get_data(), values)


def test_real_asr_replay_refits_each_independent_raw(monkeypatch):
    import asrpy.asr as asr_source

    sfreq = 160.0
    rng = np.random.default_rng(33)
    data = rng.normal(0, 10e-6, (4, 8000))
    names = ["C3", "C4", "Cz", "Pz"]
    raw = mne.io.RawArray(data, mne.create_info(names, sfreq, "eeg"), verbose="ERROR")
    instances = []
    constructor = asr_source.ASR

    def observed_constructor(*args, **kwargs):
        estimator = constructor(*args, **kwargs)
        instances.append(estimator)
        return estimator

    monkeypatch.setattr(asr_source, "ASR", observed_constructor)
    config = {
        "steps": [
            dict(
                id="filter",
                input="raw",
                unit_id="EEG-FILTER",
                op="filter",
                params={
                    "l_freq": 1.0,
                    "h_freq": 70.0,
                    "method": "iir",
                    "phase": "zero",
                    "picks": names,
                },
            ),
            dict(
                id="detect",
                input="filter",
                unit_id="EEG-AUTO-BAD-CHANNEL",
                op="detect_bad_channels",
                params={
                    "adaptation_scope": "record_unlabeled",
                    "correlation_threshold": 0.0,
                    "deviation_z": 10.0,
                },
            ),
            dict(
                id="mark",
                input="filter",
                decision_from="detect",
                unit_id="EEG-BAD-CHANNEL-MARK",
                op="mark_channels",
                params={"max_fraction": 0.25},
            ),
            dict(
                id="asr",
                input="mark",
                unit_id="EEG-ASR-AUTO",
                op="asr_clean",
                params={
                    "adaptation_scope": "record_unlabeled",
                    "min_clean_seconds": 30.0,
                },
            ),
            dict(
                id="epoch",
                input="asr",
                unit_id="EEG-EPOCH",
                op="epoch",
                params={
                    "tmin": 0.0,
                    "tmax": 1.0,
                    "picks": names,
                    "event_id": {"left": 1},
                },
            ),
        ]
    }
    events = np.array([[320, 0, 1]])
    _, _, _, clean_trace = reval._replay(raw, events, config)
    changed = raw.copy()
    changed._data *= 2
    _, _, _, noisy_trace = reval._replay(changed, events, config)
    assert len(instances) == 2 and instances[0] is not instances[1]
    assert (
        clean_trace[3]["fit_artifact_hashes"]["mixing_matrix"]
        != noisy_trace[3]["fit_artifact_hashes"]["mixing_matrix"]
    )
    np.testing.assert_array_equal(raw.get_data(), data)


def test_output_cannot_overwrite_source_existing_results_or_previous_evaluation(
    completed, tmp_path
):
    with pytest.raises(reval.ProbeError, match="overlap"):
        run(
            completed,
            Path(completed[0].input_snapshot.collection.root) / "probe",
        )
    with pytest.raises(reval.ProbeError, match="overlap"):
        run(completed, completed[2] / "sub-01" / "probe")
    out = tmp_path / "existing"
    out.mkdir()
    with pytest.raises(reval.ProbeError, match="fresh output"):
        run(completed, out)


def test_aggregation_never_reweights_around_failed_subject():
    rows = [
        {name: {"value": float(i == 0)} for name in reval.METRICS} for i in range(109)
    ]
    assert reval._aggregate(rows)["reconstruction_nrmse"]["value"] == pytest.approx(
        1 / 109
    )
    rows[-1] = {}
    result = reval._aggregate(rows)["reconstruction_nrmse"]
    assert result == {
        "value": None,
        "status": "incomplete",
        "n_valid": 108,
        "n_total": 109,
    }


def test_one_corrupted_replay_failure_keeps_controls_and_other_cases(
    completed, tmp_path, monkeypatch
):
    replay = reval._replay
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise reval.ProbeError(
                "ASR_CALIBRATION_TOO_SHORT", "injected calibration failure"
            )
        return replay(*args)

    monkeypatch.setattr(reval, "_replay", fail_once)
    result = run(completed, tmp_path / "out")
    assert result["summary"]["status_counts"] == {"failed": 1, "evaluated": 19}
    detail = case_file(result, tmp_path / "out", case="eog-r05")
    assert detail["reason_code"] == "ASR_CALIBRATION_TOO_SHORT"
    assert detail["negative_controls_verified"] is True
    assert detail["metrics"]["reconstruction_nrmse"]["value"] is None
    assert "cleaned" not in detail["array_hashes"]
    assert (
        result["summary"]["by_case"]["eog-r05"]["metrics"]["reconstruction_nrmse"][
            "n_total"
        ]
        == 2
    )


def test_default_balanced_execution_reuses_assignment_across_candidate_scores(
    completed, tmp_path
):
    probe = reval.freeze_probe_panel(completed[3])
    original = deepcopy(probe)
    first = run(
        completed,
        tmp_path / "first",
        probe_panel=probe,
        candidate_entry={"id": "same-physical-recipe", "score": -999},
    )
    second = run(
        completed,
        tmp_path / "second",
        probe_panel=probe,
        candidate_entry={"id": "same-physical-recipe", "score": 999},
    )
    assert probe == original
    for result in (first, second):
        summary = result["summary"]
        assert summary["design"] == "balanced"
        assert summary["subjects_expected"] == summary["cases_expected"] == 2
        assert summary["trial_cases_expected"] == 14
        assert summary["status_counts"] == {"evaluated": 2}
        assert summary["resources"]["source_records_read"] == 2
        assert summary["resources"]["clean_replays"] == 2
        assert summary["resources"]["corrupted_replays"] == 2
        assert summary["primary_evaluation_record_count"] == 2
        assert summary["primary_evaluation_subject_count"] == 2
        assert any(
            "assigned subset, not all subjects" in s for s in summary["limitations"]
        )
        for case_id, condition in probe["conditions"].items():
            row = summary["by_case"][case_id]
            count = condition["subjects_expected"]
            assert row["subjects_expected"] == count
            assert row["subjects_assigned"] == condition["subjects"]
            assert row["trial_cases_expected"] == count * 7
            assert row["subjects_not_assigned"] == 2 - count
            metric = row["metrics"]["clean_retention_nrmse"]
            assert metric["n_total"] == count
            if count == 0:
                assert row["status"] == "not_assigned"
                assert metric == {
                    "value": None,
                    "status": "not_assigned",
                    "n_valid": 0,
                    "n_total": 0,
                }
    for subject, selection in probe["subjects"].items():
        case_id = selection["cases"][0]["id"]
        a = case_file(first, tmp_path / "first", subject=subject, case=case_id)
        b = case_file(second, tmp_path / "second", subject=subject, case=case_id)
        assert a["case"] == b["case"]
        assert a["injection"] == b["injection"]
        assert a["array_hashes"] == b["array_hashes"]
    print("balanced_resources", first["summary"]["resources"])


def test_balanced_failure_remains_in_its_assigned_condition_only(completed, tmp_path):
    probe = reval.freeze_probe_panel(completed[3])
    result = completed[1].model_dump(mode="json")
    result["records"][0].update(status="failed", result=None)
    output = run(completed, tmp_path / "out", probe_panel=probe, result=result)
    summary = output["summary"]
    assert summary["subjects_expected"] == summary["cases_expected"] == 2
    assert summary["status_counts"] == {"failed": 1, "evaluated": 1}
    assert summary["resources"]["corrupted_replays"] == 1
    case_id = probe["subjects"]["sub-01"]["cases"][0]["id"]
    condition = summary["by_case"][case_id]
    assert condition["subjects_assigned"] == ["sub-01"]
    assert condition["metrics"]["reconstruction_nrmse"] == {
        "value": None,
        "status": "incomplete",
        "n_valid": 0,
        "n_total": 1,
    }
    assert (
        case_file(output, tmp_path / "out", case=case_id)["reason_code"]
        == "CANDIDATE_RECORD_FAILED"
    )


@pytest.mark.parametrize("tamper", ["design", "assignment"])
def test_rehashed_design_or_assignment_changes_cannot_replace_frozen_policy(
    completed, tmp_path, tamper
):
    probe = reval.freeze_probe_panel(completed[3])
    if tamper == "design":
        probe["design"] = "full_factorial"
    else:
        subjects = list(probe["subjects"])
        left, right = (probe["subjects"][s] for s in subjects)
        left["cases"], right["cases"] = right["cases"], left["cases"]
        for condition in probe["conditions"].values():
            condition["subjects"] = [
                subjects[1 - subjects.index(s)] for s in condition["subjects"]
            ]
    probe["probe_hash"] = digest({k: v for k, v in probe.items() if k != "probe_hash"})
    with pytest.raises(reval.ProbeError, match="deterministic frozen policy"):
        run(completed, tmp_path / "out", probe_panel=probe)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("count", [3, 9, 10, 11, 20, 37])
def test_balanced_counts_are_guaranteed_on_small_and_nonmultiple_panels(
    tmp_path, count
):
    data = make_input(tmp_path / "tsv", counts=(2,) * count)
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=18,
        tmin=-0.1,
        tmax=0.1,
        sfreq=160,
    )
    probe = reval.freeze_probe_panel(panel)
    counts = [c["subjects_expected"] for c in probe["conditions"].values()]
    assert sum(counts) == count
    assert max(counts) - min(counts) <= 1
    assert all(len(s["cases"]) == 1 for s in probe["subjects"].values())


def test_unknown_design_is_not_silently_defaulted(completed):
    with pytest.raises(ValueError, match="balanced or full_factorial"):
        reval.freeze_probe_panel(completed[3], design="adaptive")


@pytest.mark.parametrize("design", ["balanced", "full_factorial"])
def test_probe_condition_ids_are_safe_metric_path_segments(completed, design):
    probe = reval.freeze_probe_panel(completed[3], design=design)
    assert probe["schema_version"] == "dataset-reconstruction-v3"
    expected = {
        f"{kind}-{suffix}": ratio
        for kind in reval.KINDS
        for suffix, ratio in (("r05", 0.5), ("r10", 1.0))
    }
    assert set(probe["conditions"]) == set(expected)
    assert probe["assignment"]["condition_order"] == list(expected)
    for identity, condition in probe["conditions"].items():
        assert "." not in identity and condition["id"] == identity
        assert condition["rms_ratio"] == expected[identity]
    for subject in probe["subjects"].values():
        for case in subject["cases"]:
            assert case["id"] in expected
            assert case["rms_ratio"] == expected[case["id"]]
    assert probe["probe_hash"] == digest(
        {k: v for k, v in probe.items() if k != "probe_hash"}
    )


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_input",
        "wrong_detector",
        "reuse",
        "missing_mark",
        "manual_bads",
        "duplicate_id",
    ],
)
def test_only_bound_diagnostic_branch_is_supported(diagnostic_chain, damage):
    raw, events, config = diagnostic_chain
    if damage == "wrong_input":
        config["steps"][1]["input"] = "detect"
    elif damage == "wrong_detector":
        config["steps"][1]["decision_from"] = "other"
    elif damage == "reuse":
        config["steps"].insert(
            2, {**deepcopy(config["steps"][1]), "id": "again", "input": "mark"}
        )
    elif damage == "missing_mark":
        config["steps"].pop(1)
        config["steps"][1]["input"] = "detect"
    elif damage == "manual_bads":
        config["steps"][1]["params"]["bads"] = []
    else:
        config["steps"][1]["id"] = "detect"
    with pytest.raises(reval.ProbeError) as error:
        reval._replay(raw, events, config)
    assert error.value.code == "UNSUPPORTED_RECIPE"
    assert error.value.status == "not_applicable"


@pytest.mark.parametrize(
    "damage,code",
    [
        ("input_samples", "DECISION_INPUT_MUTATED"),
        ("input_geometry", "DECISION_INPUT_MUTATED"),
        ("diagnostic_output", "DIAGNOSTIC_OUTPUT_CHANGED"),
        ("duplicates", "INVALID_BAD_CHANNELS"),
        ("unknown_channel", "INVALID_BAD_CHANNELS"),
        ("mark_samples", "MARK_OUTPUT_CHANGED"),
        ("mark_bads", "MARK_OUTPUT_CHANGED"),
    ],
)
def test_diagnostic_and_mark_runtime_bindings_are_verified(
    diagnostic_chain, monkeypatch, damage, code
):
    raw, events, config = diagnostic_chain
    original = raw.get_data()
    invoke = units.invoke

    def changed(unit, op, x, model=None, **params):
        result = invoke(unit, op, x, model=model, **params)
        if op == "detect_bad_channels":
            if damage == "input_samples":
                x._data[1, 0] += 1e-6
            elif damage == "input_geometry":
                x.info["chs"][1]["loc"][0] += 0.001
            elif damage == "diagnostic_output":
                result["data"].info["bads"] = ["C3"]
            elif damage == "duplicates":
                result["artifacts"]["candidates"] = ["C3", "C3"]
            elif damage == "unknown_channel":
                result["artifacts"]["candidates"] = ["missing"]
        elif op == "mark_channels":
            if damage == "mark_samples":
                result["data"]._data[1, 0] += 1e-6
            elif damage == "mark_bads":
                result["data"].info["bads"] = []
        return result

    monkeypatch.setattr(units, "invoke", changed)
    with pytest.raises(reval.ProbeError) as error:
        reval._replay(raw, events, config)
    assert error.value.code == code
    np.testing.assert_array_equal(raw.get_data(), original)


def test_mark_uses_real_fraction_cap(diagnostic_chain):
    raw, events, config = diagnostic_chain
    config["steps"][1]["params"]["max_fraction"] = 0.0
    with pytest.raises(ValueError):
        reval._replay(raw, events, config)
    assert raw.info["bads"] == []


@pytest.fixture(scope="module")
def marked_completed(completed, tmp_path_factory):
    plan = completed[0].model_copy(deep=True)
    store = tmp_path_factory.mktemp("explicit-mark-artifacts")
    for config in plan.records:
        config.steps[1].input = "repair"
        branch = [
            Step(
                id="detect",
                input="filter",
                unit_id="EEG-AUTO-BAD-CHANNEL",
                op="detect_bad_channels",
                params={
                    "adaptation_scope": "record_unlabeled",
                    "correlation_threshold": 0.0,
                    "deviation_z": 10.0,
                },
                evidence_indices=[0],
            ),
            Step(
                id="mark",
                input="filter",
                decision_from="detect",
                unit_id="EEG-BAD-CHANNEL-MARK",
                op="mark_channels",
                params={"max_fraction": 0.25},
                evidence_indices=[0],
            ),
            Step(
                id="repair",
                input="mark",
                unit_id="EEG-AUTO-BAD-CHANNEL",
                op="interpolate_bad_channels",
                params={"max_fraction": 0.25},
                evidence_indices=[0],
            ),
        ]
        config.steps[1:1] = branch
    rows = []
    for config in plan.records:
        artifacts = run_record(
            plan,
            config,
            Path(plan.input_snapshot.collection.root),
            store / config.record_id,
            store,
        )
        rows.append(
            {
                "record_id": config.record_id,
                "method_id": config.method_ref.id,
                "status": "completed",
                "result": artifacts,
            }
        )
    result = completed[1].model_dump(mode="json")
    result["records"] = rows
    result = rebind(plan.model_dump(mode="json"), result)
    return plan, result, store, completed[3]


def test_runner_mark_branch_matches_reconstruction_and_lists_all_artifacts(
    marked_completed, tmp_path
):
    out = tmp_path / "assessment" / "reconstruction"
    output = run(marked_completed, out, design="balanced")
    assert output["summary"]["status_counts"] == {"evaluated": 2}
    assert output["summary"]["resources"]["clean_replays"] == 2
    probe = reval.freeze_probe_panel(marked_completed[3])
    for subject, selection in probe["subjects"].items():
        detail = case_file(
            output, out, subject=subject, case=selection["cases"][0]["id"]
        )
        assert detail["verification"]["status"] == "verified"
        trace = detail["verification"]["steps"]
        mark = next(s for s in trace if s["op"] == "mark_channels")
        assert mark["decision_binding"]["input_node"] == "filter"
        assert mark["decision_binding"]["source_step"] == "detect"
        assert mark["parameters"]["bads"] == mark["decision_binding"]["candidates"]
    inventory = output["artifacts"]
    assert {a["path"] for a in inventory} == {
        p.relative_to(out).as_posix() for p in out.rglob("*.json")
    }
    assert {"probe_panel.json", "reconstruction_evaluation.json"} <= {
        a["name"] for a in inventory
    }
    for artifact in inventory:
        path = out / artifact["path"]
        assert file_hash(path) == artifact["sha256"]
        assert path.stat().st_size == artifact["bytes"] > 0


@pytest.mark.parametrize("damage", ["bads", "input_hash"])
def test_saved_mark_decision_must_match_verified_replay(
    marked_completed, tmp_path, damage
):
    result = deepcopy(marked_completed[1])
    entry = next(
        a
        for a in result["records"][0]["result"]["artifacts"]
        if a["name"] == "provenance.json"
    )
    source = marked_completed[2] / entry["path"]
    provenance = json.loads(source.read_text(encoding="utf-8"))
    mark = next(s for s in provenance["steps"] if s["op"] == "mark_channels")
    if damage == "bads":
        mark["parameters"]["bads"] = ["C3"]
    else:
        mark["input_hash"] = "0" * 64
    alternate = marked_completed[2] / f"wrong-binding-{damage}.json"
    write_json(alternate, provenance)
    entry.update(path=alternate.name, sha256=file_hash(alternate))
    out = tmp_path / "reconstruction"
    output = run(marked_completed, out, result=result, design="balanced")
    assert output["summary"]["status_counts"] == {"failed": 1, "evaluated": 1}
    case = reval.freeze_probe_panel(marked_completed[3])["subjects"]["sub-01"]["cases"][
        0
    ]["id"]
    assert (
        case_file(output, out, case=case)["reason_code"]
        == "DECISION_PROVENANCE_MISMATCH"
    )
