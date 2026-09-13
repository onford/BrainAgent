"""Serialize an intake across API instances and verify its immutable result."""
import asyncio
from contextlib import asynccontextmanager
from time import monotonic

import portalocker

from .schemas import Ref
from .storage import digest, write_json
from app.search.io import read


def build_identity():
    from app.build_info import execution_identity, runtime_snapshot
    return execution_identity(runtime_snapshot())


@asynccontextmanager
async def intake_lock(root, timeout=900):
    root.mkdir(parents=True, exist_ok=True)
    lock = portalocker.Lock(root / 'intake.lock', timeout=0,
                            flags=portalocker.LOCK_EX | portalocker.LOCK_NB)
    deadline = monotonic() + timeout
    while True:
        try:
            lock.acquire()
            break
        except portalocker.exceptions.LockException:
            if monotonic() >= deadline:
                raise ValueError('Identical literature intake is still running; retry the same bundle')
            await asyncio.sleep(.05)
    try:
        yield
    finally:
        lock.release()


def bind(root, bundle, build):
    identity = dict(version='1', bundle_sha256=digest(bundle.model_dump(mode='json')),
                    execution_build=build)
    path = root / 'intake-identity.json'
    if path.exists():
        if read(path) != identity:
            raise ValueError('Literature intake build or inputs changed; use a new survey run')
    else:
        if (root / 'budget.json').exists() or (root / 'result.json').exists():
            raise ValueError('Legacy literature intake has no build binding; use a new survey run')
        write_json(path, identity)
    return identity


def completed(store, owner, bundle, root, identity):
    path = root / 'completed-intake.json'
    if not path.exists():
        return None
    saved = read(path)
    if saved.get('identity') != identity:
        raise ValueError('Completed literature intake identity differs')
    value = store.get(owner, Ref.model_validate(saved['result_ref']), 'literature_intake_result')
    if value.get('identity') != identity:
        raise ValueError('Immutable literature intake result belongs to another intake')
    # Verify both the immutable result and every object to which it points.
    if bundle.input_ref:
        store.get(owner, bundle.input_ref, 'input')
    for paper in bundle.papers:
        if paper.fulltext_ref:
            store.get(owner, paper.fulltext_ref, 'evidence')
    refs = [Ref.model_validate(ref) for ref in value['methods']]
    for ref in refs:
        store.get(owner, ref, 'method')
    if value['supplement_requests']:
        raise ValueError('Incomplete literature intake cannot be a completed result')
    return dict(methods=refs, supplement_requests=[])


def finish(store, owner, root, identity, result):
    # Missing evidence/configuration may be supplied later. Never freeze those
    # responses as successful completion or replenish the original budget.
    if result['supplement_requests']:
        return
    value = dict(identity=identity, methods=[ref.model_dump(mode='json') for ref in result['methods']],
                 supplement_requests=[])
    ref = store.put(owner, 'literature_intake_result', value)
    write_json(root / 'completed-intake.json', dict(identity=identity, result_ref=ref.model_dump(mode='json')))
