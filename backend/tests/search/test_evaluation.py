import csv
import hashlib
import json
from pathlib import Path

import mne
import numpy as np
import pytest
from pydantic import ValidationError

from app.preprocessing.schemas import (
    ExecutionPlan,
    PlanRequest,
    RecordPlan,
    Ref,
    RunResult,
    Step,
)
from app.preprocessing.storage import digest, file_hash, write_json
from app.search import evaluation
from app.search.evaluation_contracts import EvaluationReceipt, FrozenPanel
from app.search.panel import freeze_panel
from tests.search.test_panel import make_input


def make_case(tmp_path):
    data = make_input(tmp_path / "bids")
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=42,
        tmin=-0.1,
        tmax=0.1,
        sfreq=160,
        train_subjects=["sub-01"],
        development_subjects=["sub-02", "sub-03"],
    )
    method = Ref(id="a" * 64, sha256="a" * 64)
    input_ref = Ref(id=panel["input_hash"], sha256=panel["input_hash"])
    configs = []
    for rid in panel["records"]:
        configs.append(
            RecordPlan(
                method_ref=method,
                record_id=rid,
                steps=[
                    Step(
                        id="resample",
                        unit_id="EEG-RESAMPLE",
                        op="resample",
                        params={"sfreq": 160},
                        evidence_indices=[0],
                    ),
                    Step(
                        id="epochs",
                        input="resample",
                        unit_id="EEG-EPOCH",
                        op="epoch",
                        params={
                            "tmin": -0.1,
                            "tmax": 0.1,
                            "picks": ["C4", "C3"],
                            "event_id": data.survey.event_id,
                        },
                        evidence_indices=[0],
                    ),
                ],
                output="epochs",
                code_hashes={},
            )
        )
    plan = ExecutionPlan(
        request=PlanRequest(input_ref=input_ref, methods=[method], mode="validation"),
        input_snapshot=data,
        screening=[],
        records=configs,
        environment={},
        engine_sha256="b" * 64,
    )
    root = tmp_path / "store"
    results = []
    for config in configs:
        directory = root / config.record_id
        directory.mkdir(parents=True)
        trials = [t for t in panel["trials"] if t["record_id"] == config.record_id]
        rows, signal = [], []
        wave = np.sin(np.arange(33) * 2 * np.pi / 8)
        for trial in trials:
            code = panel["event_codes"][trial["label"]]
            index = len(signal) if trial["eligible"] else None
            rows.append(
                dict(
                    event_id=trial["event_id"],
                    label=trial["label"],
                    code=code,
                    original_sample=trial["source_sample"],
                    output_sample=trial["output_sample"],
                    output_sfreq=160,
                    retained=trial["eligible"],
                    epoch_index=index,
                    reason=[] if trial["eligible"] else [trial["reason"]],
                )
            )
            if trial["eligible"]:
                # Subject 2 is perfectly decoded; much larger subject 3 is
                # reversed. This separates macro BA=.5 from pooled BA=.1.
                left = code == 1
                if config.record_id == "sub-03":
                    left = not left
                amplitudes = np.array([1, 5] if left else [5, 1]) * 1e-6
                signal.append(amplitudes[:, None] * wave)
        signal = np.asarray(signal)
        retained = [r for r in rows if r["retained"]]
        epochs = mne.EpochsArray(
            signal,
            mne.create_info(["C4", "C3"], 160, "eeg"),
            events=np.array([[r["output_sample"], 0, r["code"]] for r in retained]),
            event_id=data.survey.event_id,
            tmin=-0.1,
            baseline=None,
            verbose="ERROR",
        )
        epochs.selection = np.array([i for i, r in enumerate(rows) if r["retained"]])
        epochs.drop_log = tuple(
            () if r["retained"] else tuple(r["reason"]) for r in rows
        )
        epochs.save(
            directory / "data-epo.fif", fmt="double", overwrite=True, verbose="ERROR"
        )
        np.save(directory / "signal_V.npy", signal, allow_pickle=False)
        after = dict(
            kind="epochs",
            unit="V",
            channels=["C4", "C3"],
            types=["eeg", "eeg"],
            sfreq=160,
            shape=list(signal.shape),
            epoch_selection=epochs.selection.tolist(),
        )
        delta = dict(
            after=after, events_before=len(rows), events_retained=len(retained)
        )
        write_json(directory / "events.json", rows)
        write_json(directory / "delta.json", delta)
        write_json(
            directory / "provenance.json",
            dict(
                input_ref=input_ref.model_dump(),
                method_ref=method.model_dump(),
                engine_sha256=plan.engine_sha256,
                steps=[
                    dict(
                        branch="main",
                        step_id=s.id,
                        unit_id=s.unit_id,
                        op=s.op,
                        parameters=s.params,
                    )
                    for s in config.steps
                ],
            ),
        )
        artifacts = [
            dict(name=p.name, path=p.relative_to(root).as_posix(), sha256=file_hash(p))
            for p in directory.iterdir()
        ]
        results.append(
            dict(
                record_id=config.record_id,
                method_id=method.id,
                status="completed",
                result=dict(artifacts=artifacts, delta=delta),
            )
        )
    plan_hash = digest(plan.model_dump(mode="json"))
    result = RunResult(
        job_id="fixture",
        plan_ref=Ref(id=plan_hash, sha256=plan_hash),
        status="completed",
        records=results,
        completed=3,
        total=3,
        cancel_requested=False,
    )
    return result, plan, root, panel


