"""Spawn-isolated record execution; all durable job state belongs to the parent.

Python 3.12 warnings contexts and MNE logging state are process-global. A record
process therefore runs one numerical call at a time. The frozen plan is passed
once through the process initializer, never through each submitted task.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import multiprocessing as mp
import os
from pathlib import Path
import threading
import time
import traceback

_PLAN = _ROOT = _STORAGE = _CANCEL = _THREAD_LIMIT = None


class ParallelExecutionError(RuntimeError):
    """A process failed; already verified records remain valid."""


def process_memory(pid):
    """Return current/peak resident bytes; missing/exited processes return zero."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as w

        class Counters(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged",
                    "nonpaged", "pagefile", "peak_pagefile")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
        psapi.GetProcessMemoryInfo.restype = w.BOOL
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return {"rss_bytes": 0, "process_peak_rss_bytes": 0}
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ParallelExecutionError("cannot inspect record process memory")
            return {"rss_bytes": int(counters.rss), "process_peak_rss_bytes": int(counters.peak_rss)}
        finally:
            kernel.CloseHandle(handle)
    try:
        rows = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line)
        return {"rss_bytes": int(rows["VmRSS"].split()[0]) * 1024,
                "process_peak_rss_bytes": int(rows["VmHWM"].split()[0]) * 1024}
    except (FileNotFoundError, ProcessLookupError):
        return {"rss_bytes": 0, "process_peak_rss_bytes": 0}


def _parent_guard():
    # multiprocessing retains the original parent handle/sentinel on Windows,
    # so PID reuse cannot make an orphan mistake a new process for its parent.
    from multiprocessing.connection import wait
    parent = mp.parent_process()
    if parent is None:
        raise ParallelExecutionError("record process requires a spawning parent")

    def watch():
        wait([parent.sentinel])
        os._exit(72)
    threading.Thread(target=watch, name="record-parent-guard", daemon=True).start()


def initialize_record_process(plan_payload, root, storage, cancel):
    global _PLAN, _ROOT, _STORAGE, _CANCEL, _THREAD_LIMIT
    _parent_guard()
    from threadpoolctl import threadpool_limits
    import mne
    from .schemas import ExecutionPlan
    _THREAD_LIMIT = threadpool_limits(limits=1)
    mne.set_log_level("WARNING")
    _PLAN = ExecutionPlan.model_validate(plan_payload)
    _ROOT, _STORAGE, _CANCEL = Path(root), Path(storage), cancel


def execute_record(index, output):
    """Return a serializable envelope, including scientific exception details."""
    from .inputs import validate_record_files
    from .resources import ResourceError
    from .runner import Cancelled, run_record
    from .storage import file_hash, write_json

    config = _PLAN.records[index]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.parent / (output.name + "-process.log")
    started, cpu_started = time.perf_counter(), time.process_time()
    envelope = {"status": "failed", "result": None}
    with log.open("w", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
        try:
            if _CANCEL.is_set():
                raise Cancelled("cancelled before record")
            result = run_record(_PLAN, config, _ROOT, output, _STORAGE, _CANCEL.is_set)
            record = next(r for r in _PLAN.input_snapshot.collection.records if r.id == config.record_id)
            validate_record_files(_ROOT, record)
            envelope.update(status="completed", result=result)
        except BaseException as exc:
            envelope.update(status="resource_error" if isinstance(exc, ResourceError) else (
                "cancelled" if isinstance(exc, Cancelled) else "failed"),
                error=f"{type(exc).__name__}: {exc}", failure_code=getattr(exc, "code", type(exc).__name__),
                failure_details=getattr(exc, "details", {}), traceback=traceback.format_exc())
            print(envelope["traceback"], file=stream)
    execution = {"pid": os.getpid(), "parent_pid": os.getppid(), "start_method": "spawn",
                 "plan_initialization": "once_per_process", "record_index": index,
                 "record_id": config.record_id, "wall_seconds": time.perf_counter() - started,
                 "cpu_seconds": time.process_time() - cpu_started, **process_memory(os.getpid()),
                 "peak_memory_scope": "worker process lifetime; not a per-record isolated maximum"}
    envelope["execution"] = execution
    if output.exists():
        receipt = output / "process-execution.json"
        write_json(receipt, execution)
        if envelope["result"]:
            for path, kind in ((receipt, "provenance"), (log, "execution_log")):
                envelope["result"]["artifacts"].append({
                    "name": path.name, "path": path.relative_to(_STORAGE).as_posix(),
                    "kind": kind, "sha256": file_hash(path), "bytes": path.stat().st_size})
            envelope["result"]["parallel_execution"] = execution
    return envelope


class RecordProcessPool:
    """Bounded supervision and termination for the pinned Python 3.12 executor."""
    def __init__(self, plan, root, storage, workers):
        context = mp.get_context("spawn")
        self.cancel = context.Event()
        self.executor = ProcessPoolExecutor(max_workers=workers, mp_context=context,
            initializer=initialize_record_process,
            initargs=(plan.model_dump(mode="json"), str(root), str(storage), self.cancel))
        self.closed = False
        self.peak_rss_bytes = 0
        self.observed_pids = set()

    def submit(self, index, output):
        return self.executor.submit(execute_record, index, str(output))

    def processes(self):
        # Python 3.12 has no public terminate_workers API. Keep the sole private
        # access here and cover hard termination with real spawn-process tests.
        return list((self.executor._processes or {}).values())

    def memory(self):
        processes = self.processes()
        self.observed_pids.update(p.pid for p in processes if p.pid)
        rss = sum(process_memory(p.pid)["rss_bytes"] for p in processes if p.pid)
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        return rss

    def close(self):
        if not self.closed:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.closed = True

    def abort(self, grace_seconds=1.0):
        if self.closed:
            return
        self.cancel.set()
        processes = self.processes()
        self.executor.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + grace_seconds
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.terminate()
        deadline = time.monotonic() + 2
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join(2)
        self.closed = True
        if any(p.is_alive() for p in processes):
            raise ParallelExecutionError("record process could not be reaped")
