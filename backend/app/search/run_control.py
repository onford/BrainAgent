"""Durable cancellation generations shared by all supervisors of one search."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator
from app.preprocessing.schemas import Contract
from app.preprocessing.storage import write_json


class CancellationRequest(Contract):
    id: str
    generation: int = Field(ge=0)
    owner: str
    requested_at: str


class RunControl(Contract):
    schema_version: Literal['run-control-1'] = 'run-control-1'
    generation: int = Field(default=0, ge=0)
    pending: CancellationRequest | None = None
    history: list[CancellationRequest] = Field(default_factory=list)

    @model_validator(mode='after')
    def pending_is_current(self):
        if self.pending is not None and (self.pending.generation != self.generation or self.pending not in self.history):
            raise ValueError('pending cancellation must belong to the current recorded generation')
        return self


class Controls:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'control.json'

    @contextmanager
    def transaction(self):
        import portalocker
        with portalocker.Lock(self.root / 'control.lock', timeout=5):
            value = self.snapshot()
            before = value.model_dump(mode='json')
            yield value
            after = RunControl.model_validate(value.model_dump(mode='json')).model_dump(mode='json')
            if after != before:
                write_json(self.path, after)

    def snapshot(self):
        # Atomic replacement permits read-only polling, including old records.
        try:
            with self.path.open('rb') as stream:
                body = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            return RunControl()
        if len(body) > 1024 * 1024:
            raise ValueError('search control metadata exceeds read bound')
        return RunControl.model_validate_json(body)

    @staticmethod
    def request(value, owner):
        if value.pending is None:
            request = CancellationRequest(id=uuid4().hex, generation=value.generation, owner=owner,
                                          requested_at=datetime.now(timezone.utc).isoformat())
            value.pending = request
            value.history.append(request)

    @staticmethod
    def resume(value):
        value.generation += 1
        value.pending = None