def rehash(result, root, record_id, name):
    item = next(r for r in result.records if r["record_id"] == record_id)
    artifact = next(a for a in item["result"]["artifacts"] if a["name"] == name)
    artifact["sha256"] = file_hash(root / artifact["path"])


def test_macro_is_subject_mean_not_pooled_and_baseline_is_paired(tmp_path):
    result, plan, root, panel = make_case(tmp_path)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "evaluated", receipt
    assert receipt["macro_ba"] == 0.5
    assert receipt["macro_ba"] != 2 / 20  # pooled recalls are both 1/10
    assert receipt["subjects"]["sub-02"]["ba"] == 1
    assert receipt["subjects"]["sub-03"]["ba"] == 0
    assert receipt["mean_delta"] is None
    development = dict(
        original=24,
        eligible=20,
        predicted=20,
        missing=0,
        common_invalid=4,
        common_invalid_reasons={"NO_DATA": 2, "TOO_SHORT": 2},
        available=20,
    )
    assert receipt["coverage"] == {
        **development,
        "development": development,
        "train": dict(
            original=6,
            eligible=4,
            predicted=0,
            missing=0,
            common_invalid=2,
            common_invalid_reasons={"NO_DATA": 1, "TOO_SHORT": 1},
            available=4,
        ),
    }
    assert receipt["diagnostics"]["converged"] is True
    assert all(receipt["timings"][key] >= 0 for key in ("feature", "train", "predict"))
    with Path(receipt["predictions_path"]).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 30
    assert all(
        not r["prediction"]
        for r in rows
        if r["role"] == "train" or r["eligible"] == "False"
    )
    assert "left_hand" not in json.dumps(receipt)  # no per-trial labels in receipt
    paired = evaluation.evaluate(
        result, plan, root, panel, tmp_path / "paired", baseline=receipt
    )
    assert paired["status"] == "evaluated", paired
    assert paired["mean_delta"] == 0
    assert all(s["delta"] == 0 for s in paired["subjects"].values())


