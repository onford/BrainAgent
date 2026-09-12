"""Bounded numerical subprocess: python -m app.search.worker --root PATH --stage ... ."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time

import portalocker

from app.file_publish import replace_file
from app.preprocessing.inputs import validate_input
from app.preprocessing.methods import check_mapping
from app.preprocessing.resources import MIB, ResourceError, require_capacity
from app.preprocessing.runner import verify_result
from app.preprocessing.schemas import (
    ExecutionPlan,
    MethodSpec,
    PlanRequest,
    PreprocessInput,
    Ref,
    RunResult,
)
from app.preprocessing.service import PreprocessingService
from app.preprocessing.storage import Storage, digest, file_hash, within
from app.preprocessing.units import engine_hash, environment
from app.preprocessing.worker import Worker

from .catalog import (
    BASELINE_ID,
    entries_at,
    method as catalog_method,
    search_engine_hash,
)
from .evaluation import EVALUATOR_VERSION
from .evaluation_contracts import EvaluationReceipt
from .io import directory_bytes
from .panel import DataUnevaluable, freeze_panel, validate_panel

OWNER = "offline-search"
WORKER_VERSION = 2
RETRYABLE = {"failed", "partial", "interrupted", "cancelled"}


def _start_parent_guard(parent_pid: int) -> threading.Thread:
    """Exit with the supervisor; the Windows handle pins its process identity."""
    if parent_pid <= 0:
        raise ValueError("parent PID must be positive")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        # SYNCHRONIZE is sufficient; retain this handle instead of reopening
        # the PID, which may be assigned to another process after parent exit.
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)
        if not handle:
            os._exit(1)

        def watch():
            try:
                while kernel.WaitForSingleObject(handle, 1000) == 0x00000102:
                    pass  # WAIT_TIMEOUT: the original parent remains alive.
                os._exit(1)  # Signaled, or monitoring failed: do not orphan work.
            finally:
                kernel.CloseHandle(handle)

    else:

        def watch():
            while True:
                try:
                    os.kill(parent_pid, 0)
                except ProcessLookupError:
                    os._exit(1)
                except PermissionError:
                    pass  # The process exists, even without signal permission.
                except OSError:
                    os._exit(1)
                time.sleep(1)

    thread = threading.Thread(target=watch, name="search-parent-guard", daemon=True)
    thread.start()
    return thread


class CandidateInvalid(ValueError):
    """The candidate cannot compile for every frozen panel record."""


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_receipt(value) -> dict:
    return EvaluationReceipt.model_validate(value).model_dump(mode="json")


def _check_catalog_method(
    spec: MethodSpec, candidate_id: str, panel: dict, root: Path
) -> None:
    entry = entries_at(root).get(candidate_id)
    protocol = read_json(root / "protocol.json")
    if entry is None or spec.model_dump(mode="json") != catalog_method(
        entry, panel, protocol["space"], protocol.get("space_context")
    ).model_dump(mode="json"):
        raise CandidateInvalid(
            f"{candidate_id}: method differs from the frozen catalog recipe"
        )


def write_json(path: Path, value) -> None:
    """Publish readable JSON with a single replace; never expose a partial file."""
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def failure_status(exc: Exception) -> str:
    from .utility_parallel import UtilityExecutionError

    if isinstance(exc, UtilityExecutionError):
        return "resource_failure" if exc.code in {"memory_budget", "memory_pressure", "timeout"} else "execution_failure"
    if isinstance(exc, (ResourceError, MemoryError)) or (
        isinstance(exc, OSError)
        and (
            exc.errno in {errno.ENOSPC, errno.ENOMEM, errno.EDQUOT}
            or getattr(exc, "winerror", None) in {112, 1455}
        )
    ):
        return "resource_failure"
    if isinstance(exc, CandidateInvalid):
        return "candidate_invalid"
    if isinstance(exc, DataUnevaluable):
        return "data_unevaluable"
    return "execution_failure"


def _input(root: Path):
    data = PreprocessInput.model_validate(read_json(root / "input.json"))
    allowed = [Path(data.collection.root).resolve()]
    # Check the whole search root, not merely engine/: neither tree may contain
    # the other, and unselected BIDS inventory is still immutable input.
    validate_input(data, allowed, root)
    return data, allowed


def prepare(root: Path) -> dict:
    root = Path(root).resolve()
    try:
        data, _ = _input(root)
        request = read_json(root / "panel-request.json")
        # SearchRequest represents automatic splitting as two empty lists.
        if request.get("train_subjects") == request.get("development_subjects") == []:
            request = {**request, "train_subjects": None, "development_subjects": None}
        panel = freeze_panel(data, **request)
        protocol_path = root / "protocol.json"
        protocol = read_json(protocol_path) if protocol_path.exists() else {}
        assessment = protocol.get("assessment") or {}
        if protocol.get("utility_version") == 2 or assessment.get("version") == 2:
            if any(len(fold["train_subjects"]) < 2 for fold in panel["folds"]):
                raise DataUnevaluable(
                    "EEGNet 每个外折至少需要两名训练被试，用于独立的拟合与早停验证；"
                    "请增加被试或调整训练/开发划分。"
                )
        write_json(root / "panel.json", panel)
        if assessment:
            from .reconstruction_evaluation import freeze_probe_panel

            design = assessment["reconstruction_design"]
            write_json(root / "probe-panel.json", freeze_probe_panel(panel, design=design))
        (root / "prepare-error.json").unlink(missing_ok=True)
        return panel
    except Exception as exc:
        receipt = {
            "status": "data_unevaluable"
            if isinstance(exc, DataUnevaluable)
            else "execution_failure",
            "error": f"{type(exc).__name__}: {exc}",
        }
        write_json(root / "prepare-error.json", receipt)
        return receipt


def _limits(root: Path, limits: dict) -> tuple[int, int]:
    memory, disk = limits["memory_limit_bytes"], limits["disk_limit_bytes"]
    if any(type(v) is not int or v < 0 for v in (memory, disk)):
        raise ValueError("frozen resource limits must be nonnegative integer bytes")
    used = directory_bytes(root)
    remaining = disk - used
    require_capacity("disk", 64 * MIB, remaining)
    require_capacity("memory", 64 * MIB, memory)
    return memory // MIB, remaining // MIB


def _check_plan(plan, data, method_ref):
    if plan.engine_sha256 != engine_hash() or plan.environment != environment():
        raise RuntimeError(
            "frozen execution environment/engine has changed; refusing to replan"
        )
    if plan.input_snapshot != data:
        raise RuntimeError("saved plan input differs from the frozen panel input")
    request = plan.request
    if (
        request.methods != [method_ref]
        or request.mode != "exploratory"
        or request.max_candidates != 1
        or request.selection != "all"
    ):
        raise RuntimeError("saved plan does not belong to this candidate")
    expected = {(method_ref.id, r) for r in data.collection.selected_record_ids}
    actual = [(r.method_ref.id, r.record_id) for r in plan.records]
    if len(actual) != len(expected) or set(actual) != expected:
        reasons = "; ".join(reason for s in plan.screening for reason in s.reasons)
        raise CandidateInvalid("plan must cover every panel record: " + reasons)


def _check_result(result, plan):
    expected = {(r.method_ref.id, r.record_id) for r in plan.records}
    actual = [(r["method_id"], r["record_id"]) for r in result.records]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError("job records differ from this candidate's frozen plan")


def _failed_result(result):
    errors = [
        str(r.get("error") or r["status"])
        for r in result.records
        if r["status"] != "completed"
    ]
    message = "; ".join(errors) or f"preprocessing job is {result.status}"
    # Worker serializes exception types into record errors instead of raising.
    resource_markers = (
        "ResourceError:",
        "MemoryError:",
        "_ArrayMemoryError:",
        "[Errno 28]",
        "[Errno 12]",
        f"[Errno {errno.EDQUOT}]",
        "[WinError 112]",
        "[WinError 1455]",
    )
    if any(marker in error for error in errors for marker in resource_markers):
        raise ResourceError(message)
    raise RuntimeError(message)


class _VerificationStorage(Storage):
    """Reuse object/job decoding without initializing or updating the engine DB."""

    def __init__(self, root: Path, db_path: Path):
        self.root = root
        self.db_path = db_path

    @classmethod
    @contextmanager
    def snapshot(cls, root: Path):
        # SQLite's mode=ro may still create WAL/SHM files. Open a temporary
        # metadata snapshot instead, retaining any committed, uncheckpointed
        # WAL. Signal artifacts are verified in place and never copied.
        with tempfile.TemporaryDirectory(
            prefix=".verify-", dir=root.parent
        ) as directory:
            db_path = Path(directory) / "preprocessing.db"
            for suffix in ("", "-wal"):
                source = root / ("preprocessing.db" + suffix)
                if suffix and not source.exists():
                    continue
                target = db_path.with_name(db_path.name + suffix)
                shutil.copyfile(source, target)
                if file_hash(target) != file_hash(source):
                    raise RuntimeError(
                        "engine database changed during verification snapshot"
                    )
            yield cls(root, db_path)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()


def _verify_candidate(root, store, entry, data, panel):
    identity = entry["id"]
    entries = entries_at(root)
    if identity not in entries:
        raise RuntimeError("cached candidate is not in the catalog")
    output = within(root, f"candidates/{identity}")
    policy = entries[identity]
    if read_json(output / "policy.json") != policy:
        raise RuntimeError(f"{identity}: policy differs from frozen catalog")
    receipt = _normalize_receipt(read_json(output / "receipt.json"))
    if digest(receipt) != digest(_normalize_receipt(entry["receipt"])):
        raise RuntimeError(f"{identity}: receipt differs from search.json snapshot")
    if (
        receipt["status"] != "evaluated"
        or receipt["error"] is not None
        or receipt["candidate_id"] != identity
    ):
        raise RuntimeError(f"{identity}: cached receipt is not an evaluated candidate")
    if (
        receipt["panel_hash"] != panel["panel_hash"]
        or receipt["evaluator_version"] != EVALUATOR_VERSION
    ):
        raise RuntimeError(
            f"{identity}: receipt belongs to a different panel/evaluator"
        )
    predictions = within(root, f"candidates/{identity}/originalpredictions.tsv")
    if (
        Path(receipt["predictions_path"]).resolve() != predictions
        or file_hash(predictions) != receipt["predictions_sha256"]
    ):
        raise RuntimeError(f"{identity}: prediction path/checksum differs from receipt")
    representation = receipt.get("representation")
    if representation:
        if set(representation["records"]) != set(panel["records"]):
            raise RuntimeError(f"{identity}: representation record coverage differs")
        for record in representation["records"].values():
            path = Path(record["array_path"]).resolve()
            if (
                not path.is_relative_to(root)
                or file_hash(path) != record["array_sha256"]
            ):
                raise RuntimeError(f"{identity}: representation array checksum differs")

    method = MethodSpec.model_validate(read_json(output / "method.json"))
    _check_catalog_method(method, identity, panel, root)
    from .source_evidence import source_objects
    for source_id, value in source_objects(root, method).items():
        if store.get(OWNER, Ref(id=source_id, sha256=source_id), "evidence") != value:
            raise RuntimeError(f"{identity}: engine source evidence differs")
    # Mirror register_method's deterministic mapping checks without registering.
    method.checks = sorted(set(method.checks + check_mapping(method)))
    method_hash = digest(method.model_dump(mode="json"))
    method_ref = Ref(id=method_hash, sha256=method_hash)
    if store.get(OWNER, method_ref, "method") != method.model_dump(mode="json"):
        raise RuntimeError(f"{identity}: method differs from the engine snapshot")
    plan_value = read_json(output / "plan.json")
    plan = ExecutionPlan.model_validate(plan_value)
    plan_ref = Ref.model_validate(receipt["plan_ref"])
    if (
        digest(plan_value) != plan_ref.sha256
        or store.get(OWNER, plan_ref, "plan") != plan_value
    ):
        raise RuntimeError(f"{identity}: plan differs from the receipt/engine snapshot")
    _check_plan(plan, data, method_ref)
    input_hash = digest(data.model_dump(mode="json"))
    if plan.request.input_ref != Ref(id=input_hash, sha256=input_hash):
        raise RuntimeError(
            f"{identity}: plan input reference differs from frozen input"
        )
    if store.get(OWNER, plan.request.input_ref, "input") != data.model_dump(
        mode="json"
    ):
        raise RuntimeError(f"{identity}: engine input differs from frozen input")
    versions = receipt["versions"]
    for key, expected in {
        "method_hash": method_hash,
        "input_hash": input_hash,
        "panel_hash": panel["panel_hash"],
        "engine_sha256": plan.engine_sha256,
        "environment_sha256": digest(plan.environment),
    }.items():
        if versions[key] != expected:
            raise RuntimeError(
                f"{identity}: receipt {key} differs from frozen execution"
            )

    result_value = read_json(output / "result.json")
    result = RunResult.model_validate(result_value)
    if receipt.get("operator_usage") is not None:
        from .operator_usage import OperatorUsageReport

        usage = receipt["operator_usage"]
        usage_path = within(output, usage["artifact"]["path"])
        if file_hash(usage_path) != usage["artifact"]["sha256"] or usage_path.stat().st_size != usage["artifact"]["bytes"]:
            raise RuntimeError(f"{identity}: operator application artifact differs")
        native_usage = OperatorUsageReport.model_validate(read_json(usage_path))
        if native_usage.summary.model_dump(mode="json") != usage["summary"] or native_usage.plan_sha256 != digest(plan_value) or native_usage.result_sha256 != digest(result_value):
            raise RuntimeError(f"{identity}: operator application bindings differ")
    if read_json(root / "protocol.json").get("assessment"):
        from .assessment import verify_assessment
        from .reconstruction_evaluation import freeze_probe_panel

        if receipt.get("assessment") is None or not receipt.get("assessment_path") or not receipt.get("core_receipt_path"):
            raise RuntimeError(f"{identity}: required multi-axis assessment missing")
        if receipt.get("operator_usage") is None:
            raise RuntimeError(f"{identity}: required operator application record missing")
        assessed = verify_assessment(
            within(output, receipt["assessment_path"]), receipt["assessment"],
            panel_hash=panel["panel_hash"], candidate_id=identity,
        )
        probe = read_json(root / "probe-panel.json")
        protocol = read_json(root / "protocol.json")
        if assessed["utility"]["receipt_artifact"] is not None:
            native_utility_protocol = read_json(
                within(output, receipt["assessment_path"]) / "utility" / "protocol.json"
            )
            if native_utility_protocol != protocol["utility_protocol"]:
                raise RuntimeError(f"{identity}: assessment utility protocol differs from frozen search")
        if probe != freeze_probe_panel(panel, design=protocol["assessment"]["reconstruction_design"]):
            raise RuntimeError("frozen reconstruction design differs")
        for key, expected in {
            "candidate_hash": digest(policy), "plan_hash": digest(plan_value),
            "result_hash": digest(result_value), "input_hash": panel["input_hash"],
            "core_receipt_hash": digest(read_json(within(output, receipt["core_receipt_path"]))),
            "probe_panel_hash": digest(probe),
        }.items():
            if assessed["bindings"][key] != expected:
                raise RuntimeError(f"{identity}: assessment {key} binding differs")
    if (
        result.job_id != receipt["job_id"]
        or result.plan_ref != plan_ref
        or (entry.get("job_id") is not None and entry["job_id"] != result.job_id)
        or (
            entry.get("plan_ref") is not None
            and entry["plan_ref"] != plan_ref.model_dump()
        )
    ):
        raise RuntimeError(
            f"{identity}: result identity differs from the receipt/state"
        )
    execution = read_json(output / "execution.json")
    if (
        execution["job_id"] != result.job_id
        or execution["plan_ref"] != plan_ref.model_dump()
        or execution["status"] != "completed"
    ):
        raise RuntimeError(
            f"{identity}: execution snapshot differs from completed result"
        )
    if digest(store.status(OWNER, result.job_id).model_dump(mode="json")) != digest(
        result_value
    ):
        raise RuntimeError(f"{identity}: result differs from the engine job snapshot")
    _check_result(result, plan)
    if (
        result.status != "completed"
        or result.cancel_requested
        or result.completed != result.total
        or result.total != len(plan.records)
        or any(record["status"] != "completed" for record in result.records)
    ):
        raise RuntimeError(f"{identity}: cached preprocessing result is incomplete")
    for record in result.records:
        if not verify_result(store.root, record["result"]):
            raise RuntimeError(
                f"{identity}: completed artifact verification failed for {record['record_id']}"
            )


def verify(root: Path) -> dict:
    """Validate cached evaluations without executing, fitting, or repairing them."""
    root = Path(root).resolve()
    verification = {
        "status": "execution_failure",
        "error": None,
        "verified_candidate_ids": [],
    }
    try:
        data, _ = _input(root)
        panel_path = root / "panel.json"
        panel = read_json(panel_path)
        validate_panel(panel)
        if panel["input_hash"] != digest(data.model_dump(mode="json")) or set(
            panel["records"]
        ) != set(data.collection.selected_record_ids):
            raise RuntimeError("panel differs from the frozen input")
        # Only this stage reads the parent's ledger; no stage writes it.
        state = read_json(root / "search.json")
        summary = state["panel"]
        if (
            summary["file_sha256"] != file_hash(panel_path)
            or summary["panel_hash"] != panel["panel_hash"]
        ):
            raise RuntimeError("panel file/hash differs from search.json snapshot")
        expected_summary = {
            **{k: v for k, v in panel.items() if k != "trials"},
            "file_sha256": file_hash(panel_path),
            "trial_count": len(panel["trials"]),
            "eligible_count": sum(t["eligible"] for t in panel["trials"]),
        }
        if any(
            key not in expected_summary
            or digest(value) != digest(expected_summary[key])
            for key, value in summary.items()
        ):
            raise RuntimeError("panel summary differs from the frozen panel")
        engine_root = root / "engine"
        if engine_root.resolve() != engine_root:
            raise RuntimeError("private engine root must not be redirected")
        seen = set()
        evaluated = []
        for entry in state["candidates"]:
            if entry["id"] in seen:
                raise RuntimeError("duplicate candidates in search.json")
            seen.add(entry["id"])
            if entry["status"] == "evaluated":
                evaluated.append(entry)
        if evaluated:
            with _VerificationStorage.snapshot(engine_root) as store:
                for entry in evaluated:
                    _verify_candidate(root, store, entry, data, panel)
                    verification["verified_candidate_ids"].append(entry["id"])
        verification["status"] = "verified"
    except Exception as exc:
        verification["error"] = f"{type(exc).__name__}: {exc}"
    write_json(root / "verification.json", verification)
    return verification


def candidate(root: Path, candidate_id: str) -> dict:
    root = Path(root).resolve()
    # Never turn a malformed ID into a filesystem write outside candidates/.
    entries = entries_at(root)
    if candidate_id not in entries:
        raise CandidateInvalid("unknown catalog candidate")
    output = within(root, f"candidates/{candidate_id}")
    started = time.perf_counter()
    preprocessing_seconds = evaluation_seconds = 0.0
    evaluation_started = None
    job_id = plan_ref = plan = service = None
    versions = {"worker_version": WORKER_VERSION}
    receipt = None
    operator_usage = None
    try:
        data, allowed = _input(root)
        panel = read_json(root / "panel.json")
        validate_panel(panel)
        if panel["input_hash"] != digest(data.model_dump(mode="json")):
            raise RuntimeError("panel input hash differs from input.json")
        if set(data.collection.selected_record_ids) != set(panel["records"]):
            raise RuntimeError("panel records differ from the frozen input selection")
        # Selection order participates in input_hash. freeze_panel sorts its
        # record mapping, but registration must retain the original list order.
        # Keep collection.records and every record.files inventory intact.
        engine_root = root / "engine"
        if engine_root.resolve() != engine_root:
            raise RuntimeError("private engine root must not be redirected")
        service = PreprocessingService(engine_root, allowed)
        limits = read_json(root / "limits.json")
        try:
            policy = entries[candidate_id]
            if read_json(output / "policy.json") != policy:
                raise CandidateInvalid(
                    "policy differs from the frozen candidate catalog"
                )
            method = MethodSpec.model_validate(read_json(output / "method.json"))
            _check_catalog_method(method, candidate_id, panel, root)
            from .source_evidence import import_evidence
            import_evidence(root, method, service.store, OWNER)
            method_ref = service.register_method(OWNER, method)
        except ValueError as exc:
            raise CandidateInvalid(str(exc)) from exc
        versions.update(
            search_engine_sha256=search_engine_hash(),
            engine_sha256=engine_hash(),
            environment_sha256=digest(environment()),
            panel_hash=panel["panel_hash"],
            input_hash=panel["input_hash"],
            method_hash=method_ref.sha256,
        )
        execution_path, plan_path = output / "execution.json", output / "plan.json"
        if execution_path.exists():
            execution = read_json(execution_path)
            job_id = execution["job_id"]
            plan_ref = Ref.model_validate(execution["plan_ref"])
            plan = ExecutionPlan.model_validate(
                service.store.get(OWNER, plan_ref, "plan")
            )
            if plan_path.exists() and read_json(plan_path) != plan.model_dump(
                mode="json"
            ):
                raise RuntimeError(
                    "saved plan.json differs from the immutable execution plan"
                )
        elif plan_path.exists():
            # Also recover a kill between plan publication, submit, and execution
            # publication. Never create another plan with newly measured budgets.
            saved = read_json(plan_path)
            identity = digest(saved)
            plan_ref = Ref(id=identity, sha256=identity)
            plan = ExecutionPlan.model_validate(
                service.store.get(OWNER, plan_ref, "plan")
            )
        else:
            input_ref = service.register_input(OWNER, data)
            memory_mb, disk_mb = _limits(root, limits)
            plan_ref, plan = service.plan(
                OWNER,
                PlanRequest(
                    input_ref=input_ref,
                    methods=[method_ref],
                    mode="exploratory",
                    max_candidates=1,
                    selection="all",
                    max_memory_mb=memory_mb,
                    max_disk_mb=disk_mb,
                ),
            )
            write_json(plan_path, plan.model_dump(mode="json"))
        _check_plan(plan, data, method_ref)
        validate_input(plan.input_snapshot, allowed, engine_root)
        write_json(plan_path, plan.model_dump(mode="json"))
        if job_id is None:
            result = service.submit(OWNER, plan_ref)
            job_id = result.job_id
        else:
            result = service.store.status(OWNER, job_id)
        if result.plan_ref != plan_ref:
            raise RuntimeError("execution job does not refer to the saved plan")
        _check_result(result, plan)
        write_json(
            execution_path,
            {
                "job_id": job_id,
                "plan_ref": plan_ref.model_dump(),
                "status": result.status,
            },
        )
        if result.status != "completed":
            memory_mb, disk_mb = _limits(root, limits)
            pending = {
                r["record_id"]
                for r in result.records
                if r["status"] != "completed"
                or not verify_result(engine_root, r["result"])
            }
            require_capacity(
                "disk",
                sum(
                    r.estimated_disk_bytes
                    for r in plan.records
                    if r.record_id in pending
                ),
                disk_mb * MIB,
            )
            require_capacity(
                "memory",
                max(
                    (
                        r.estimated_memory_bytes
                        for r in plan.records
                        if r.record_id in pending
                    ),
                    default=0,
                ),
                memory_mb * MIB,
            )
            # Only acquiring the OS lock proves that a 'running' job was killed.
            with portalocker.Lock(engine_root / "worker.lock", timeout=0):
                service.store.recover()
                result = service.store.status(OWNER, job_id)
                if result.status in RETRYABLE:
                    result = service.store.control(OWNER, job_id, "retry")
                with service.store.db() as db:
                    other = db.execute(
                        "SELECT id FROM jobs WHERE status IN ('queued','interrupted') AND cancel=0 AND id!=?",
                        (job_id,),
                    ).fetchone()
                if other:
                    raise RuntimeError(
                        "another candidate has unfinished work in the private engine"
                    )
            concurrency = read_json(root / "protocol.json").get("record_workers", 1)
            result = Worker(
                service.store, allowed, max_record_workers=concurrency
            ).run_once()
            if result is None or result.job_id != job_id or result.plan_ref != plan_ref:
                raise RuntimeError("Worker did not execute the selected candidate job")
        write_json(
            execution_path,
            {
                "job_id": job_id,
                "plan_ref": plan_ref.model_dump(),
                "status": result.status,
            },
        )
        write_json(output / "result.json", result.model_dump(mode="json"))
        _check_result(result, plan)
        if read_json(root / "protocol.json").get("assessment"):
            from .operator_usage import aggregate_operator_usage

            usage_report = aggregate_operator_usage(plan, result, engine_root)
            usage_attempt = 1
            while (output / "operator-usage" / f"u{usage_attempt}.json").exists():
                usage_attempt += 1
            usage_path = output / "operator-usage" / f"u{usage_attempt}.json"
            write_json(usage_path, usage_report)
            operator_usage = {"summary": usage_report["summary"], "artifact": {
                "path": usage_path.relative_to(output).as_posix(),
                "sha256": file_hash(usage_path), "bytes": usage_path.stat().st_size,
            }}
        if (
            result.status != "completed"
            or result.cancel_requested
            or result.completed != result.total
            or any(r["status"] != "completed" for r in result.records)
        ):
            _failed_result(result)
        validate_input(plan.input_snapshot, allowed, root)
        if not all(verify_result(engine_root, r["result"]) for r in result.records):
            raise RuntimeError("completed job artifacts failed verification")
        preprocessing_seconds = time.perf_counter() - started
        evaluation_started = time.perf_counter()
        from .evaluation import evaluate

        baseline_path = root / "candidates" / BASELINE_ID / "receipt.json"
        baseline = read_json(baseline_path) if candidate_id != BASELINE_ID else None
        receipt = evaluate(
            result,
            plan,
            engine_root,
            panel,
            output,
            baseline=baseline,
            policy=policy["parameters"],
        )
        if not isinstance(receipt, dict) or not isinstance(receipt.get("status"), str):
            raise RuntimeError("evaluator did not return a status receipt")
        receipt = dict(receipt)
        protocol = read_json(root / "protocol.json")
        if receipt["status"] == "evaluated" and protocol.get("assessment"):
            from .assessment import assess_candidate
            from .reconstruction_evaluation import freeze_probe_panel
            from .utility_evaluation import utility_protocol

            if protocol["utility_protocol"] != utility_protocol(execution=protocol.get("utility_execution")):
                raise RuntimeError("utility model protocol or dependency versions changed")
            probe = read_json(root / "probe-panel.json")
            if probe != freeze_probe_panel(panel, design=protocol["assessment"]["reconstruction_design"]):
                raise RuntimeError("reconstruction panel differs from frozen design")
            attempts = output / "assessment"
            attempt_number = 1
            while (attempts / f"a{attempt_number}").exists() or (
                output / "core-receipts" / f"a{attempt_number}.json"
            ).exists():
                attempt_number += 1
            assessment_path = f"assessment/a{attempt_number}"
            core_path = f"core-receipts/a{attempt_number}.json"
            write_json(output / core_path, receipt)
            assessment = assess_candidate(
                plan, result, engine_root, panel, policy, receipt,
                output / assessment_path, probe,
                utility_execution=protocol.get("utility_execution"),
            )
            receipt.update(assessment=assessment, assessment_path=assessment_path, core_receipt_path=core_path)
        receipt["error"] = (
            None
            if receipt["status"] == "evaluated"
            else str(
                receipt.get("error") or receipt.get("error_code") or receipt["status"]
            )
        )
    except Exception as exc:
        receipt = {
            "status": failure_status(exc),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        now = time.perf_counter()
        if evaluation_started is None:
            preprocessing_seconds = now - started
        else:
            evaluation_seconds = now - evaluation_started
    receipt.update(
        candidate_id=candidate_id,
        operator_usage=operator_usage,
        job_id=job_id,
        plan_ref=plan_ref.model_dump() if plan_ref is not None else None,
        preprocessing_seconds=preprocessing_seconds,
        evaluation_seconds=evaluation_seconds,
        timings={
            **receipt.get("timings", {}),
            "preprocessing_seconds": preprocessing_seconds,
            "evaluation_seconds": evaluation_seconds,
            "total_seconds": now - started,
        },
        versions=versions,
    )
    try:
        receipt = _normalize_receipt(receipt)
    except ValueError as exc:
        receipt = _normalize_receipt(
            {
                "status": "execution_failure",
                "error": f"invalid worker receipt: {exc}",
                "candidate_id": candidate_id,
                "preprocessing_seconds": preprocessing_seconds,
                "evaluation_seconds": evaluation_seconds,
                "versions": {"worker_version": WORKER_VERSION},
            }
        )
    write_json(output / "receipt.json", receipt)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--stage", choices=("prepare", "candidate", "verify"), required=True
    )
    parser.add_argument("--candidate")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    if args.stage == "candidate" and args.candidate is None:
        parser.error("--candidate is required for the candidate stage")
    if args.parent_pid is not None:
        if args.parent_pid <= 0:
            parser.error("--parent-pid must be positive")
        _start_parent_guard(args.parent_pid)
    if args.stage == "verify":
        return 0 if verify(args.root)["status"] == "verified" else 1
    receipt = (
        prepare(args.root)
        if args.stage == "prepare"
        else candidate(args.root, args.candidate)
    )
    return (
        0
        if (
            "panel_hash" in receipt
            if args.stage == "prepare"
            else receipt["status"] == "evaluated"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
