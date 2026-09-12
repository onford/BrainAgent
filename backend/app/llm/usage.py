"""Per-call durable accounting. Unknown billed usage/cost remains unknown."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
from time import time
from urllib.parse import urlsplit
from uuid import uuid4

import portalocker

from app.preprocessing.storage import write_json

_SCOPE = ContextVar("llm_usage_scope", default=None)
_CALL = ContextVar("llm_usage_call", default=None)
_BUDGET = ContextVar("llm_call_budget", default=None)


@contextmanager
def usage_scope(path, operation, *, budget_path=None):
    from .budget import CallBudget
    budget = CallBudget(budget_path or Path(path).with_name('llm-budget.json'))
    token = _SCOPE.set((Path(path), operation))
    budget_token = _BUDGET.set(budget)
    try:
        yield
    finally:
        _SCOPE.reset(token)
        _BUDGET.reset(budget_token)


def output_limit():
    budget = _BUDGET.get()
    return budget.output_limit if budget else None


def reserve_attempt(input_bytes):
    budget, call, scope = _BUDGET.get(), _CALL.get(), _SCOPE.get()
    return budget.reserve(input_bytes, call[1], scope[1]) if budget else (None, None)


def complete_attempt(identity, **values):
    if identity is not None:
        _BUDGET.get().complete(identity, **values)


def _change(path, identity, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(path.with_suffix(".lock"), timeout=5):
        data = json.loads(path.read_text(encoding="utf8")) if path.exists() else dict(schema_version="1", calls=[])
        row = next((r for r in data["calls"] if r["id"] == identity), None)
        if row is None:
            row = dict(id=identity)
            data["calls"].append(row)
        row.update(values)
        write_json(path, data)


def record(**values):
    call = _CALL.get()
    if call is not None:
        _change(*call, values)


@contextmanager
def metered_call(config, messages):
    scope = _SCOPE.get()
    if scope is None:
        yield
        return
    path, operation = scope
    identity = uuid4().hex
    started = time()
    location = urlsplit(config.base_url)
    _change(path, identity, dict(operation=operation, model=config.model,
        provider=location.hostname, started_at=started, status="reserved", attempts=0,
        input_characters=sum(len(m.get("content", "")) for m in messages),
        usage=None, monetary_cost=None, cost_status="no_configured_price_schedule"))
    token = _CALL.set((path, identity))
    try:
        yield
        record(status="completed", completed_at=time(), wall_seconds=time()-started)
    except BaseException as exc:
        record(status="failed", error_type=type(exc).__name__, completed_at=time(), wall_seconds=time()-started)
        raise
    finally:
        _CALL.reset(token)
