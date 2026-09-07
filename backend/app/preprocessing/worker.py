"""Single independent worker: python -m app.preprocessing.worker --root PATH."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time
import shutil

import portalocker

from .inputs import validate_input
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
            if shutil.disk_usage(self.store.root).free < plan.estimated_disk_bytes:
                raise ValueError(
                    "free disk space is below the conservative run estimate"
                )
            for index, config in enumerate(plan.records):
                status = self.store.status(owner, job_id)
                key = digest([config.method_ref.id, config.record_id])
                previous = next(r for r in status.records if r["key"] == key)
                if previous["status"] == "completed" and verify_result(
                    self.store.root, previous["result"]
                ):
                    continue
                if status.cancel_requested:
                    self.store.record_finish(
                        job_id, key, "cancelled", error="cancelled before record"
                    )
                    continue
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
                        lambda: self.store.status(owner, job_id).cancel_requested,
                    )
                    validate_input(
                        plan.input_snapshot, self.allowed_roots, self.store.root
                    )
                    self.store.record_finish(job_id, key, "completed", result=result)
                except Cancelled as exc:
                    self.store.record_finish(job_id, key, "cancelled", error=str(exc))
                except Exception as exc:
                    logger.exception(
                        "preprocessing_record_failed job=%s record=%s", job_id, key
                    )
                    self.store.record_finish(
                        job_id, key, "failed", error=f"{type(exc).__name__}: {exc}"
                    )
            return self.store.finish_job(owner, job_id)
        except Exception as exc:
            logger.exception("preprocessing_job_failed job=%s", job_id)
            for record in self.store.status(owner, job_id).records:
                if record["status"] != "completed":
                    self.store.record_finish(
                        job_id,
                        record["key"],
                        "failed",
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
        [Path(p) for p in (args.input_root or settings.preprocessing_input_roots)],
    )
    try:
        worker.run_once() if args.once else worker.run_forever()
    except portalocker.exceptions.LockException:
        parser.exit(2, "A preprocessing worker already owns this storage root.\n")


if __name__ == "__main__":
    main()
