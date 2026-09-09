"""Single independent worker: python -m app.preprocessing.worker --root PATH."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time

import portalocker

from .inputs import validate_input, validate_record_files
from .resources import ResourceError, budget, require_capacity
from .runner import Cancelled, run_record, verify_result
from .schemas import ExecutionPlan, Ref
from .storage import Storage, digest
from .units import environment, engine_hash

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store: Storage, allowed_roots: list[Path]):
        self.store, self.allowed_roots = store, allowed_roots

    def run_once(self):
        # The OS releases this lock on process death. Never steal a timed-out lock.
        with portalocker.Lock(self.store.root / "worker.lock", timeout=0):
            self.store.recover()
            return self._next()

    def run_forever(self):
        with portalocker.Lock(self.store.root / "worker.lock", timeout=0):
            self.store.recover()
            while True:
                if self._next() is None:
                    time.sleep(1)

    def _next(self):
        job = self.store.claim()
        if not job:
            return None
        owner, job_id = job["owner"], job["id"]
        verified_completed = set()
        retain_verified_on_resource_error = False
        try:
            plan = ExecutionPlan.model_validate(
                self.store.get(
                    owner, Ref(id=job["plan_id"], sha256=job["plan_id"]), "plan"
                )
            )
            if plan.environment != environment() or plan.engine_sha256 != engine_hash():
                raise ValueError(
                    "frozen execution environment/engine has changed; create a new plan"
                )
            root = validate_input(
                plan.input_snapshot, self.allowed_roots, self.store.root
            )
            for record in self.store.status(owner, job_id).records:
                if record["status"] != "completed":
                    continue
                if verify_result(self.store.root, record["result"]):
                    verified_completed.add(record["key"])
                else:
                    # Revoke the stale success before any resource check can fail.
                    self.store.record_finish(
                        job_id,
                        record["key"],
                        "failed",
                        error="saved artifacts failed verification; recomputation required",
                    )
            retain_verified_on_resource_error = True
            remaining = sum(
                c.estimated_disk_bytes
                for c in plan.records
                if digest([c.method_ref.id, c.record_id]) not in verified_completed
            )
            source_records = {r.id: r for r in plan.input_snapshot.collection.records}
            for index, config in enumerate(plan.records):
                key = digest([config.method_ref.id, config.record_id])
                if key in verified_completed:
                    continue
                if self.store.cancel_requested(owner, job_id):
                    self.store.record_finish(
                        job_id, key, "cancelled", error="cancelled before record"
                    )
                    remaining -= config.estimated_disk_bytes
                    continue
                resources = budget(self.store.root, plan.request)
                require_capacity("disk", remaining, resources.disk_limit_bytes)
                require_capacity(
                    "memory",
                    config.estimated_memory_bytes,
                    resources.memory_limit_bytes,
                )
                attempt = self.store.record_start(job_id, key)
                output = (
                    self.store.root / "runs" / job_id / f"r{index:04}" / f"a{attempt}"
                )
                try:
                    # Interrupted records restart from the immutable input, in a new directory.
                    result = run_record(
                        plan,
                        config,
                        root,
                        output,
                        self.store.root,
                        lambda: self.store.cancel_requested(owner, job_id),
                    )
                    validate_record_files(root, source_records[config.record_id])
                    self.store.record_finish(job_id, key, "completed", result=result)
                    # run_record verifies its artifacts before returning.
                    verified_completed.add(key)
                except ResourceError:
                    raise
                except Cancelled as exc:
                    self.store.record_finish(job_id, key, "cancelled", error=str(exc))
                except Exception as exc:
                    logger.exception(
                        "preprocessing_record_failed job=%s record=%s", job_id, key
                    )
                    self.store.record_finish(
                        job_id, key, "failed", error=f"{type(exc).__name__}: {exc}"
                    )
                finally:
                    # Failed attempts are not rerun in this pass. Their files
                    # already reduce the next live free-space measurement.
                    remaining -= config.estimated_disk_bytes
            retain_verified_on_resource_error = False
            validate_input(plan.input_snapshot, self.allowed_roots, self.store.root)
            return self.store.finish_job(owner, job_id)
        except Exception as exc:
            logger.exception("preprocessing_job_failed job=%s", job_id)
            cancelled = self.store.cancel_requested(owner, job_id)
            for record in self.store.status(owner, job_id).records:
                if record["status"] == "cancelled" or (
                    isinstance(exc, ResourceError)
                    and retain_verified_on_resource_error
                    and record["status"] == "completed"
                    and record["key"] in verified_completed
                ):
                    continue
                self.store.record_finish(
                    job_id,
                    record["key"],
                    "cancelled"
                    if cancelled and record["status"] != "completed"
                    else "failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            return self.store.finish_job(owner, job_id)


def main():
    from app.core.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root")
    parser.add_argument("--input-root", action="append")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    worker = Worker(
        Storage(args.root or settings.preprocessing_root),
        [
            Path(p)
            for p in (
                args.input_root
                or [*settings.preprocessing_input_roots, settings.workflow_root]
            )
        ],
    )
    try:
        worker.run_once() if args.once else worker.run_forever()
    except portalocker.exceptions.LockException:
        parser.exit(2, "A preprocessing worker already owns this storage root.\n")


if __name__ == "__main__":
    main()
