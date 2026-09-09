"""Search subprocess integration against real, small BrainVision recordings."""

import errno
import os
from pathlib import Path
import subprocess
import shutil
import sqlite3
import sys
import time

import pytest

from tests.preprocessing.conftest import make_dataset
from app.preprocessing import worker as numerical_worker
from app.preprocessing.resources import MIB, ResourceError
from app.preprocessing.storage import Storage, file_hash, digest
from app.search import evaluation, worker
from app.search.catalog import BASELINE_ID, catalog, method
from app.search.method_space import basic_space
from app.search.method_space import seed_entries, edited_entry
from app.search.evaluation_contracts import EvaluationReceipt


@pytest.fixture
def search(tmp_path):
    data = make_dataset(tmp_path / "bids", subjects=3)
    data.survey.dataset_id = data.collection.dataset_id = "eegmmidb"
    data.survey.task = "left_right_motor_imagery"
    data.collection.selected_record_ids = ["sub-01", "sub-02"]
    root = tmp_path / "search"
    worker.write_json(root / "input.json", data.model_dump(mode="json"))
    worker.write_json(
        root / "panel-request.json",
        {
            "record_subjects": {r.id: r.id for r in data.collection.records},
            "seed": 42,
            "tmin": -0.2,
            "tmax": 0.5,
            "sfreq": 160,
            "train_subjects": [],
            "development_subjects": [],
        },
    )
    worker.write_json(
        root / "limits.json",
        {
            "memory_limit_bytes": 512 * MIB,
            "disk_limit_bytes": 512 * MIB,
        },
    )
    panel = worker.prepare(root)
    assert "panel_hash" in panel, panel
    space = basic_space().model_dump(mode="json")
    worker.write_json(
        root / "protocol.json", {"space": space, "space_hash": digest(space)}
    )
    worker.write_json(root / "registry.json", catalog())
    for entry in catalog()[:2]:
        worker.write_json(root / "candidates" / entry["id"] / "policy.json", entry)
        worker.write_json(
            root / "candidates" / entry["id"] / "method.json",
            method(entry, panel).model_dump(mode="json"),
        )
    return root


def read(root, name="receipt.json", candidate_id=BASELINE_ID):
    return worker.read_json(root / "candidates" / candidate_id / name)


