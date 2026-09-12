"""Record interruption under the worker lock without rewriting native evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from .schemas import Contract
from .storage import file_hash, within, write_json


class NativeInterruptionObservation(Contract):
    path: str
    sha256: str
    declared_status: str | None
    read_error: str | None


class RecoveryReceipt(Contract):
    schema_version: Literal['worker-recovery-1'] = 'worker-recovery-1'
    job_id: str
    record_key: str
    attempt: int = Field(ge=1)
    recovered_at: str
    effective_status: Literal['interrupted'] = 'interrupted'
    basis: Literal['exclusive_worker_lock_reacquired'] = 'exclusive_worker_lock_reacquired'
    native_process_exit_verified: Literal[False] = False
    previous_outputs_accepted: Literal[False] = False
    native_receipts: list[NativeInterruptionObservation]


def record_interruption(root, *, job_id, record_key, attempt):
    """The caller owns the exclusive worker lock; this is not a heartbeat guess.

    Lock reacquisition proves supervisor ownership ended, not that a particular
    native PID exited. Preserve that distinction, especially on untested OSes.
    """
    root = Path(root)
    target = root / 'recovery.json'
    if target.exists():
        saved = RecoveryReceipt.model_validate_json(target.read_text(encoding='utf-8'))
        if (saved.job_id, saved.record_key, saved.attempt) != (job_id, record_key, attempt):
            raise ValueError('recovery receipt identity differs')
        return saved
    observations = []
    for path in sorted(root.glob('**/native-*/execution.json')):
        # Input snapshots are never recovery outputs.
        relative = path.relative_to(root)
        if relative.parts[0] == 'input':
            continue
        path = within(root, relative.as_posix())
        digest = file_hash(path)
        status, error = None, None
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('native receipt exceeds metadata read bound')
            value = json.loads(path.read_text(encoding='utf-8'))
            status = value.get('status')
            if not isinstance(status, str):
                raise ValueError('native receipt has no string status')
            if file_hash(path) != digest:
                raise ValueError('native receipt changed during interruption observation')
        except (ValueError, OSError, AttributeError) as exc:
            status, error = None, type(exc).__name__ + ': ' + str(exc)
        observations.append(NativeInterruptionObservation(path=relative.as_posix(), sha256=digest,
                            declared_status=status, read_error=error))
    receipt = RecoveryReceipt(job_id=job_id, record_key=record_key, attempt=attempt,
        recovered_at=datetime.now(timezone.utc).isoformat(), native_receipts=observations)
    write_json(target, receipt.model_dump(mode='json'))
    return receipt