def test_scaler_and_classifier_never_fit_development_data(tmp_path, monkeypatch):
    result, plan, root, panel = make_case(tmp_path)
    scaler_fits, classifier_fits = [], []
    original_scaler, original_lr = (
        evaluation.StandardScaler.fit,
        evaluation.LogisticRegression.fit,
    )

    def scaler_fit(self, X, *args, **kwargs):
        scaler_fits.append(np.array(X, copy=True))
        return original_scaler(self, X, *args, **kwargs)

    def classifier_fit(self, X, y, *args, **kwargs):
        classifier_fits.append((np.array(X, copy=True), np.array(y, copy=True)))
        return original_lr(self, X, y, *args, **kwargs)

    monkeypatch.setattr(evaluation.StandardScaler, "fit", scaler_fit)
    monkeypatch.setattr(evaluation.LogisticRegression, "fit", classifier_fit)
    first = evaluation.evaluate(result, plan, root, panel, tmp_path / "first")
    assert first["status"] == "evaluated", first
    # Change only development signals by orders of magnitude, keeping valid
    # shapes, provenance and hash inventories. Fitted inputs must stay identical.
    for rid in panel["development_subjects"]:
        path = root / rid / "signal_V.npy"
        values = np.load(path)
        np.save(path, values * 1000)
        rehash(result, root, rid, "signal_V.npy")
    second = evaluation.evaluate(result, plan, root, panel, tmp_path / "second")
    assert second["status"] == "evaluated", second
    assert len(scaler_fits) == len(classifier_fits) == 2
    assert scaler_fits[0].shape == (4, 2)
    np.testing.assert_array_equal(scaler_fits[0], scaler_fits[1])
    np.testing.assert_array_equal(classifier_fits[0][0], classifier_fits[1][0])
    np.testing.assert_array_equal(classifier_fits[0][1], classifier_fits[1][1])


@pytest.mark.parametrize(
    "mutation",
    [
        "drop",
        "omit",
        "extra",
        "duplicate",
        "label",
        "sample",
        "epoch_index",
        "rate",
        "hash",
        "channels",
        "time",
    ],
)
def test_candidate_cannot_change_frozen_denominator_or_contract(
    tmp_path, monkeypatch, mutation
):
    result, plan, root, panel = make_case(tmp_path)
    path = root / "sub-02" / "events.json"
    rows = json.loads(path.read_text())
    if mutation == "drop":
        rows[1].update(retained=False, epoch_index=None)
    elif mutation == "omit":
        rows.pop(1)
    elif mutation == "extra":
        rows.append({**rows[1], "event_id": "extra:event:1"})
    elif mutation == "duplicate":
        rows.append(rows[1].copy())
    elif mutation == "label":
        rows[1]["label"] = "right_hand"
    elif mutation == "sample":
        rows[1]["output_sample"] += 1
    elif mutation == "epoch_index":
        rows[2]["epoch_index"] = rows[1]["epoch_index"]
    elif mutation == "rate":
        rows[1]["output_sfreq"] = 128
    elif mutation in {"channels", "time"}:
        fif = root / "sub-02" / "data-epo.fif"
        epochs = mne.read_epochs(fif, preload=True, verbose="ERROR")
        if mutation == "channels":
            epochs.reorder_channels(["C3", "C4"])
        else:
            epochs.shift_time(1 / 160, relative=True)
        epochs.save(fif, overwrite=True, fmt="double", verbose="ERROR")
        rehash(result, root, "sub-02", "data-epo.fif")
    if mutation == "hash":
        path.write_text("[]")
    else:
        write_json(path, rows)
        rehash(result, root, "sub-02", "events.json")
    monkeypatch.setattr(
        evaluation.StandardScaler,
        "fit",
        lambda *a, **k: pytest.fail("invalid candidate fitted model"),
    )
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "candidate_invalid", receipt
    assert receipt["macro_ba"] is receipt["mean_delta"] is None
    assert receipt["coverage"]["original"] == 24
    assert receipt["coverage"]["eligible"] == 20
    assert receipt["error"]
    if mutation in {"drop", "omit"}:
        assert receipt["subjects"]["sub-02"]["missing"] == 1


def test_nonfinite_signal_is_execution_failure_and_mmap_is_closed(
    tmp_path, monkeypatch
):
    result, plan, root, panel = make_case(tmp_path)
    path = root / "sub-02" / "signal_V.npy"
    values = np.load(path)
    values[0, 0, 0] = np.nan
    np.save(path, values)
    rehash(result, root, "sub-02", "signal_V.npy")
    mapped = []
    original_load = evaluation.np.load

    def load(*args, **kwargs):
        value = original_load(*args, **kwargs)
        if isinstance(value, np.memmap):
            mapped.append(value)
        return value

    monkeypatch.setattr(evaluation.np, "load", load)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "execution_failure", receipt
    assert receipt["error"] == "nonfinite signal"
    assert mapped and all(value._mmap.closed for value in mapped)
    # This rename would fail on Windows with a live mapping.
    path.rename(path.with_suffix(".closed.npy"))


