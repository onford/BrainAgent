from pathlib import Path
import json

import mne
import numpy as np

from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import PlanRequest, Step
from app.preprocessing.storage import file_hash
from app.preprocessing.worker import Worker
from .conftest import OWNER, PARAMETERS, make_dataset


def prepare(service, dataset, methods=None, parameters=None):
    input_ref = service.register_input(OWNER, dataset)
    refs = [service.register_method(OWNER, m) for m in (methods or baseline_methods())]
    plan_ref, plan = service.plan(
        OWNER,
        PlanRequest(
            input_ref=input_ref,
            methods=refs,
            mode="validation",
            parameters=parameters or PARAMETERS,
        ),
    )
    assert plan.records, [s.model_dump() for s in plan.screening]
    return service.submit(OWNER, plan_ref), refs, plan


def test_real_bids_two_methods_complete_reproducible_artifacts(service, dataset):
    job, refs, plan = prepare(service, dataset)
    assert job.status == "queued"
    assert service.submit(OWNER, job.plan_ref).job_id == job.job_id
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "completed", result.model_dump()
    assert result.completed == result.total == 4
    outputs = {}
    for r in result.records:
        path = service.store.artifact(OWNER, job.job_id, r["key"], "data-epo.fif")
        epochs = mne.read_epochs(path, preload=True, verbose="ERROR")
        assert epochs.get_data().shape == (7, 5, 141)
        assert epochs.ch_names[-1] == "VEOG"
        np.testing.assert_allclose(
            epochs.get_data(picks="eeg")[:, :, :41].mean(axis=-1), 0, atol=1e-18
        )
        mapping_path = service.store.artifact(
            OWNER, job.job_id, r["key"], "events.json"
        )
        mapping = json.loads(mapping_path.read_text())
        assert len(mapping) == 8 and mapping[0]["retained"] is False
        assert mapping[0]["reason"] == ["NO_DATA"]
        assert [e["original_sample"] for e in mapping][1:] == epochs.events[
            :, 0
        ].tolist()
        assert r["result"]["source_unchanged"]
        outputs[(r["method_id"], r["record_id"])] = epochs.get_data()
    baseline, regression = (
        outputs[(refs[0].id, "sub-01")],
        outputs[(refs[1].id, "sub-01")],
    )
    assert not np.allclose(baseline, regression, atol=1e-8, rtol=0)
    # Known injected EOG contamination should be substantially reduced.
    before = abs(np.corrcoef(baseline[:, 0].ravel(), baseline[:, -1].ravel())[0, 1])
    after = abs(np.corrcoef(regression[:, 0].ravel(), regression[:, -1].ravel())[0, 1])
    assert after < before / 3
    for record in dataset.collection.records:
        for path, expected in record.files.items():
            assert file_hash(Path(dataset.collection.root) / path) == expected
    published = service.publish(OWNER, refs[0], [job.job_id])
    assert service.store.get(OWNER, published, "method")["status"] == "validated"


def test_bad_candidate_isolated_and_retry_reuses_success(service, dataset, monkeypatch):
    methods = baseline_methods()
    bad = methods[0].model_copy(deep=True)
    bad.id = "all-outside-record"
    bad.recipe[2].params.update(tmin=-80, tmax=-70)
    job, refs, _ = prepare(service, dataset, [methods[0], bad])
    worker = Worker(service.store, service.allowed_roots)
    result = worker.run_once()
    assert result.status == "partial"
    assert result.completed == 2
    failed = [r for r in result.records if r["status"] == "failed"]
    assert len(failed) == 2 and all(r["error"] for r in failed)
    service.store.control(OWNER, job.job_id, "retry")
    result = worker.run_once()
    assert all(
        r["attempt"] == (1 if r["status"] == "completed" else 2) for r in result.records
    )


def test_input_tamper_is_detected_before_work(service, dataset):
    job, _, _ = prepare(service, dataset)
    path = Path(dataset.collection.root) / "README"
    path.write_text("changed", encoding="utf-8")
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "failed"
    assert all("inventory/checksum changed" in r["error"] for r in result.records)


def test_model_fit_never_uses_heldout_samples(tmp_path):
    from app.preprocessing.service import PreprocessingService

    coefficients = []
    for i, amplitude in enumerate([1, 100]):
        data = make_dataset(
            tmp_path / str(i) / "bids", subjects=1, test_amplitude=amplitude
        )
        svc = PreprocessingService(
            tmp_path / str(i) / "output", [Path(data.collection.root)]
        )
        job, refs, _ = prepare(svc, data, [baseline_methods()[1]])
        result = Worker(svc.store, svc.allowed_roots).run_once()
        assert result.status == "completed", result.model_dump()
        key = result.records[0]["key"]
        model = mne.preprocessing.read_eog_regression(
            svc.store.artifact(OWNER, job.job_id, key, "fit/eog-model.h5")
        )
        coefficients.append(model.coef_)
        binding = json.loads(
            svc.store.artifact(
                OWNER, job.job_id, key, "fit/model-binding.json"
            ).read_text()
        )
        assert binding["intervals"][0]["stop"] == 4000
    np.testing.assert_array_equal(*coefficients)


def test_decision_candidates_do_not_mutate_source(service, dataset):
    method = baseline_methods()[0].model_copy(deep=True)
    method.id = "mark-high-amplitude"
    method.recipe = [
        Step(
            id="detect",
            unit_id="EEG-AMPLITUDE-THRESHOLD",
            op="amplitude_windows",
            params={"peak_to_peak_limit_V": 0.00007, "frac_bad": 0.25},
            evidence_indices=[0],
        ),
        Step(
            id="mark",
            unit_id="EEG-BAD-CHANNEL-MARK",
            op="mark_channels",
            input="raw",
            decision_from="detect",
            params={"max_fraction": 0.75},
            evidence_indices=[0],
        ),
    ]
    method.output = "mark"
    job, _, _ = prepare(service, dataset, [method])
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "completed", result.model_dump()
    for record in result.records:
        decision = json.loads(
            service.store.artifact(
                OWNER, job.job_id, record["key"], "mark/decision.json"
            ).read_text()
        )
        assert decision["input_hash"] and decision["candidates"]
        raw = mne.io.read_raw_fif(
            service.store.artifact(OWNER, job.job_id, record["key"], "data-raw.fif"),
            preload=True,
            verbose="ERROR",
        )
        assert raw.info["bads"] == sorted(decision["candidates"])
