import asyncio
from threading import Event
from types import SimpleNamespace

import portalocker
import pytest

from app.preprocessing.storage import Storage
from app.workflows.schemas import WorkflowRequest
from app.workflows.service import WorkflowService, _owned_thread


@pytest.mark.asyncio
async def test_workflow_ownership_survives_cancel_until_writer_exits(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    preprocessing = SimpleNamespace(allowed_roots=[source], store=Storage(tmp_path / 'store'))
    owner = WorkflowService(tmp_path / 'workflows', [source], preprocessing)
    follower = WorkflowService(owner.root, [source], preprocessing)
    state = owner.create('owner', WorkflowRequest(source_root=str(source)), start=False)
    entered, release, cancelled = Event(), Event(), Event()
    output = owner.folder(state['id']) / 'writer-proof.txt'
    def writer():
        entered.set()
        assert release.wait(10)
        output.write_text('finished', encoding='utf-8')
    async def stage(*args):
        await _owned_thread(writer, on_cancel=cancelled.set)
    owner.registry = SimpleNamespace(get=lambda name: SimpleNamespace(run=stage))
    follower.registry = SimpleNamespace(get=lambda name: pytest.fail('duplicate stage'))
    owner.start('owner', state['id'])
    task = owner.tasks[state['id']]
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        await follower.run('owner', state['id'])
        task.cancel()
        assert await asyncio.to_thread(cancelled.wait, 10)
        task.cancel()  # repeated shutdown must still drain the same thread
        await asyncio.sleep(.01)
        assert not task.done()
        with pytest.raises(portalocker.exceptions.LockException):
            with portalocker.Lock(owner.folder(state['id']) / 'workflow.lock', timeout=0):
                pytest.fail('live writer lost ownership')
        with pytest.raises(ValueError, match='执行器'):
            follower.retry('owner', state['id'])
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert output.read_text(encoding='utf-8') == 'finished'
    assert owner.get('owner', state['id'])['status'] == 'interrupted'
    with portalocker.Lock(owner.folder(state['id']) / 'workflow.lock', timeout=0):
        pass