def test_training_failure_and_resource_failure_have_distinct_owners(
    tmp_path, monkeypatch
):
    result, plan, root, panel = make_case(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("estimator failed")

    monkeypatch.setattr(evaluation.LogisticRegression, "fit", fail)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "failure")
    assert receipt["status"] == "execution_failure", receipt
    assert receipt["error"] == "estimator failed"

    def resource(*args, **kwargs):
        raise MemoryError("worker owns memory budget")

    monkeypatch.setattr(evaluation.LogisticRegression, "fit", resource)
    with pytest.raises(MemoryError):
        evaluation.evaluate(result, plan, root, panel, tmp_path / "resource")


def test_invalid_baseline_stops_before_feature_reads(tmp_path, monkeypatch):
    result, plan, root, panel = make_case(tmp_path)
    monkeypatch.setattr(
        evaluation, "_mapped", lambda *a: pytest.fail("invalid baseline read signal")
    )
    receipt = evaluation.evaluate(
        result,
        plan,
        root,
        panel,
        tmp_path / "evaluation",
        baseline={"status": "execution_failure"},
    )
    assert receipt["status"] == "data_unevaluable"
    assert receipt["error_code"] == "baseline_invalid"
    assert receipt["stop_search"] is True
    assert "Baseline is not evaluated" in receipt["error"]


