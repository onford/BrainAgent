"""Atomic, conservative request budgets shared by a workflow and its searches.

These are operational limits, not a prediction of billed cost. Every transport
attempt consumes a reservation, including failures and interrupted requests.
The output reservation is never refunded from an incomplete usage response.
"""
import json
from pathlib import Path
from time import time
from uuid import uuid4

import portalocker

from app.preprocessing.storage import write_json

DEFAULT_LIMITS = dict(max_requests=128, max_input_bytes=16_000_000,
    max_input_bytes_per_request=750_000, max_output_tokens_per_request=32768,
    max_reserved_output_tokens=4_194_304, max_seconds=21600)


class BudgetExceeded(RuntimeError):
    pass


class CallBudget:
    def __init__(self, path, limits=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock():
            if not self.path.exists():
                limits = dict(DEFAULT_LIMITS if limits is None else limits)
                if set(limits) != set(DEFAULT_LIMITS) or any(type(v) is not int or v <= 0 for v in limits.values()):
                    raise ValueError('LLM budget requires positive integer limits')
                write_json(self.path, dict(schema_version='1', limits=limits,
                    started_at=time(), expires_at=time()+limits['max_seconds'], attempts=[]))
            elif limits is not None and self.read()['limits'] != limits:
                raise ValueError('LLM budget limits changed; use a new workflow')

    def lock(self):
        return portalocker.Lock(self.path.with_suffix('.lock'), timeout=5)

    def read(self):
        return json.loads(self.path.read_text(encoding='utf8'))

    @property
    def output_limit(self):
        return self.read()['limits']['max_output_tokens_per_request']

    def reserve(self, input_bytes, call_id, operation):
        with self.lock():
            data = self.read()
            limits, rows = data['limits'], data['attempts']
            reason = None
            if time() >= data['expires_at']:
                reason = 'absolute time limit'
            elif input_bytes > limits['max_input_bytes_per_request']:
                reason = 'single request input bytes; split the source/context before retrying'
            elif len(rows) >= limits['max_requests']:
                reason = 'request attempt limit'
            elif sum(r['input_bytes'] for r in rows) + input_bytes > limits['max_input_bytes']:
                reason = 'cumulative input bytes'
            elif sum(r['reserved_output_tokens'] for r in rows) + self.output_limit > limits['max_reserved_output_tokens']:
                reason = 'cumulative reserved output tokens'
            if reason:
                raise BudgetExceeded('Persistent LLM budget exhausted: '+reason)
            ticket = dict(id=uuid4().hex, call_id=call_id, operation=operation,
                input_bytes=input_bytes, reserved_output_tokens=self.output_limit,
                reserved_at=time(), status='reserved', usage=None)
            rows.append(ticket)
            write_json(self.path, data)
            return ticket['id'], max(0, data['expires_at']-time())

    def complete(self, identity, **values):
        with self.lock():
            data = self.read()
            row = next(r for r in data['attempts'] if r['id'] == identity)
            if row['status'] != 'reserved':
                raise ValueError('LLM attempt already completed')
            row.update(values, completed_at=time())
            write_json(self.path, data)
