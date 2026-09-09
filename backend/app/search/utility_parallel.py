"""Bounded spawn supervision. One learner owns one process and output directory.

Only small descriptors cross process boundaries; signal arrays remain read-only
memmaps. No executor shutdown waits indefinitely on a numerical native call.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import json
import multiprocessing as mp
import os
from pathlib import Path
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.preprocessing.parallel import process_memory
from app.preprocessing.resources import available_memory
from app.preprocessing.storage import file_hash, write_json

GIB = 1024**3
MODEL_ORDER = ("ea_fbcsp", "ts_lr", "fbcsp", "fgmdm", "csp_lda", "logvar_lr")


class UtilityExecution(BaseModel):
    """Explicit, machine-independent values frozen at service creation."""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    strategy: Literal["model_processes"] = "model_processes"
    start_method: Literal["spawn"] = "spawn"
    max_workers: int = Field(default=1, ge=1, le=4)
    blas_threads: Literal[1] = 1
    memory_budget_bytes: int = Field(default=16 * GIB, ge=1)
    reserve_bytes: int = Field(default=4 * GIB, ge=1)
    model_memory_bytes: int = Field(default=8 * GIB, ge=1, le=48 * GIB)
    timeout_seconds: float = Field(default=7200.0, gt=0)
    poll_seconds: float = Field(default=0.1, ge=0.01, le=1)
    terminate_grace_seconds: float = Field(default=1.0, ge=0, le=5)

    @model_validator(mode="after")
    def enough_for_one(self):
        if self.memory_budget_bytes < self.reserve_bytes + self.model_memory_bytes:
            raise ValueError("frozen memory budget must cover reserve plus one model")
        return self


def utility_execution(execution=None):
    """Normalize defaults before freezing; never infer settings from live hardware."""
    return UtilityExecution.model_validate({} if execution is None else execution).model_dump(mode="json")


class UtilityExecutionError(RuntimeError):
    def __init__(self, code, message, *, audit=None, completed=None):
        super().__init__(message)
        self.code = code
        self.audit = audit or {}
        self.completed = completed or {}


def worker_capacity(execution, available_bytes):
    config = utility_execution(execution)
    usable = min(config["memory_budget_bytes"], available_bytes) - config["reserve_bytes"]
    return max(0, min(config["max_workers"], usable // config["model_memory_bytes"]))


def check_assembly_resources(execution):
    """Parent assembly is also covered by an explicitly small memory cap."""
    config = utility_execution(execution)
    try:
        if process_memory(os.getpid())["rss_bytes"] > config["memory_budget_bytes"]:
            raise UtilityExecutionError("memory_budget", "utility parent RSS exceeds frozen memory budget during assembly")
        if available_memory() < config["reserve_bytes"]:
            raise UtilityExecutionError("memory_pressure", "host memory fell below frozen reserve during assembly")
    except UtilityExecutionError:
        raise
    except Exception as exc:
        raise UtilityExecutionError("memory_budget", f"cannot verify utility memory budget: {exc}") from exc


def _parent_guard():
    from multiprocessing.connection import wait
    parent = mp.parent_process()
    if parent is None:
        raise RuntimeError("utility worker requires a spawning parent")

    def watch():
        wait([parent.sentinel])
        os._exit(72)
    threading.Thread(target=watch, name="utility-parent-sentinel", daemon=True).start()


def _worker(name, payload, execution):
    _parent_guard()  # Guard native calls even if the supervisor is forcibly killed.
    destination = Path(payload["output"]) / name
    destination.mkdir(parents=True, exist_ok=True)
    started, cpu = time.monotonic(), time.process_time()
    with (destination / "process.log").open("w", encoding="utf-8") as stream, redirect_stdout(stream), redirect_stderr(stream):
        try:
            import mne
            from threadpoolctl import threadpool_info, threadpool_limits
            from .utility_evaluation import _run_learner
            mne.set_log_level("WARNING")
            with threadpool_limits(limits=1):
                outcome = _run_learner(name, payload["trials"], {k: Path(v) for k, v in payload["paths"].items()},
                    payload["panel"], payload["core"], payload["core_rows"], tuple(payload["band"]),
                    Path(payload["output"]), model_memory_bytes=execution["model_memory_bytes"])
                thread_pools = [{key: pool.get(key) for key in ("internal_api", "num_threads", "prefix", "version")}
                                for pool in threadpool_info()]
            execution_record = {"pid": os.getpid(), "parent_pid": os.getppid(), "start_method": "spawn", "blas_threads": 1,
                "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu,
                **process_memory(os.getpid()), "input_mode": "read-only memmap", "learner": name, "thread_pools": thread_pools}
            process_path = destination / "process-execution.json"
            write_json(process_path, execution_record)
            if outcome["metadata"]:
                metadata_path = Path(outcome["metadata"]["path"])
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["execution"] = {"path": str(process_path.resolve()), "sha256": file_hash(process_path)}
                write_json(metadata_path, metadata)
                outcome["metadata"]["sha256"] = file_hash(metadata_path)
            write_json(destination / "process-result.json", outcome)
        except BaseException as exc:
            import traceback
            traceback.print_exc()
            write_json(destination / "process-error.json", {"type": type(exc).__name__, "error": str(exc),
                       "failure_code": "memory_budget" if isinstance(exc, MemoryError) else "worker_failed"})
            raise


def _reap(processes, grace):
    """Bounded cooperative wait, terminate, kill; always join every child."""
    deadline = time.monotonic() + grace
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
    if any(process.is_alive() for process in processes):
        raise UtilityExecutionError("unreaped_worker", "utility child could not be reaped")


def run_utility_tasks(payload, execution=None, cancel_check=None):
    """Return all learner outcomes plus supervision audit; abort never returns scores.

    A single worker is still a supervised spawn process. Live memory may reduce
    concurrency, never change models, grids, folds or trial coverage. RSS is a
    sampled safety bound (shared mapped pages counted conservatively per process),
    not an OS allocation quota. The enclosing Windows Job supplies tree teardown.
    """
    config = utility_execution(execution)
    context = mp.get_context("spawn")
    started = time.monotonic()
    completed, active, launched = {}, {}, []
    audit = {"configuration": config, "status": "running", "workers": {}, "peak_worker_rss_sum_bytes": 0,
             "peak_parent_plus_workers_rss_bytes": 0, "max_active_workers": 0, "memory_poll_seconds": config["poll_seconds"]}
    pending = list(MODEL_ORDER)
    try:
        initial_available = available_memory()
        capacity = worker_capacity(config, initial_available)
        audit.update(initial_available_bytes=initial_available, effective_max_workers=capacity)
        if capacity < 1:
            raise UtilityExecutionError("memory_budget", "insufficient available memory for even one utility model")
        while pending or active:
            if cancel_check and cancel_check():
                raise UtilityExecutionError("cancelled", "utility cancelled by supervisor")
            if time.monotonic() - started > config["timeout_seconds"]:
                raise UtilityExecutionError("timeout", "utility model-suite wall-clock budget exceeded")
            rss = {name: process_memory(process.pid)["rss_bytes"] for name, process in active.items()}
            worker_rss = sum(rss.values())
            parent_rss = process_memory(os.getpid())["rss_bytes"]
            audit["peak_worker_rss_sum_bytes"] = max(audit["peak_worker_rss_sum_bytes"], worker_rss)
            audit["peak_parent_plus_workers_rss_bytes"] = max(audit["peak_parent_plus_workers_rss_bytes"], worker_rss + parent_rss)
            if any(value > config["model_memory_bytes"] for value in rss.values()) or worker_rss + parent_rss > config["memory_budget_bytes"]:
                raise UtilityExecutionError("memory_budget", "utility worker or parent-plus-workers RSS exceeds frozen budget")
            free = available_memory()
            if free < config["reserve_bytes"]:
                raise UtilityExecutionError("memory_pressure", "host available memory fell below frozen reserve")
            for name, process in list(active.items()):
                if process.is_alive():
                    continue
                process.join()
                audit["workers"][name]["exitcode"] = process.exitcode
                if process.exitcode != 0:
                    error_path = Path(payload["output"]) / name / "process-error.json"
                    detail = json.loads(error_path.read_text(encoding="utf-8")) if error_path.exists() else {}
                    code = "memory_budget" if detail.get("failure_code") == "memory_budget" else "worker_failed"
                    raise UtilityExecutionError(code, f"{name} process exited {process.exitcode}: {detail.get('error', 'inspect process.log')}")
                destination = Path(payload["output"]) / name
                completed[name] = json.loads((destination / "process-result.json").read_text(encoding="utf-8"))
                audit["workers"][name]["execution"] = json.loads((destination / "process-execution.json").read_text(encoding="utf-8"))
                del active[name]
            rss = {name: value for name, value in rss.items() if name in active}
            worker_rss = sum(rss.values())
            free = available_memory()
            # Reserve unused portions of active model slots, including workers
            # still importing, so simultaneous starts cannot overcommit memory.
            unconsumed = sum(max(0, config["model_memory_bytes"] - rss.get(name, 0)) for name in active)
            headroom = min(free - config["reserve_bytes"], config["memory_budget_bytes"] - max(parent_rss, config["reserve_bytes"]) - worker_rss) - unconsumed
            while pending and len(active) < capacity and headroom >= config["model_memory_bytes"]:
                name = pending.pop(0)
                # Never consume a stale envelope if a rerun dies during startup.
                for filename in ("process-result.json", "process-error.json", "process-execution.json"):
                    (Path(payload["output"]) / name / filename).unlink(missing_ok=True)
                process = context.Process(target=_worker, args=(name, payload, config), name=f"utility-{name}")
                process.start()
                launched.append(process)
                active[name] = process
                audit["workers"][name] = {"pid": process.pid, "exitcode": None}
                headroom -= config["model_memory_bytes"]
            audit["max_active_workers"] = max(audit["max_active_workers"], len(active))
            if pending and not active:
                raise UtilityExecutionError("memory_budget", "no model slot fits current host and frozen parent memory budget")
            if active:
                time.sleep(config["poll_seconds"])
        audit["status"] = "completed"
        return completed, audit
    except BaseException as exc:
        audit.update(status="aborted", error=f"{type(exc).__name__}: {exc}")
        if isinstance(exc, UtilityExecutionError):
            exc.audit, exc.completed = audit, completed
            raise
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        # Probe failures must not be mistaken for scientific learner failure.
        from app.preprocessing.resources import ResourceError
        code = "memory_budget" if isinstance(exc, (ResourceError, MemoryError)) else "worker_failed"
        raise UtilityExecutionError(code, str(exc), audit=audit, completed=completed) from exc
    finally:
        _reap(launched, config["terminate_grace_seconds"] if active else 0)
        audit["wall_seconds"] = time.monotonic() - started
        for name, process in active.items():
            audit["workers"][name]["exitcode"] = process.exitcode
        for process in launched:
            process.close()
