"""Crash-safe action reservations and an absolute shared research deadline."""
from time import time, monotonic
from pathlib import Path
from .storage import digest, write_json
import json
import portalocker


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only the short read/reserve/write transaction holds this lock, never a
    # model/network await. Concurrent API requests cannot reserve the same slot.
    return portalocker.Lock(path.with_suffix(path.suffix + '.lock'), timeout=5)


def open_budget(path, limits, identity):
    path = Path(path)
    key = digest([limits, identity])
    with _lock(path):
        if path.exists():
            saved = _read(path)
            if saved['identity'] != key:
                raise ValueError('research budget inputs changed; a new run is required')
        else:
            saved = dict(identity=key, started_at=time(), expires_at=time()+limits['max_seconds'],
                         max_actions=limits['max_recovery_actions'], used=0, actions=[])
            write_json(path, saved)
    return {**saved, 'path': path, 'deadline': monotonic()+max(0, saved['expires_at']-time())}


def reserve(budget, detail):
    if budget.get('path'):
        path=Path(budget['path'])
        with _lock(path):
            saved=_read(path)
            if saved['identity']!=budget['identity']:
                raise ValueError('research budget identity changed')
            budget.update(saved)
            if time()>=saved['expires_at']:
                raise TimeoutError('shared method research budget exhausted')
            _reserve(budget, detail)
            write_json(path, {k: v for k, v in budget.items() if k not in ('path', 'deadline')})
        return
    _reserve(budget, detail)


def _reserve(budget, detail):
    if budget['used'] >= budget['max_actions'] or monotonic() >= budget['deadline']:
        raise TimeoutError('shared method research budget exhausted')
    budget['used'] += 1
    budget.setdefault('actions', []).append(dict(sequence=budget['used'], reserved_at=time(), **detail))