def run_cli(root, stage, candidate_id=None, parent_pid=None):
    args = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "app.search.worker",
        "--root",
        str(root),
        "--stage",
        stage,
    ]
    if candidate_id:
        args.extend(["--candidate", candidate_id])
    if parent_pid is not None:
        args.extend(["--parent-pid", str(parent_pid)])
    return subprocess.run(
        args,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_real_prepare_candidate_cli_and_full_inventory(search):
    prepare = run_cli(search, "prepare")
    assert prepare.returncode == 0, prepare.stderr
    run = run_cli(search, "candidate", BASELINE_ID, parent_pid=os.getpid())
    assert run.returncode == 0, run.stderr + str(read(search))
    receipt, plan, result = (
        read(search),
        read(search, "plan.json"),
        read(search, "result.json"),
    )
    assert receipt["status"] == "evaluated" and receipt["error"] is None
    assert 0 <= receipt["macro_ba"] <= 1
    assert receipt["preprocessing_seconds"] > 0 and receipt["evaluation_seconds"] > 0
    assert {"feature", "train", "predict", "total_seconds"} <= receipt["timings"].keys()
    assert receipt["versions"]["engine_sha256"] == plan["engine_sha256"]
    assert receipt["versions"]["search_engine_sha256"]
    assert receipt["predictions_sha256"] == file_hash(
        search / "candidates" / BASELINE_ID / "originalpredictions.tsv"
    )
    assert result["completed"] == result["total"] == 2
    assert len(plan["input_snapshot"]["collection"]["records"]) == 3
    assert plan["input_snapshot"]["collection"]["selected_record_ids"] == [
        "sub-01",
        "sub-02",
    ]
    original = worker.read_json(search / "input.json")
    assert (
        plan["input_snapshot"]["collection"]["records"]
        == original["collection"]["records"]
    )
    request = plan["request"]
    assert request["mode"] == "exploratory" and request["selection"] == "all"
    assert request["max_candidates"] == len(request["methods"]) == 1
    assert request["max_memory_mb"] == 512 and 64 <= request["max_disk_mb"] < 512
    assert (
        read(search, "execution.json")["job_id"]
        == receipt["job_id"]
        == result["job_id"]
    )
    assert not (search / "search.json").exists()
    assert not list(search.rglob("*.tmp"))
    assert '\n  "' in (search / "candidates" / BASELINE_ID / "receipt.json").read_text()


def test_bounded_edit_executes_without_static_catalog_membership(search):
    space = basic_space()
    seeds = seed_entries(space)
    entry = edited_entry(
        seeds[0],
        [
            {
                "action": "set_parameter",
                "node_id": "bandpass",
                "parameter": "l_freq",
                "value": 4.0,
            },
            {
                "action": "set_adaptation",
                "policy": {"adaptation": "euclidean_alignment"},
            },
        ],
        space,
        title="4–30 with EA",
        order=len(seeds),
    )
    worker.write_json(search / "registry.json", seeds + [entry])
    output = search / "candidates" / entry["id"]
    worker.write_json(output / "policy.json", entry)
    worker.write_json(
        output / "method.json",
        method(entry, worker.read_json(search / "panel.json")).model_dump(mode="json"),
    )
    reference = worker.candidate(search, BASELINE_ID)
    assert reference["status"] == "evaluated"
    result = worker.candidate(search, entry["id"])
    assert result["status"] == "evaluated", result
    assert result["representation"]["policy"]["adaptation"] == "euclidean_alignment"
    assert result["coverage"]["predicted"] == reference["coverage"]["predicted"]


def test_parallel_record_execution_preserves_numerical_predictions(search):
    parallel = search.with_name("parallel")
    shutil.copytree(search, parallel)
    protocol = worker.read_json(parallel / "protocol.json")
    protocol["record_workers"] = 2
    worker.write_json(parallel / "protocol.json", protocol)
    serial_result = worker.candidate(search, BASELINE_ID)
    parallel_result = worker.candidate(parallel, BASELINE_ID)
    assert serial_result["status"] == parallel_result["status"] == "evaluated", (
        parallel_result
    )
    assert serial_result["macro_ba"] == parallel_result["macro_ba"]
    assert serial_result["predictions_sha256"] == parallel_result["predictions_sha256"]
    import numpy as np

    for identity, left in serial_result["representation"]["records"].items():
        right = parallel_result["representation"]["records"][identity]
        np.testing.assert_array_equal(
            np.load(left["array_path"]), np.load(right["array_path"])
        )


def test_worker_runs_complete_multi_axis_assessment_in_fresh_attempt(search):
    from app.search.utility_evaluation import utility_protocol
    from app.search.assessment import verify_assessment

    protocol = worker.read_json(search / "protocol.json")
    protocol.update(assessment={"reconstruction_design": "balanced"}, utility_protocol=utility_protocol())
    worker.write_json(search / "protocol.json", protocol)
    panel = worker.prepare(search)
    assert "panel_hash" in panel
    orphan = search / "candidates" / BASELINE_ID / "core-receipts" / "a1.json"
    worker.write_json(orphan, {"interrupted_before_assessment": True})
    orphan_bytes = orphan.read_bytes()
    receipt = worker.candidate(search, BASELINE_ID)
    assert receipt["status"] == "evaluated", receipt
    assert receipt["assessment_path"] == "assessment/a2"
    assert orphan.read_bytes() == orphan_bytes
    summary = receipt["assessment"]
    assert summary is not None
    assert summary["utility"]["status"] == "evaluated", summary["utility"]
    assert summary["selection_score"] is not None
    assert summary["quality"]["status"] != "failed", summary["quality"]
    assert summary["reconstruction"]["status"] != "failed", summary["reconstruction"]
    assert verify_assessment(search / "candidates" / BASELINE_ID / receipt["assessment_path"], summary) == summary


def test_completed_job_not_executed_again_and_baseline_forwarded(search, monkeypatch):
    first = worker.candidate(search, BASELINE_ID)
    assert first["status"] == "evaluated", first
    attempts = read(search, "result.json")["records"]
    with monkeypatch.context() as patch:
        patch.setattr(
            worker.Worker, "run_once", lambda _: pytest.fail("completed job ran again")
        )
        second = worker.candidate(search, BASELINE_ID)
    assert second["status"] == "evaluated", second
    assert second["job_id"] == first["job_id"]
    assert read(search, "result.json")["records"] == attempts
    evaluate = evaluation.evaluate
    seen = []

    def capture(*args, baseline=None, **kwargs):
        seen.append(baseline)
        return evaluate(*args, baseline=baseline, **kwargs)

    monkeypatch.setattr(evaluation, "evaluate", capture)
    other = worker.candidate(search, "basic-broadband")
    assert other["status"] == "evaluated", other
    assert seen == [second]
    assert other["mean_delta"] == pytest.approx(other["macro_ba"] - second["macro_ba"])


def test_partial_resource_failure_retries_same_job_preserving_success(
    search, monkeypatch
):
    run_record = numerical_worker.run_record
    calls = []

    def fail_second(plan, config, *args, **kwargs):
        calls.append(config.record_id)
        if len(calls) == 2:
            raise ResourceError("fixture disk exhaustion")
        return run_record(plan, config, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(numerical_worker, "run_record", fail_second)
        failed = worker.candidate(search, BASELINE_ID)
    assert failed["status"] == "resource_failure", failed
    assert failed["error"] and failed.get("macro_ba") is None
    assert read(search, "result.json")["status"] == "partial"
    store = Storage(search / "engine")
    real_control = store.control
    retries = []

    def control(self, owner, job_id, action):
        retries.append((job_id, action))
        return real_control(owner, job_id, action)

    monkeypatch.setattr(Storage, "control", control)
    recovered = worker.candidate(search, BASELINE_ID)
    assert recovered["status"] == "evaluated", recovered
    assert recovered["job_id"] == failed["job_id"]
    assert recovered["plan_ref"] == failed["plan_ref"]
    assert retries == [(failed["job_id"], "retry")]
    # Resource exhaustion interrupted the second attempt after record_start.
    records = read(search, "result.json")["records"]
    assert {r["record_id"]: r["attempt"] for r in records} == {calls[0]: 1, calls[1]: 2}


@pytest.mark.parametrize("state", ["failed", "interrupted", "cancelled", "running"])
def test_terminal_and_killed_job_recovery(search, monkeypatch, state):
    real_run_once = worker.Worker.run_once

    def stop_before_work(self):
        raise RuntimeError("simulate supervisor termination before execution")

    monkeypatch.setattr(worker.Worker, "run_once", stop_before_work)
    first = worker.candidate(search, BASELINE_ID)
    assert first["status"] == "execution_failure"
    store = Storage(search / "engine")
    with store.db() as db:
        db.execute(
            "UPDATE jobs SET status=?,cancel=? WHERE id=?",
            (state, int(state == "cancelled"), first["job_id"]),
        )
        db.execute(
            "UPDATE records SET status=? WHERE job_id=?", (state, first["job_id"])
        )
    monkeypatch.setattr(worker.Worker, "run_once", real_run_once)
    receipt = worker.candidate(search, BASELINE_ID)
    assert receipt["status"] == "evaluated", receipt
    assert receipt["job_id"] == first["job_id"]


@pytest.mark.parametrize(
    "failure", ["disk", "memory", "compile", "infrastructure", "evaluation_memory"]
)
def test_failures_always_have_receipt_and_never_zero_score(
    search, monkeypatch, failure
):
    expected = "resource_failure"
    if failure in {"disk", "memory"}:
        limits = worker.read_json(search / "limits.json")
        limits[f"{failure}_limit_bytes"] = 64 * MIB if failure == "disk" else 63 * MIB
        worker.write_json(search / "limits.json", limits)
    elif failure == "compile":
        value = read(search, "method.json")
        value["recipe"][1]["params"]["h_freq"] = 200
        worker.write_json(search / "candidates" / BASELINE_ID / "method.json", value)
        expected = "candidate_invalid"
    elif failure == "infrastructure":
        monkeypatch.setattr(
            worker,
            "environment",
            lambda: (_ for _ in ()).throw(RuntimeError("broken environment")),
        )
        expected = "execution_failure"
    else:
        monkeypatch.setattr(
            evaluation,
            "evaluate",
            lambda *a, **k: (_ for _ in ()).throw(MemoryError("feature allocation")),
        )
    assert (
        worker.main(
            ["--root", str(search), "--stage", "candidate", "--candidate", BASELINE_ID]
        )
        == 1
    )
    receipt = read(search)
    assert receipt["status"] == expected, receipt
    assert receipt["error"] and receipt.get("macro_ba") is None


@pytest.mark.parametrize(
    "tamper", ["engine", "input", "plan", "artifacts", "execution"]
)
def test_completed_reuse_cannot_bypass_validation(search, monkeypatch, tamper):
    first = worker.candidate(search, BASELINE_ID)
    assert first["status"] == "evaluated", first
    if tamper == "engine":
        monkeypatch.setattr(worker, "engine_hash", lambda: "0" * 64)
    elif tamper == "input":
        data = worker.read_json(search / "input.json")
        (Path(data["collection"]["root"]) / "README").write_text(
            "changed", encoding="utf-8"
        )
    elif tamper == "plan":
        plan = read(search, "plan.json")
        plan["engine_sha256"] = "0" * 64
        worker.write_json(search / "candidates" / BASELINE_ID / "plan.json", plan)
    elif tamper == "execution":
        execution = read(search, "execution.json")
        execution["job_id"] = "f" * 32
        worker.write_json(
            search / "candidates" / BASELINE_ID / "execution.json", execution
        )
    else:
        artifact = read(search, "result.json")["records"][0]["result"]["artifacts"][0]
        (search / "engine" / artifact["path"]).write_bytes(b"changed")
    monkeypatch.setattr(
        worker.Worker, "run_once", lambda _: pytest.fail("validation bypassed")
    )
    receipt = worker.candidate(search, BASELINE_ID)
    assert receipt["status"] == "execution_failure", receipt
    assert receipt.get("macro_ba") is None


def test_recover_submit_before_execution_file_publication(search, monkeypatch):
    first = worker.candidate(search, BASELINE_ID)
    assert first["status"] == "evaluated", first
    (search / "candidates" / BASELINE_ID / "execution.json").unlink()
    monkeypatch.setattr(
        worker.PreprocessingService,
        "plan",
        lambda *a: pytest.fail("replanned saved plan"),
    )
    again = worker.candidate(search, BASELINE_ID)
    assert again["status"] == "evaluated", again
    assert again["job_id"] == first["job_id"]


def test_selection_order_remains_bound_to_original_input_hash(search):
    value = worker.read_json(search / "input.json")
    value["collection"]["selected_record_ids"].reverse()
    worker.write_json(search / "input.json", value)
    assert "panel_hash" in worker.prepare(search)
    receipt = worker.candidate(search, BASELINE_ID)
    assert receipt["status"] == "evaluated", receipt
    assert read(search, "plan.json")["input_snapshot"] == value


@pytest.mark.parametrize("case", ["one_subject", "source_changed", "overlap"])
def test_prepare_failure_receipt_and_nonzero(search, case):
    data = worker.read_json(search / "input.json")
    expected = "execution_failure"
    if case == "one_subject":
        data["collection"]["selected_record_ids"] = ["sub-01"]
        worker.write_json(search / "input.json", data)
        expected = "data_unevaluable"
    elif case == "source_changed":
        (Path(data["collection"]["root"]) / "README").write_text(
            "changed", encoding="utf-8"
        )
    else:
        search = Path(data["collection"]["root"]) / "search"
        worker.write_json(search / "input.json", data)
    assert worker.main(["--root", str(search), "--stage", "prepare"]) == 1
    receipt = worker.read_json(search / "prepare-error.json")
    assert receipt["status"] == expected and receipt["error"]


@pytest.mark.parametrize(
    "exc", [ResourceError("cap"), MemoryError("array"), OSError(errno.ENOSPC, "full")]
)
def test_resource_exception_types(exc):
    assert worker.failure_status(exc) == "resource_failure"


def test_parent_guard_is_optional_and_wired_before_prepare(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_start_parent_guard", lambda pid: calls.append(pid))

    def prepare(root):
        calls.append("prepare")
        return {"panel_hash": "fixture"}

    monkeypatch.setattr(worker, "prepare", prepare)
    args = ["--root", str(tmp_path), "--stage", "prepare"]
    assert worker.main(args) == 0
    assert calls == ["prepare"]
    calls.clear()
    assert worker.main([*args, "--parent-pid", "12345"]) == 0
    assert calls == [12345, "prepare"]


def test_parent_exit_terminates_guarded_numeric_process(tmp_path):
    parent = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", "import time; time.sleep(60)"]
    )
    child = None
    ready = tmp_path / "guard-ready"
    code = (
        "import sys, time; from pathlib import Path; "
        "from app.search.worker import _start_parent_guard; "
        "_start_parent_guard(int(sys.argv[1])); "
        "Path(sys.argv[2]).write_text('ready'); time.sleep(60)"
    )
    args = [sys.executable, "-X", "utf8", "-c", code, str(parent.pid), str(ready)]
    cwd = Path(__file__).resolve().parents[2]
    try:
        child = subprocess.Popen(args, cwd=cwd)
        deadline = time.monotonic() + 20
        while (
            not ready.exists() and child.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert ready.exists() and child.poll() is None
        parent.terminate()
        parent.wait(timeout=5)
        assert child.wait(timeout=5) == 1
        # A supervisor already gone when the child starts is also fatal.
        ready.unlink()
        orphan = subprocess.run(args, cwd=cwd, timeout=10)
        assert orphan.returncode == 1
    finally:
        for process in (child, parent):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def cached_search(search):
    receipt = worker.candidate(search, BASELINE_ID)
    assert receipt["status"] == "evaluated", receipt
    panel = worker.read_json(search / "panel.json")
    worker.write_json(
        search / "search.json",
        {
            "panel": {
                **{k: v for k, v in panel.items() if k != "trials"},
                "trial_count": len(panel["trials"]),
                "eligible_count": sum(t["eligible"] for t in panel["trials"]),
                "file_sha256": file_hash(search / "panel.json"),
            },
            "candidates": [
                {
                    "id": BASELINE_ID,
                    "status": "evaluated",
                    "receipt": receipt,
                    "job_id": receipt["job_id"],
                    "plan_ref": receipt["plan_ref"],
                }
            ],
        },
    )
    return search


def test_verify_cached_evaluations_is_read_only_and_never_refits(
    cached_search, monkeypatch
):
    root = cached_search
    receipt = worker.candidate(root, "basic-broadband")
    assert receipt["status"] == "evaluated", receipt
    state = worker.read_json(root / "search.json")
    state["candidates"].extend(
        [
            {
                "id": "basic-broadband",
                "status": "evaluated",
                "receipt": receipt,
                "job_id": receipt["job_id"],
                "plan_ref": receipt["plan_ref"],
            },
            {"id": "bp1-40-average", "status": "reserved", "receipt": None},
        ]
    )
    worker.write_json(root / "search.json", state)

    def hashes():
        return {
            p.relative_to(root).as_posix(): file_hash(p)
            for p in root.rglob("*")
            if p.is_file() and p.name != "verification.json"
        }

    before = hashes()
    run = run_cli(root, "verify", parent_pid=os.getpid())
    assert run.returncode == 0, run.stderr + str(
        worker.read_json(root / "verification.json")
    )

    def forbidden(*args, **kwargs):
        pytest.fail(
            "verification must not execute, fit, or initialize writable storage"
        )

    monkeypatch.setattr(worker.Worker, "run_once", forbidden)
    monkeypatch.setattr(numerical_worker, "run_record", forbidden)
    monkeypatch.setattr(evaluation, "evaluate", forbidden)
    monkeypatch.setattr(evaluation.LogisticRegression, "fit", forbidden)
    monkeypatch.setattr(worker, "PreprocessingService", forbidden)
    monkeypatch.setattr(Storage, "__init__", forbidden)
    assert worker.main(["--root", str(root), "--stage", "verify"]) == 0
    assert worker.read_json(root / "verification.json") == {
        "status": "verified",
        "error": None,
        "verified_candidate_ids": [BASELINE_ID, "basic-broadband"],
    }
    assert hashes() == before


def test_verify_reads_committed_uncheckpointed_engine_wal(cached_search):
    root = cached_search
    connection = sqlite3.connect(root / "engine" / "preprocessing.db")
    try:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("UPDATE records SET attempt=attempt+1")
        connection.commit()
        store = Storage(root / "engine")
        receipt = read(root)
        result = store.status(worker.OWNER, receipt["job_id"])
        worker.write_json(
            root / "candidates" / BASELINE_ID / "result.json",
            result.model_dump(mode="json"),
        )
        wal = root / "engine" / "preprocessing.db-wal"
        assert wal.stat().st_size > 0
        before = file_hash(wal)
        verification = worker.verify(root)
        assert verification["status"] == "verified", verification
        assert file_hash(wal) == before
        assert not list(root.glob(".verify-*"))
    finally:
        connection.close()


def test_verify_normalizes_missing_receipt_defaults(cached_search):
    root = cached_search
    path = root / "candidates" / BASELINE_ID / "receipt.json"
    sparse = read(root)
    for key in ("error", "error_code", "mean_delta", "stop_search"):
        sparse.pop(key, None)
    worker.write_json(path, sparse)
    state = worker.read_json(root / "search.json")
    state["candidates"][0]["receipt"] = EvaluationReceipt.model_validate(
        sparse
    ).model_dump(mode="json")
    worker.write_json(root / "search.json", state)
    before = path.read_bytes()
    verification = worker.verify(root)
    assert verification["status"] == "verified", verification
    assert path.read_bytes() == before


@pytest.mark.parametrize("stage", ["candidate", "verify"])
@pytest.mark.parametrize("change", ["filter", "window", "title", "checks"])
def test_entire_catalog_method_is_frozen_before_registration_or_cached_lookup(
    search, monkeypatch, stage, change, request
):
    root = request.getfixturevalue("cached_search") if stage == "verify" else search
    value = read(root, "method.json")
    if change == "filter":
        value["recipe"][1]["params"]["h_freq"] = (
            29  # Valid filter, wrong catalog candidate.
        )
    elif change == "window":
        value["recipe"][-1]["params"]["tmax"] = 0.4
    elif change == "title":
        value["title"] = "manually altered metadata"
    else:
        value["checks"] = ["manually injected check"]
    worker.write_json(root / "candidates" / BASELINE_ID / "method.json", value)

    def forbidden(*args, **kwargs):
        pytest.fail(
            "catalog mismatch must be rejected before registration or engine lookup"
        )

    if stage == "candidate":
        monkeypatch.setattr(worker.PreprocessingService, "register_method", forbidden)
        receipt = worker.candidate(root, BASELINE_ID)
        assert receipt["status"] == "candidate_invalid", receipt
    else:
        monkeypatch.setattr(worker._VerificationStorage, "get", forbidden)
        receipt = worker.verify(root)
        assert receipt["status"] == "execution_failure", receipt
    assert "frozen catalog recipe" in receipt["error"]


@pytest.mark.parametrize(
    "damage",
    [
        "source_signal",
        "unselected_source",
        "artifact",
        "missing_artifact",
        "panel_file",
        "panel_hash",
        "panel_summary",
        "method",
        "plan",
        "result",
        "receipt",
        "state_receipt",
        "execution",
        "engine_job",
        "predictions",
        "predictions_path",
    ],
)
def test_verify_detects_corrupt_sources_artifacts_and_cached_snapshots(
    cached_search, damage
):
    root = cached_search
    output = root / "candidates" / BASELINE_ID
    if damage in {"source_signal", "unselected_source"}:
        data = worker.read_json(root / "input.json")
        record = data["collection"]["records"][
            2 if damage == "unselected_source" else 0
        ]
        signal = Path(data["collection"]["root"]) / record["bids_path"]
        signal.with_suffix(".eeg").write_bytes(b"corrupt source bytes")
    elif damage in {"artifact", "missing_artifact"}:
        result = read(root, "result.json")
        entry = next(
            a
            for a in result["records"][0]["result"]["artifacts"]
            if a["name"] == "signal_V.npy"
        )
        path = root / "engine" / entry["path"]
        path.write_bytes(b"corrupt signal") if damage == "artifact" else path.unlink()
    elif damage == "panel_file":
        with (root / "panel.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")  # Semantic hash stays equal, physical snapshot does not.
    elif damage == "panel_hash":
        panel = worker.read_json(root / "panel.json")
        panel["seed"] += 1
        worker.write_json(root / "panel.json", panel)
        state = worker.read_json(root / "search.json")
        state["panel"]["file_sha256"] = file_hash(root / "panel.json")
        worker.write_json(root / "search.json", state)
    elif damage in {"panel_summary", "state_receipt"}:
        state = worker.read_json(root / "search.json")
        if damage == "panel_summary":
            state["panel"]["eligible_count"] += 1
        else:
            state["candidates"][0]["receipt"]["macro_ba"] = -1
        worker.write_json(root / "search.json", state)
    elif damage == "engine_job":
        store = Storage(root / "engine")
        with store.db() as db:
            db.execute("UPDATE jobs SET status='failed'")
    elif damage == "predictions":
        (output / "originalpredictions.tsv").write_text(
            "corrupt predictions", encoding="utf-8"
        )
    elif damage == "predictions_path":
        alternate = root / "wrong-predictions.tsv"
        alternate.write_bytes((output / "originalpredictions.tsv").read_bytes())
        receipt = read(root)
        receipt["predictions_path"] = str(alternate.resolve())
        worker.write_json(output / "receipt.json", receipt)
        state = worker.read_json(root / "search.json")
        state["candidates"][0]["receipt"] = receipt
        worker.write_json(root / "search.json", state)
    else:
        path = output / f"{damage}.json"
        value = worker.read_json(path)
        if damage == "method":
            value["recipe"][1]["params"]["h_freq"] = 29
        elif damage == "plan":
            value["request"]["input_ref"] = {"id": "0" * 64, "sha256": "0" * 64}
        elif damage == "result":
            value["records"][0]["attempt"] += 1
        elif damage == "receipt":
            value["macro_ba"] = -1
        else:
            value["job_id"] = "f" * 32
        worker.write_json(path, value)
    original_receipt = (output / "receipt.json").read_bytes()
    original_state = (root / "search.json").read_bytes()
    assert worker.main(["--root", str(root), "--stage", "verify"]) == 1
    verification = worker.read_json(root / "verification.json")
    assert verification["status"] == "execution_failure", verification
    assert verification["error"] and verification["verified_candidate_ids"] == []
    assert (output / "receipt.json").read_bytes() == original_receipt
    assert (root / "search.json").read_bytes() == original_state
