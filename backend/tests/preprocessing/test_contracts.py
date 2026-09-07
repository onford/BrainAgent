import ast
from pathlib import Path
import subprocess
import sys

import pytest
import portalocker

from app.preprocessing.methods import baseline_methods
from app.preprocessing.schemas import PlanRequest, Step
from app.preprocessing.storage import file_hash
from app.preprocessing.units import catalog, validate_params
from app.preprocessing.worker import Worker
from .conftest import OWNER, PARAMETERS
from .test_execution import prepare


def test_all_50_source_modules_match_frozen_catalog():
    units = catalog()
    assert len(units) == len({u.id for u in units}) == 50
    root = Path(__file__).parents[2] / "app/preprocessing/units/source"
    for unit in units:
        path = root / (unit.implementation["module"] + ".py")
        assert file_hash(path) == unit.source["code_sha256"]
        ast.parse(path.read_text(encoding="utf-8"))
    assert sum(bool(u.implementation["enabled_ops"]) for u in units) == 8


@pytest.mark.parametrize(
    "unit,op,params",
    [
        ("EEG-NOTCH", "notch", {}),
        ("EEG-ICA", "ica_fit", {}),
        (
            "EEG-FILTER",
            "filter",
            {
                "l_freq": True,
                "h_freq": 40,
                "method": "iir",
                "phase": "zero",
                "picks": ["C3"],
            },
        ),
        (
            "EEG-FILTER",
            "filter",
            {
                "l_freq": 1,
                "h_freq": 40,
                "method": "fir",
                "phase": "zero",
                "picks": ["C3"],
            },
        ),
        ("EEG-BASELINE", "baseline", {"baseline": [0, 1], "unknown": 2}),
    ],
)
def test_unregistered_and_out_of_domain_operations_rejected(unit, op, params):
    with pytest.raises(ValueError):
        validate_params(unit, op, params)


@pytest.mark.parametrize(
    "mutation",
    ["version", "missing_group", "path_escape", "incomplete_selection", "outside_root"],
)
def test_bad_upstream_contracts_rejected(service, dataset, mutation):
    data = dataset.model_dump(mode="json")
    if mutation == "version":
        data["survey"]["dataset_version"] = "other"
    elif mutation == "missing_group":
        del data["collection"]["records"][0]["files"][
            data["collection"]["records"][0]["bids_path"]
        ]
    elif mutation == "path_escape":
        data["collection"]["records"][0]["files"]["../secret"] = "0" * 64
    elif mutation == "incomplete_selection":
        data["collection"]["selected_record_ids"].append("unknown")
    else:
        service.allowed_roots = [service.store.root]
    from app.preprocessing.schemas import PreprocessInput

    with pytest.raises((ValueError, FileNotFoundError)):
        service.register_input(OWNER, PreprocessInput.model_validate(data))


def test_screening_dedup_diversity_and_all_budget(service, dataset):
    refs = service.methods.seed(OWNER)
    copy = baseline_methods()[0].model_copy(deep=True)
    copy.id, copy.title = "another-source", "same numerical workflow"
    duplicate = service.register_method(OWNER, copy)
    request = PlanRequest(
        input_ref=service.register_input(OWNER, dataset),
        methods=[refs[0], duplicate, refs[1]],
        mode="validation",
        parameters=PARAMETERS,
        max_candidates=1,
    )
    _, plan = service.plan(OWNER, request)
    assert sorted(s.status for s in plan.screening) == [
        "deferred",
        "duplicate",
        "selected",
    ]
    with pytest.raises(ValueError, match="exceed"):
        service.plan(OWNER, request.model_copy(update={"selection": "all"}))


def test_fit_scope_and_dag_are_checked_before_submit(service, dataset):
    method = baseline_methods()[1]
    method.recipe[2].fit_scope.ids = ["heldout"]
    ref = service.register_method(OWNER, method)
    _, plan = service.plan(
        OWNER,
        PlanRequest(
            input_ref=service.register_input(OWNER, dataset),
            methods=[ref],
            mode="validation",
            parameters=PARAMETERS,
        ),
    )
    assert plan.screening[0].status == "blocked"
    assert "test or incompatible" in plan.screening[0].reasons[0]
    method = baseline_methods()[0]
    method.recipe[0].input = "future"
    ref = service.register_method(OWNER, method)
    _, plan = service.plan(
        OWNER,
        PlanRequest(
            input_ref=service.register_input(OWNER, dataset),
            methods=[ref],
            mode="validation",
            parameters=PARAMETERS,
        ),
    )
    assert "topologically" in plan.screening[0].reasons[0]


def test_draft_cannot_be_forged_validated(service):
    method = baseline_methods()[0]
    method.status = "validated"
    with pytest.raises(ValueError, match="receipts"):
        service.register_method(OWNER, method)


def test_cancel_queued_job_and_restore_in_new_process(service, dataset):
    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    cancelled = service.store.control(OWNER, job.job_id, "cancel")
    assert cancelled.status == "cancelled"
    service.store.control(OWNER, job.job_id, "retry")
    # Simulate an abrupt worker exit after claiming/starting a record.
    service.store.claim()
    service.store.record_start(job.job_id, cancelled.records[0]["key"])
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.preprocessing.worker",
            "--root",
            str(service.store.root),
            "--input-root",
            dataset.collection.root,
            "--once",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert child.returncode == 0, child.stderr
    restored = service.store.status(OWNER, job.job_id)
    assert restored.status == "completed", restored.model_dump()
    assert sorted(r["attempt"] for r in restored.records) == [1, 2]


