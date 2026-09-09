from types import SimpleNamespace

import pytest

from app.preprocessing import planner, resources
from app.preprocessing.inputs import working_files
from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import PlanRequest
from .conftest import OWNER, PARAMETERS


def test_auto_budget_scales_past_eight_gib_and_respects_explicit_cap(
    service, dataset, monkeypatch
):
    monkeypatch.setattr(
        resources.shutil, "disk_usage", lambda root: SimpleNamespace(free=100 * 1024**3)
    )
    monkeypatch.setattr(resources, "available_memory", lambda: 64 * 1024**3)
    monkeypatch.setattr(planner, "signal_bytes", lambda *args: 500 * 1024**2)
    request = PlanRequest(
        input_ref=service.register_input(OWNER, dataset),
        methods=[service.register_method(OWNER, baseline_methods()[0])],
        mode="validation",
        parameters=PARAMETERS,
    )
    _, plan = service.plan(OWNER, request)
    assert plan.estimated_disk_bytes > 8 * 1024**3
    assert plan.estimated_disk_bytes == sum(
        r.estimated_disk_bytes for r in plan.records
    )
    assert plan.resource_budget.disk_policy == "available_disk_85_percent"
    with pytest.raises(resources.ResourceError, match="磁盘资源不足"):
        service.plan(OWNER, request.model_copy(update={"max_disk_mb": 8192}))
    with pytest.raises(resources.ResourceError, match="内存资源不足"):
        service.plan(OWNER, request.model_copy(update={"max_memory_mb": 64}))


def test_work_copy_includes_own_run_and_shared_metadata_only(dataset):
    record = dataset.collection.records[0].model_copy(deep=True)
    record.bids_path = "sub-01/eeg/sub-01_task-motor_run-04_eeg.vhdr"
    shared = [
        "dataset_description.json",
        "participants.tsv",
        "sub-01/sub-01_scans.tsv",
        "sub-01/eeg/sub-01_electrodes.tsv",
        "sub-01/eeg/sub-01_coordsystem.json",
    ]
    target = [record.bids_path, record.bids_path.replace("eeg.vhdr", "events.tsv")]
    other = [
        record.bids_path.replace("run-04", "run-08"),
        record.bids_path.replace("eeg.vhdr", "events.tsv").replace("run-04", "run-08"),
    ]
    record.files = {name: "1" * 64 for name in shared + target + other}
    assert set(working_files(record)) == set(shared + target)


def test_worker_checks_cancellation_without_loading_all_results_per_step(
    service, dataset, monkeypatch
):
    from app.preprocessing.worker import Worker
    from .test_execution import prepare

    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    original = service.store.status
    calls = []

    def status(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.store, "status", status)
    Worker(service.store, service.allowed_roots).run_once()
    assert len(calls) <= 4
    assert original(OWNER, job.job_id).status == "completed"
    with pytest.raises(KeyError):
        service.store.cancel_requested("different-owner", job.job_id)
