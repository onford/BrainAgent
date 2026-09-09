"""Real Windows-compatible spawn workers: isolation, parity and forced cleanup."""
import multiprocessing as mp
import os
from pathlib import Path
import time
import warnings

import numpy as np
import pytest

from app.preprocessing import worker as runtime
from app.preprocessing.methods import baseline_methods
from app.preprocessing.parallel import RecordProcessPool
from app.preprocessing.worker import Worker
from .conftest import OWNER
from .test_execution import prepare


def warning_probe(label):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        time.sleep(.05)
        warnings.warn(label)
        time.sleep(.05)
    return os.getpid(), [str(w.message) for w in caught]


def test_process_array_parity_and_parent_only_sqlite(service, dataset, tmp_path, monkeypatch):
    from app.preprocessing.service import PreprocessingService
    parent = os.getpid()
    original_start, original_finish = service.store.record_start, service.store.record_finish
    def start(*args, **kwargs):
        assert os.getpid() == parent
        return original_start(*args, **kwargs)
    def finish(*args, **kwargs):
        assert os.getpid() == parent
        return original_finish(*args, **kwargs)
    monkeypatch.setattr(service.store, 'record_start', start)
    monkeypatch.setattr(service.store, 'record_finish', finish)
    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    parallel = Worker(service.store, service.allowed_roots, max_record_workers=2).run_once()
    assert parallel.status == 'completed', parallel.model_dump()
    serial_service = PreprocessingService(tmp_path / 'serial', [Path(dataset.collection.root)])
    serial_job, _, _ = prepare(serial_service, dataset, [baseline_methods()[0]])
    serial = Worker(serial_service.store, serial_service.allowed_roots).run_once()
    assert serial.status == 'completed'
    serial_rows = {r['record_id']: r for r in serial.records}
    for row in parallel.records:
        execution = row['result']['parallel_execution']
        assert execution['pid'] != parent and execution['parent_pid'] == parent
        assert execution['start_method'] == 'spawn'
        a = np.load(service.store.artifact(OWNER, job.job_id, row['key'], 'signal_V.npy'))
        other = serial_rows[row['record_id']]
        b = np.load(serial_service.store.artifact(OWNER, serial_job.job_id, other['key'], 'signal_V.npy'))
        np.testing.assert_array_equal(a, b)
        assert any(f['kind'] == 'execution_log' for f in row['result']['artifacts'])


def test_process_warning_isolation_and_hard_abort(service, dataset):
    _, _, plan = prepare(service, dataset, [baseline_methods()[0]])
    pool = RecordProcessPool(plan, dataset.collection.root, service.store.root, 2)
    try:
        futures = [pool.executor.submit(warning_probe, name) for name in ('record-A', 'record-B')]
        values = [f.result(timeout=30) for f in futures]
        assert [v[1] for v in values] == [['record-A'], ['record-B']]
        pool.executor.submit(time.sleep, 60)
        processes = pool.processes()
        started = time.monotonic()
        pool.abort(grace_seconds=.1)
        assert time.monotonic() - started < 8
        assert all(not p.is_alive() for p in processes)
    finally:
        pool.abort(grace_seconds=.1)


def test_parallel_cancel_reaps_children_and_marks_queued(service, dataset, monkeypatch):
    job, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    original = runtime.RecordProcessPool
    instances = []
    class CancellingPool(original):
        def submit(self, index, output):
            future = super().submit(index, output)
            instances.append(self)
            service.store.control(OWNER, job.job_id, 'cancel')
            return future
    monkeypatch.setattr(runtime, 'RecordProcessPool', CancellingPool)
    result = Worker(service.store, service.allowed_roots, max_record_workers=2).run_once()
    assert result.status == 'cancelled'
    assert all(r['status'] == 'cancelled' for r in result.records)
    assert instances and all(p.closed for p in instances)
    assert not [p for p in mp.active_children() if p.is_alive()]


def test_runtime_memory_overrun_reaps_children(service, dataset, monkeypatch):
    _, _, _ = prepare(service, dataset, [baseline_methods()[0]])
    original = runtime.RecordProcessPool
    class OverBudgetPool(original):
        def memory(self):
            return 10**15 if self.processes() else 0
    monkeypatch.setattr(runtime, 'RecordProcessPool', OverBudgetPool)
    result = Worker(service.store, service.allowed_roots, max_record_workers=2).run_once()
    assert result.status == 'failed'
    assert all('ResourceError' in r['error'] for r in result.records)
    assert not [p for p in mp.active_children() if p.is_alive()]


def test_abrupt_process_exit_is_reaped(service, dataset):
    _, _, plan = prepare(service, dataset, [baseline_methods()[0]])
    pool = RecordProcessPool(plan, dataset.collection.root, service.store.root, 2)
    try:
        dead = pool.executor.submit(os._exit, 9)
        with pytest.raises(Exception, match='terminated abruptly'):
            dead.result(timeout=30)
        processes = pool.processes()
        pool.abort(grace_seconds=.1)
        assert all(not p.is_alive() for p in processes)
    finally:
        pool.abort(grace_seconds=.1)


def test_parent_death_guard_leaves_no_record_orphan(service, dataset, tmp_path):
    import json
    import subprocess
    import sys
    from app.preprocessing.parallel import process_memory
    _, _, plan = prepare(service, dataset, [baseline_methods()[0]])
    payload = tmp_path / 'plan.json'
    payload.write_text(plan.model_dump_json(), encoding='utf-8')
    receipt = tmp_path / 'pids.json'
    script = tmp_path / 'parent_exit.py'
    script.write_text('''import json, os, sys, time
from pathlib import Path
from app.preprocessing.parallel import RecordProcessPool
from app.preprocessing.schemas import ExecutionPlan
if __name__ == '__main__':
    plan = ExecutionPlan.model_validate_json(Path(sys.argv[1]).read_text())
    pool = RecordProcessPool(plan, sys.argv[2], sys.argv[3], 2)
    pid = pool.executor.submit(os.getpid).result(timeout=20)
    pool.executor.submit(time.sleep, 60)
    Path(sys.argv[4]).write_text(json.dumps([p.pid for p in pool.processes()]))
    os._exit(0)
''', encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
    subprocess.run([sys.executable, str(script), str(payload), dataset.collection.root,
                    str(service.store.root), str(receipt)], env=env, check=True, timeout=30)
    pids = json.loads(receipt.read_text())
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and any(process_memory(pid)['rss_bytes'] for pid in pids):
        time.sleep(.1)
    assert pids and all(process_memory(pid)['rss_bytes'] == 0 for pid in pids)
