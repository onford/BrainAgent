"""Real spawn regression: exact predictions, bounded resources and no orphans."""
import json
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys
import time
import warnings

import numpy as np
import pytest
from pydantic import ValidationError

from app.preprocessing.storage import digest, file_hash
from app.search import utility_evaluation as utility, utility_parallel as parallel
from tests.search.test_utility_evaluation import case  # noqa: F401 - shared artifact fixture


def read(artifact):
    path = Path(artifact["path"])
    assert file_hash(path) == artifact["sha256"]
    return json.loads(path.read_text(encoding="utf-8"))


def test_real_spawn_serial_parallel_exact_six_model_predictions(case, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(utility, "run_utility_tasks", parallel.run_utility_tasks)
    common = {"memory_budget_bytes": 40 * parallel.GIB, "reserve_bytes": 4 * parallel.GIB}
    serial = utility.evaluate_dataset_utility(*case, tmp_path / "serial", execution={**common, "max_workers": 1})
    config = {**common, "max_workers": 4}
    multi = utility.evaluate_dataset_utility(*case, tmp_path / "parallel", execution=config)
    assert serial["status"] == multi["status"] == "evaluated"
    assert serial["selection_score"] == multi["selection_score"]
    assert serial["learner_scores"] == multi["learner_scores"]
    assert multi["protocol"]["sha256"] == digest(utility.utility_protocol(execution=config))
    for name in utility.LEARNER_SUITE:
        a, b = serial["learners"][name], multi["learners"][name]
        assert a["status"] == b["status"] == "evaluated", (name, a["error"], b["error"])
        assert read(a["predictions"]) == read(b["predictions"])  # Probabilities and decision scores included.
        assert a["subjects"] == b["subjects"] and a["summary"] == b["summary"]
        for af, bf in zip(a["folds"], b["folds"], strict=True):
            assert read(af["metadata"]) == read(bf["metadata"])  # Includes inner CV selection and roles.
        process_audit = read(read(b["metadata"])["execution"])
        assert process_audit["pid"] != os.getpid()
        assert process_audit["thread_pools"] and all(pool["num_threads"] == 1 for pool in process_audit["thread_pools"])
    serial_audit, parallel_audit = read(serial["execution"]), read(multi["execution"])
    assert serial_audit["max_active_workers"] == 1
    assert 1 < parallel_audit["max_active_workers"] <= 4
    assert len({v["pid"] for v in parallel_audit["workers"].values()}) == 6
    assert all(v["exitcode"] == 0 for v in parallel_audit["workers"].values())
    for receipt in (serial, multi):
        for artifact in read(receipt["inputs"])["arrays"].values():
            values = np.load(artifact["path"], mmap_mode="r", allow_pickle=False)
            assert not values.flags.writeable
            values._mmap.close()
    assert not [p for p in mp.active_children() if p.name.startswith("utility-")]


def test_frozen_config_capacity_and_no_live_host_in_protocol():
    config = parallel.utility_execution({"max_workers": 4, "memory_budget_bytes": 40 * parallel.GIB})
    assert parallel.worker_capacity(config, 63 * parallel.GIB) == 4
    assert parallel.worker_capacity(config, 13 * parallel.GIB) == 1
    assert parallel.worker_capacity(config, 11 * parallel.GIB) == 0
    frozen = utility.utility_protocol(execution=config)
    assert frozen["resources"]["execution"] == config
    config["max_workers"] = 2
    assert frozen["resources"]["execution"]["max_workers"] == 4
    assert digest(frozen) != digest(utility.utility_protocol(execution=config))
    for invalid in ({"max_workers": 5}, {"blas_threads": 2}, {"extra": 1}, {"model_memory_bytes": 20 * parallel.GIB},
                    {"timeout_seconds": float("nan")}, {"max_workers": True}):
        with pytest.raises(ValidationError):
            parallel.utility_execution(invalid)


def _sleep_worker(name, payload, config):
    parallel._parent_guard()
    destination = Path(payload["output"])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{name}.ready").write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(60)


def _dead_worker(name, payload, config):
    os._exit(9)


@pytest.mark.parametrize("reason", ["cancelled", "timeout", "memory_budget", "worker_failed"])
def test_abort_terminates_and_reaps_all_spawn_children(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(parallel, "_worker", _dead_worker if reason == "worker_failed" else _sleep_worker)
    config = {"max_workers": 2, "memory_budget_bytes": 24 * parallel.GIB, "terminate_grace_seconds": 0.0}
    cancel = None
    if reason == "timeout":
        config["timeout_seconds"] = .3
    elif reason == "cancelled":
        def cancel():
            return bool(list(tmp_path.glob("*.ready")))
    elif reason == "memory_budget":
        actual = parallel.process_memory
        monkeypatch.setattr(parallel, "process_memory", lambda pid: {"rss_bytes": 9 * parallel.GIB}
                            if pid != os.getpid() else actual(pid))
    started = time.monotonic()
    with pytest.raises(parallel.UtilityExecutionError) as raised:
        parallel.run_utility_tasks({"output": str(tmp_path)}, config, cancel)
    assert raised.value.code == reason
    assert time.monotonic() - started < 20
    assert raised.value.audit["status"] == "aborted"
    assert raised.value.audit["workers"]
    assert all(w["exitcode"] is not None for w in raised.value.audit["workers"].values())
    assert not [p for p in mp.active_children() if p.name.startswith("utility-")]


def test_unavailable_memory_fails_before_spawning(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel, "available_memory", lambda: parallel.GIB)
    with pytest.raises(parallel.UtilityExecutionError, match="even one") as raised:
        parallel.run_utility_tasks({"output": str(tmp_path)})
    assert raised.value.audit["workers"] == {}


def test_explicit_512mib_cap_propagates_and_invalidates_stale_success(case, tmp_path, monkeypatch):  # noqa: F811
    cap = 512 * 1024**2
    config = {"max_workers": 4, "memory_budget_bytes": cap, "reserve_bytes": cap // 4, "model_memory_bytes": cap * 3 // 4}
    frozen = utility.utility_protocol(execution=config)
    assert frozen["resources"]["execution"]["memory_budget_bytes"] == cap
    assert parallel.worker_capacity(config, 63 * parallel.GIB) == 1
    output = tmp_path / "small-cap"
    output.mkdir()
    (output / "utility.json").write_text('{"status":"evaluated"}', encoding="utf-8")
    monkeypatch.setattr(utility, "run_utility_tasks", parallel.run_utility_tasks)
    monkeypatch.setattr(parallel, "process_memory", lambda pid: {"rss_bytes": cap + 1})
    with pytest.raises(parallel.UtilityExecutionError) as raised:
        utility.evaluate_dataset_utility(*case, output, execution=config)
    assert raised.value.code == "memory_budget"
    assert not (output / "utility.json").exists()
    audit = json.loads((output / "execution.json").read_text(encoding="utf-8"))
    assert audit["configuration"]["memory_budget_bytes"] == cap
    assert audit["failure_code"] == "memory_budget" and audit["status"] == "aborted"
    assert file_hash(output / "protocol.json") == digest(frozen)


def test_parallel_api_resource_failure_not_converted_to_scientific_incomplete(case, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(utility, "run_utility_tasks", parallel.run_utility_tasks)
    monkeypatch.setattr(parallel, "_worker", _sleep_worker)
    # Parent assembly remains feasible; the supervisor then observes an overrun
    # in a real spawned child and must propagate after joining that child.
    actual = parallel.process_memory
    monkeypatch.setattr(parallel, "process_memory", lambda pid: {"rss_bytes": 9 * parallel.GIB}
                        if pid != os.getpid() else actual(pid))
    output = tmp_path / "resource-api"
    with pytest.raises(parallel.UtilityExecutionError) as raised:
        utility.evaluate_dataset_utility(*case, output, execution={"max_workers": 2,
            "memory_budget_bytes": 24 * parallel.GIB, "terminate_grace_seconds": 0.0})
    assert raised.value.code == "memory_budget"
    assert not (output / "utility.json").exists()
    audit = json.loads((output / "execution.json").read_text(encoding="utf-8"))
    assert audit["workers"] and all(w["exitcode"] is not None for w in audit["workers"].values())
    assert audit["failure_code"] == "memory_budget"
    assert not [p for p in mp.active_children() if p.name.startswith("utility-")]


def test_host_memory_pressure_has_distinct_resource_code(tmp_path, monkeypatch):
    readings = iter([32 * parallel.GIB, parallel.GIB])
    monkeypatch.setattr(parallel, "available_memory", lambda: next(readings))
    with pytest.raises(parallel.UtilityExecutionError) as raised:
        parallel.run_utility_tasks({"output": str(tmp_path)})
    assert raised.value.code == "memory_pressure"


def _warning_worker(name, payload, config):
    parallel._parent_guard()
    path = Path(payload["output"]) / name
    path.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        time.sleep(.05)
        warnings.warn(name)
        time.sleep(.05)
    values = np.load(payload["array"], mmap_mode="r", allow_pickle=False)
    writable = values.flags.writeable
    values._mmap.close()
    (path / "process-result.json").write_text(json.dumps({"warnings": [str(w.message) for w in caught], "writable": writable}), encoding="utf-8")
    (path / "process-execution.json").write_text("{}", encoding="utf-8")


@pytest.mark.parametrize("memory_gib,max_workers,expected", [(24, 2, 2), (16, 4, 1)])
def test_process_warning_isolation_and_readonly_arrays(tmp_path, monkeypatch, memory_gib, max_workers, expected):
    array = tmp_path / "array.npy"
    np.save(array, np.ones((2, 2, 4)))
    before = file_hash(array)
    monkeypatch.setattr(parallel, "_worker", _warning_worker)
    outcomes, audit = parallel.run_utility_tasks({"output": str(tmp_path), "array": str(array)},
        {"max_workers": max_workers, "memory_budget_bytes": memory_gib * parallel.GIB})
    assert audit["max_active_workers"] == expected
    for name, value in outcomes.items():
        assert value == {"warnings": [name], "writable": False}
    assert file_hash(array) == before


def _memory_fit_worker(name, payload, config):
    from app.search.learners import LearnerMemoryLimit
    def fail(*args, **kwargs):
        raise LearnerMemoryLimit("intentional working-array budget excess")
    utility._run_learner = fail
    parallel._worker(name, payload, config)  # Real envelope handling in this spawned process.


def test_actual_worker_memory_exception_envelope_is_resource_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel, "_worker", _memory_fit_worker)
    payload = {"output": str(tmp_path), "paths": {}, "trials": [], "panel": {}, "core": {}, "core_rows": {}, "band": [4., 40.]}
    with pytest.raises(parallel.UtilityExecutionError) as raised:
        parallel.run_utility_tasks(payload)
    assert raised.value.code == "memory_budget"
    assert "working-array budget" in str(raised.value)
    assert not [p for p in mp.active_children() if p.name.startswith("utility-")]


def test_parent_sentinel_guard_after_abrupt_supervisor_death(tmp_path):
    # The child stays in a native-style blocking call when its parent disappears.
    script = tmp_path / "parent_exit.py"
    marker = tmp_path / "child.txt"
    script.write_text('''import multiprocessing as mp, os, sys, time
from pathlib import Path
from app.search.utility_parallel import _parent_guard
def child(marker):
    _parent_guard()
    Path(marker).write_text(str(os.getpid()))
    time.sleep(60)
if __name__ == '__main__':
    p = mp.get_context('spawn').Process(target=child, args=(sys.argv[1],))
    p.start()
    deadline = time.monotonic() + 20
    while not Path(sys.argv[1]).exists():
        if time.monotonic() > deadline:
            p.terminate(); p.join(); raise RuntimeError('child did not start')
        time.sleep(.05)
    os._exit(0)
''', encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
    subprocess.run([sys.executable, str(script), str(marker)], env=env, check=True, timeout=30)
    pid = int(marker.read_text())
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and parallel.process_memory(pid)["rss_bytes"]:
        time.sleep(.05)
    assert parallel.process_memory(pid)["rss_bytes"] == 0
