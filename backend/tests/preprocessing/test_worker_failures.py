"""Fault injection with real plans, SQLite state, and verified EEG artifacts."""

from types import SimpleNamespace

import pytest

from app.preprocessing import worker as runtime
from app.preprocessing.methods import baseline_methods
from app.preprocessing.resources import ResourceError
from app.preprocessing.storage import digest
from app.preprocessing.worker import Worker
from .conftest import OWNER
from .test_execution import prepare


def plentiful(*args):
    return SimpleNamespace(disk_limit_bytes=10**12, memory_limit_bytes=10**12)


@pytest.fixture
def prepared(service, dataset, monkeypatch):
    job, _, plan = prepare(service, dataset, [baseline_methods()[0]])
    monkeypatch.setattr(runtime, "budget", plentiful)
    return service, job, plan, Worker(service.store, service.allowed_roots)


def interrupt_after_completed_records(service, job):
    # Reproduce process death after record commits but before finish_job commits.
    with service.store.db() as db:
        db.execute("UPDATE jobs SET status='interrupted' WHERE id=?", (job.job_id,))


@pytest.fixture
def completed(prepared):
    service, job, _, worker = prepared
    result = worker.run_once()
    assert result.status == "completed" and result.completed == 2
    interrupt_after_completed_records(service, job)
    return prepared, result


@pytest.mark.parametrize(
    "failure", ["environment", "engine", "input", "input_io", "input_resource"]
)
def test_global_preflight_failure_revokes_every_prior_success(
    completed, monkeypatch, failure
):
    (service, job, _, worker), before = completed
    if failure == "environment":
        monkeypatch.setattr(runtime, "environment", lambda: {})
    elif failure == "engine":
        monkeypatch.setattr(runtime, "engine_hash", lambda: "0" * 64)
    else:
        error = {
            "input": ValueError("injected invalid input"),
            "input_io": PermissionError("injected inaccessible input"),
            "input_resource": ResourceError("injected preflight resource failure"),
        }[failure]

        def reject_input(*args):
            raise error

        monkeypatch.setattr(runtime, "validate_input", reject_input)

    def must_not_execute(*args):
        pytest.fail("global preflight failure must stop before numeric execution")

    monkeypatch.setattr(runtime, "run_record", must_not_execute)
    result = worker.run_once()
    assert result.status == "failed" and result.completed == 0
    assert all(r["status"] == "failed" and r["result"] is None for r in result.records)
    assert [r["attempt"] for r in result.records] == [
        r["attempt"] for r in before.records
    ]
    assert all(r["error"] for r in service.store.status(OWNER, job.job_id).records)


@pytest.mark.parametrize("damaged_count", [1, 2])
def test_resource_failure_keeps_only_verified_successes_and_retries_damage(
    completed, monkeypatch, damaged_count
):
    (service, job, plan, worker), before = completed
    damaged = {r["key"] for r in before.records[:damaged_count]}
    for record in before.records[:damaged_count]:
        path = service.store.artifact(OWNER, job.job_id, record["key"], "events.json")
        path.write_text("damaged artifact", encoding="utf-8")

    def insufficient(*args):
        # Revocation must already be durable, not just absent from a Python set.
        rows = service.store.status(OWNER, job.job_id).records
        assert all(
            r["status"] != "completed" and r["result"] is None
            for r in rows
            if r["key"] in damaged
        )
        return SimpleNamespace(disk_limit_bytes=0, memory_limit_bytes=10**12)

    monkeypatch.setattr(runtime, "budget", insufficient)
    result = worker.run_once()
    assert result.completed == 2 - damaged_count
    assert result.status == ("partial" if damaged_count == 1 else "failed")
    for record in result.records:
        assert record["attempt"] == 1
        if record["key"] in damaged:
            assert record["status"] == "failed" and record["result"] is None
            assert record["error"].startswith("ResourceError:")
        else:
            assert record["status"] == "completed"
            assert runtime.verify_result(service.store.root, record["result"])

    # The immutable plan stays the same; only damaged units get new attempts.
    monkeypatch.setattr(runtime, "budget", plentiful)
    service.store.control(OWNER, job.job_id, "retry")
    resumed = worker.run_once()
    assert resumed.status == "completed" and resumed.completed == 2
    assert resumed.plan_ref == job.plan_ref
    for record in resumed.records:
        assert record["attempt"] == (2 if record["key"] in damaged else 1)
        assert runtime.verify_result(service.store.root, record["result"])