def test_group_coverage_on_training_failure_uses_available_not_predictions(
    tmp_path, monkeypatch
):
    result, plan, root, panel = make_case(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("deliberate training failure")

    monkeypatch.setattr(evaluation.LogisticRegression, "fit", fail)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "execution_failure"
    assert receipt["error"] == "deliberate training failure"
    for key in ("original", "eligible", "available", "predicted", "missing"):
        assert receipt["coverage"][key] == receipt["coverage"]["development"][key]
    assert receipt["coverage"]["available"] == 20
    assert receipt["coverage"]["predicted"] == receipt["coverage"]["missing"] == 0
    assert receipt["coverage"]["train"]["available"] == 4
    assert all(
        s["available_trials"] == s["eligible_trials"] and s["ba"] is None
        for s in receipt["subjects"].values()
    )


def test_output_models_and_worker_metadata_roundtrip(tmp_path):
    result, plan, root, panel = make_case(tmp_path)
    FrozenPanel.model_validate(panel)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt == EvaluationReceipt.model_validate(receipt).model_dump(mode="json")
    receipt.update(
        candidate_id="bp8-30-average",
        job_id=result.job_id,
        plan_ref=result.plan_ref.model_dump(),
        preprocessing_seconds=2.0,
        evaluation_seconds=1.0,
        versions={
            "worker_version": 1,
            "search_engine_sha256": "a" * 64,
            "engine_sha256": "b" * 64,
            "environment_sha256": "c" * 64,
            "panel_hash": panel["panel_hash"],
            "input_hash": panel["input_hash"],
            "method_hash": "d" * 64,
        },
    )
    receipt["timings"].update(
        preprocessing_seconds=2.0, evaluation_seconds=1.0, total_seconds=3.0
    )
    validated = EvaluationReceipt.model_validate(receipt)
    assert validated.versions.worker_version == 1
    assert validated.plan_ref.id == result.plan_ref.id
    assert validated.timings.total_seconds == 3


@pytest.mark.parametrize(
    "status",
    ["candidate_invalid", "execution_failure", "resource_failure", "data_unevaluable"],
)
def test_early_worker_failure_contract(status):
    receipt = EvaluationReceipt.model_validate(
        dict(
            status=status,
            error="worker failed before evaluation",
            candidate_id="bp8-30-average",
            job_id=None,
            plan_ref=None,
            preprocessing_seconds=0.2,
            evaluation_seconds=0.0,
            timings=dict(
                preprocessing_seconds=0.2, evaluation_seconds=0.0, total_seconds=0.2
            ),
            versions={"worker_version": 1},
        )
    )
    assert receipt.coverage is None
    assert receipt.macro_ba is receipt.mean_delta is None
    assert receipt.timings.feature is None  # Unknown rather than a fabricated 0.
    assert receipt.stop_search == (status == "data_unevaluable")
    assert receipt.predictions_sha256 is None


def test_prediction_hash_binds_exact_tsv_content_and_persisted_receipt(tmp_path):
    result, plan, root, panel = make_case(tmp_path)
    output = tmp_path / "evaluation"
    receipt = evaluation.evaluate(result, plan, root, panel, output)
    assert receipt["status"] == "evaluated", receipt
    path = Path(receipt["predictions_path"])
    original = path.read_bytes()
    expected = hashlib.sha256(original).hexdigest()
    assert receipt["predictions_sha256"] == expected
    assert (
        json.loads((output / "receipt.json").read_text(encoding="utf-8"))[
            "predictions_sha256"
        ]
        == expected
    )
    # An edit to an actual prediction must invalidate the content hash.
    changed = original.replace(b"\tleft_hand\r\n", b"\tright_hand\r\n", 1)
    if changed == original:
        changed = original.replace(b"\tleft_hand\n", b"\tright_hand\n", 1)
    assert changed != original
    path.write_bytes(changed)
    assert file_hash(path) != receipt["predictions_sha256"]
    assert (
        json.loads((output / "receipt.json").read_text(encoding="utf-8"))[
            "predictions_sha256"
        ]
        == expected
    )


@pytest.mark.parametrize("checksum", ["", "a" * 63, "g" * 64, "A" * 64])
def test_receipt_rejects_malformed_prediction_sha256(tmp_path, checksum):
    result, plan, root, panel = make_case(tmp_path)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "evaluated", receipt
    receipt["predictions_sha256"] = checksum
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate(receipt)


@pytest.mark.parametrize("missing", [True, False])
def test_legacy_evaluated_receipt_without_prediction_hash_remains_readable(
    tmp_path, missing
):
    result, plan, root, panel = make_case(tmp_path)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "evaluated", receipt
    assert receipt["predictions_sha256"] == file_hash(Path(receipt["predictions_path"]))
    receipt.pop("predictions_sha256")
    if not missing:
        receipt["predictions_sha256"] = None
    # Validation is read-only and does not manufacture a hash for old artifacts.
    path = tmp_path / "legacy-receipt.json"
    write_json(path, receipt)
    original = path.read_bytes()
    validated = EvaluationReceipt.model_validate_json(original)
    assert validated.status == "evaluated"
    assert validated.macro_ba == receipt["macro_ba"]
    assert validated.predictions_sha256 is None
    assert path.read_bytes() == original


def test_prediction_hash_failure_returns_null_hash_and_readable_error(
    tmp_path, monkeypatch
):
    result, plan, root, panel = make_case(tmp_path)
    original_hash = evaluation.file_hash

    def fail_prediction_hash(path):
        if path.name == "originalpredictions.tsv":
            raise OSError("prediction file became unreadable")
        return original_hash(path)

    monkeypatch.setattr(evaluation, "file_hash", fail_prediction_hash)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "execution_failure", receipt
    assert receipt["error"] == "prediction file became unreadable"
    assert receipt["predictions_sha256"] is None
    assert receipt["macro_ba"] is receipt["mean_delta"] is None
    with pytest.raises(ValidationError, match="predictions_sha256=None"):
        EvaluationReceipt.model_validate({**receipt, "predictions_sha256": "a" * 64})


@pytest.mark.parametrize(
    "mutation",
    [
        "mixed_denominator",
        "subject_total",
        "missing",
        "metric",
        "extra",
        "worker_version",
    ],
)
def test_receipt_schema_rejects_inconsistent_output(tmp_path, mutation):
    result, plan, root, panel = make_case(tmp_path)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    if mutation == "mixed_denominator":
        receipt["coverage"]["original"] += 6
    elif mutation == "subject_total":
        receipt["subjects"]["sub-02"]["original_trials"] += 1
    elif mutation == "missing":
        receipt["coverage"]["train"]["missing"] = 1
    elif mutation == "metric":
        receipt["macro_ba"] = 0.9
    elif mutation == "worker_version":
        receipt["versions"] = {"panel_hash": panel["panel_hash"]}
    else:
        receipt["unexpected"] = "forbidden"
    with pytest.raises(ValidationError):
        EvaluationReceipt.model_validate(receipt)


def test_invalid_panel_schema_is_readable_and_stops_search(tmp_path, monkeypatch):
    result, plan, root, panel = make_case(tmp_path)
    panel["trials"][0]["role"] = "test"
    monkeypatch.setattr(
        evaluation, "_mapped", lambda *a: pytest.fail("invalid panel read signal")
    )
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "data_unevaluable"
    assert receipt["stop_search"] is True
    assert receipt["error_code"] == "panel_schema_invalid"
    assert "trials.0.role" in receipt["error"]
    assert receipt["coverage"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_record",
        "duplicate_record",
        "plan_hash",
        "input_hash",
        "ica",
        "changed_window",
    ],
)
def test_plan_is_bound_to_panel_and_fixed_operations(tmp_path, mutation):
    result, plan, root, panel = make_case(tmp_path)
    if mutation == "missing_record":
        plan.records.pop()
    elif mutation == "duplicate_record":
        plan.records.append(plan.records[0])
    elif mutation == "input_hash":
        plan.input_snapshot.collection.selected_record_ids.pop()
    elif mutation == "ica":
        plan.records[0].steps[0].op = "ica_fit"
    elif mutation == "changed_window":
        plan.records[0].steps[-1].params["tmin"] = 0
    if mutation != "plan_hash":
        identity = digest(plan.model_dump(mode="json"))
        result.plan_ref = Ref(id=identity, sha256=identity)
    else:
        result.plan_ref = Ref(id="0" * 64, sha256="0" * 64)
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "candidate_invalid", receipt
    assert receipt["macro_ba"] is None