def test_live_worker_lock_is_never_stolen(service, dataset):
    prepare(service, dataset)
    with portalocker.Lock(service.store.root / "worker.lock", timeout=0):
        with pytest.raises(portalocker.exceptions.LockException):
            Worker(service.store, service.allowed_roots).run_once()


def test_owner_scope_blocks_plan_job_and_artifacts(service, dataset):
    job, _, _ = prepare(service, dataset)
    with pytest.raises(KeyError):
        service.store.status("other-owner", job.job_id)
    with pytest.raises(KeyError):
        service.submit("other-owner", job.plan_ref)
    Worker(service.store, service.allowed_roots).run_once()
    key = service.store.status(OWNER, job.job_id).records[0]["key"]
    with pytest.raises(KeyError):
        service.store.artifact("other-owner", job.job_id, key, "data-epo.fif")
    with pytest.raises(KeyError):
        service.store.artifact(OWNER, job.job_id, key, "../../preprocessing.db")


def test_detrend_executes_and_baseline_in_raw_is_blocked(service, dataset):
    method = baseline_methods()[0]
    method.recipe = [
        Step(
            id="detrend",
            unit_id="EEG-DETREND",
            op="detrend",
            params={"type": "linear", "picks": "$eeg_channels"},
            evidence_indices=[0],
        )
    ]
    method.output = "detrend"
    job, _, _ = prepare(service, dataset, [method])
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "completed", result.model_dump()


def test_corrupted_completed_artifact_is_recomputed_on_retry(service, dataset):
    good = baseline_methods()[0]
    bad = good.model_copy(deep=True)
    bad.id = "bad-window"
    bad.recipe[2].params.update(tmin=-80, tmax=-70)
    job, _, _ = prepare(service, dataset, [good, bad])
    worker = Worker(service.store, service.allowed_roots)
    result = worker.run_once()
    completed = next(r for r in result.records if r["status"] == "completed")
    artifact = service.store.artifact(
        OWNER, job.job_id, completed["key"], "events.json"
    )
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        service.store.artifact(OWNER, job.job_id, completed["key"], "events.json")
    service.store.control(OWNER, job.job_id, "retry")
    result = worker.run_once()
    assert (
        next(r for r in result.records if r["key"] == completed["key"])["attempt"] == 2
    )


def test_validated_method_runs_production_but_rejects_new_parameter_profile(
    service, dataset
):
    job, refs, _ = prepare(service, dataset, [baseline_methods()[0]])
    worker = Worker(service.store, service.allowed_roots)
    assert worker.run_once().status == "completed"
    validated = service.publish(OWNER, refs[0], [job.job_id])
    data = dataset.model_copy(update={"purpose": "production"})
    request = PlanRequest(
        input_ref=service.register_input(OWNER, data),
        methods=[validated],
        parameters=PARAMETERS,
    )
    plan_ref, plan = service.plan(OWNER, request)
    assert len(plan.records) == 2
    service.submit(OWNER, plan_ref)
    assert worker.run_once().status == "completed"
    request.parameters = {**PARAMETERS, "h_freq": 30.0}
    _, plan = service.plan(OWNER, request)
    assert (
        not plan.records
        and "validated parameter profile" in plan.screening[0].reasons[0]
    )


def test_renamed_steps_are_still_exact_duplicates(service, dataset):
    first = baseline_methods()[0]
    other = first.model_copy(deep=True)
    other.id = "renamed-workflow"
    mapping = {"raw": "raw", **{s.id: "other_" + s.id for s in other.recipe}}
    for step in other.recipe:
        step.id, step.input = mapping[step.id], mapping[step.input]
    other.output = mapping[other.output]
    _, _, plan = prepare(service, dataset, [first, other])
    assert [s.status for s in plan.screening].count("duplicate") == 1
    assert len(plan.records) == 2


def test_resource_estimate_accounts_for_large_epoch_expansion(service, dataset):
    method = baseline_methods()[0]
    method.recipe[2].params.update(tmin=-1000, tmax=1000)
    ref = service.register_method(OWNER, method)
    _, plan = service.plan(
        OWNER,
        PlanRequest(
            input_ref=service.register_input(OWNER, dataset),
            methods=[ref],
            mode="validation",
            parameters=PARAMETERS,
            max_memory_mb=64,
        ),
    )
    assert not plan.records and "memory estimate" in plan.screening[0].reasons[0]


def test_running_cancel_stops_at_a_step_boundary(service, dataset, monkeypatch):
    import app.preprocessing.runner as runner

    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    original = runner.invoke
    calls = []

    def cancel_after_first_step(unit, op, *args, **kwargs):
        result = original(unit, op, *args, **kwargs)
        calls.append(op)
        service.store.control(OWNER, job.job_id, "cancel")
        return result

    monkeypatch.setattr(runner, "invoke", cancel_after_first_step)
    result = Worker(service.store, service.allowed_roots).run_once()
    assert result.status == "cancelled" and result.completed == 0
    assert calls == ["filter"]
    assert all(r["status"] == "cancelled" for r in result.records)