@pytest.mark.parametrize("error_type", [ValueError, PermissionError, FileNotFoundError])
@pytest.mark.parametrize("resume", [False, True])
def test_final_integrity_failure_cannot_publish_completed_records(
    prepared, monkeypatch, error_type, resume
):
    service, job, _, worker = prepared
    if resume:
        assert worker.run_once().status == "completed"
        interrupt_after_completed_records(service, job)
    validate = runtime.validate_input
    calls = []

    def fail_final_check(*args):
        calls.append(1)
        if len(calls) == 2:
            assert service.store.status(OWNER, job.job_id).completed == 2
            raise error_type("injected final integrity failure")
        return validate(*args)

    monkeypatch.setattr(runtime, "validate_input", fail_final_check)
    result = worker.run_once()
    assert len(calls) == 2
    assert result.status == "failed" and result.completed == 0
    assert all(r["status"] == "failed" and r["result"] is None for r in result.records)
    assert all(r["attempt"] == 1 for r in result.records)
    assert all(r["error"].startswith(error_type.__name__ + ":") for r in result.records)


def test_failed_attempt_does_not_charge_its_estimate_to_later_units(
    prepared, monkeypatch
):
    service, job, plan, worker = prepared
    first, second = plan.records
    execute = runtime.run_record
    executed, checks = [], []

    def fail_after_writing_artifacts(*args):
        result = execute(*args)
        executed.append(args[1].record_id)
        if len(executed) == 1:
            raise ValueError("injected failure after artifact writes")
        return result

    def capacity(*args):
        checks.append(1)
        # A failed attempt leaves files behind. Remaining space still fits the
        # second unit, but not both units' estimates counted a second time.
        limit = (
            first.estimated_disk_bytes + second.estimated_disk_bytes
            if len(checks) == 1
            else second.estimated_disk_bytes
        )
        return SimpleNamespace(disk_limit_bytes=limit, memory_limit_bytes=10**12)

    monkeypatch.setattr(runtime, "run_record", fail_after_writing_artifacts)
    monkeypatch.setattr(runtime, "budget", capacity)
    result = worker.run_once()
    assert executed == [first.record_id, second.record_id]
    assert result.status == "partial" and result.completed == 1
    rows = {r["record_id"]: r for r in result.records}
    assert (
        rows[first.record_id]["error"]
        == "ValueError: injected failure after artifact writes"
    )
    assert rows[second.record_id]["status"] == "completed"
    assert runtime.verify_result(service.store.root, rows[second.record_id]["result"])
    assert (
        service.store.root / "runs" / job.job_id / "r0000/a1/signal_V.npy"
    ).is_file()


@pytest.mark.parametrize("cancel", [False, True])
def test_late_resource_failure_preserves_new_success_and_honors_cancellation(
    prepared, monkeypatch, cancel
):
    service, job, plan, worker = prepared
    checks = []

    def capacity(*args):
        checks.append(1)
        if len(checks) == 2:
            if cancel:
                service.store.control(OWNER, job.job_id, "cancel")
            raise ResourceError("injected late resource shortage")
        return plentiful()

    monkeypatch.setattr(runtime, "budget", capacity)
    result = worker.run_once()
    assert result.status == ("cancelled" if cancel else "partial")
    assert result.completed == 1
    rows = {r["key"]: r for r in result.records}
    first, second = [rows[digest([c.method_ref.id, c.record_id])] for c in plan.records]
    assert first["status"] == "completed" and first["attempt"] == 1
    assert runtime.verify_result(service.store.root, first["result"])
    assert second["status"] == ("cancelled" if cancel else "failed")
    assert second["attempt"] == 0 and second["result"] is None

    monkeypatch.setattr(runtime, "budget", plentiful)
    service.store.control(OWNER, job.job_id, "retry")
    resumed = worker.run_once()
    assert resumed.status == "completed" and resumed.completed == 2
    assert all(r["attempt"] == 1 for r in resumed.records)