def test_variance_floor_is_reported_without_nonfinite_features(tmp_path):
    result, plan, root, panel = make_case(tmp_path)
    for rid in panel["records"]:
        path = root / rid / "signal_V.npy"
        values = np.load(path)
        values[:, 0, :] = 0
        np.save(path, values)
        rehash(result, root, rid, "signal_V.npy")
    receipt = evaluation.evaluate(result, plan, root, panel, tmp_path / "evaluation")
    assert receipt["status"] == "evaluated", receipt
    assert receipt["diagnostics"]["floor_fraction"] == 0.5


def test_evaluator_accepts_actual_runner_artifacts(tmp_path):
    from tests.preprocessing.conftest import make_dataset
    from tests.preprocessing.test_execution import prepare
    from app.preprocessing.service import PreprocessingService
    from app.preprocessing.worker import Worker
    from app.search.catalog import catalog, method

    data = make_dataset(tmp_path / "bids", sfreqs=[200, 128])
    for record in data.collection.records:
        record.intervals = []
    panel = freeze_panel(
        data,
        {r.id: r.id for r in data.collection.records},
        seed=42,
        tmin=-0.2,
        tmax=0.5,
        sfreq=160,
    )
    service = PreprocessingService(tmp_path / "store", [tmp_path / "bids"])
    candidate = method(catalog()[0], panel)
    candidate.applicability = {}  # Exercise the recipe on a synthetic dataset.
    _, _, plan = prepare(service, data, [candidate])
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "completed", result
    receipt = evaluation.evaluate(
        result, plan, service.store.root, panel, tmp_path / "evaluation"
    )
    assert receipt["status"] == "evaluated", receipt
    assert receipt["coverage"]["eligible"] == 14
    assert receipt["coverage"]["common_invalid"] == 2
    assert receipt["coverage"]["train"]["eligible"] == 0
