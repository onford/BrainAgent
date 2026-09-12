import asyncio

import portalocker
import pytest

from app.search.run_control import Controls
from app.search.service import SearchService, BudgetStop
from tests.search.test_controller import factory  # noqa: F401


def test_control_reads_are_read_only_and_generations_keep_requests(tmp_path):
    controls = Controls(tmp_path)
    assert controls.snapshot().generation == 0
    assert list(tmp_path.iterdir()) == []
    with controls.transaction() as value:
        controls.request(value, 'owner')
    original = controls.path.read_bytes()
    with controls.transaction() as value:
        controls.request(value, 'owner')
    assert controls.path.read_bytes() == original
    with controls.transaction() as value:
        controls.resume(value)
        controls.request(value, 'owner')
    value = controls.snapshot()
    assert value.generation == 1
    assert [r.generation for r in value.history] == [0, 1]
    assert value.history[0].id != value.pending.id


@pytest.mark.asyncio
async def test_other_supervisor_cancels_owner_and_retry_preserves_budget(factory):
    service, _, initial = factory()
    identity = initial['id']
    follower = SearchService(service.root, service.workflows)
    entered = asyncio.Event()

    class Slow:
        async def structured_output(self, *args):
            entered.set()
            await asyncio.sleep(30)

    service.llm = Slow()
    service.start('owner', identity)
    try:
        await asyncio.wait_for(entered.wait(), 10)
        before = service.get('owner', identity)
        pending = follower.cancel('owner', identity)
        assert pending['status'] == 'running' and pending['cancellation_requested']
        with pytest.raises(ValueError, match='执行器'):
            follower.retry('owner', identity)
        await asyncio.wait_for(service.tasks[identity], 10)
        stopped = follower.describe('owner', identity)
        assert stopped['status'] == 'cancelled' and not stopped['cancellation_requested']
        assert stopped['usage']['llm_calls'] == before['usage']['llm_calls'] == 1
        assert all(a['status'] != 'running' for a in stopped['actions'])
        follower.start = lambda *args: None
        resumed = follower.retry('owner', identity)
        assert resumed['deadline'] == before['deadline']
        assert resumed['budget'] == before['budget']
        assert resumed['usage']['llm_calls'] == 1
        assert resumed['usage']['retries'] == stopped['usage']['retries'] + 1
        controls = Controls(service.folder(identity)).snapshot()
        assert controls.generation == 1 and controls.pending is None
        assert len(controls.history) == 1
        # A stale cancellation cache in the old owner cannot cancel a new run.
        async def shutdown(state):
            raise asyncio.CancelledError()
        service._run = shutdown
        await service.run('owner', identity)
        assert service.get('owner', identity)['status'] == 'interrupted'
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_search_lock_covers_failure_publication(factory):
    service, _, initial = factory()
    identity = initial['id']
    publishing, release = asyncio.Event(), asyncio.Event()
    async def fail(state):
        raise BudgetStop('time_budget_exhausted')
    async def publish(state, *args):
        publishing.set()
        await release.wait()
    service._run, service.stop = fail, publish
    task = asyncio.create_task(service.run('owner', identity))
    try:
        await asyncio.wait_for(publishing.wait(), 10)
        with pytest.raises(portalocker.exceptions.LockException):
            with portalocker.Lock(service.folder(identity) / 'search.lock', timeout=0):
                pytest.fail('publication lost ownership')
        follower = SearchService(service.root, service.workflows)
        async def unexpected(*args):
            pytest.fail('second supervisor entered')
        follower._run = unexpected
        await follower.run('owner', identity)
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_corrupt_control_interrupts_waiting_owner_without_a_winner(factory):
    service, _, initial = factory()
    identity = initial['id']
    entered = asyncio.Event()
    async def wait(state):
        entered.set()
        await asyncio.sleep(30)
    service._run = wait
    task = asyncio.create_task(service.run('owner', identity))
    await asyncio.wait_for(entered.wait(), 10)
    Controls(service.folder(identity)).path.write_text('{} invalid', encoding='utf-8')
    await asyncio.wait_for(task, 10)
    state = service.get('owner', identity)
    assert state['status'] == 'failed' and state['stop_reason'] == 'integrity_failure'
    assert state['selected_candidate_id'] is None


def test_unauthorized_cancel_does_not_create_control_files(factory):
    service, _, initial = factory()
    root = service.folder(initial['id'])
    with pytest.raises(KeyError):
        service.cancel('other', initial['id'])
    assert not (root / 'control.json').exists()
    assert not (root / 'control.lock').exists()


@pytest.mark.asyncio
async def test_terminal_search_is_not_reexecuted_or_republished(factory):
    service, _, initial = factory(strategy='exhaustive', max_candidates=1)
    identity = initial['id']
    await service.run('owner', identity)
    root = service.folder(identity)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    await service.run('owner', identity)
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


@pytest.mark.asyncio
async def test_cancellation_during_report_publication_drains_writer(factory, monkeypatch):
    from threading import Event
    from app.search import reporting
    service, _, initial = factory()
    identity = initial['id']
    entered, release = Event(), Event()
    async def exhausted(state):
        raise BudgetStop('time_budget_exhausted')
    def render(*args):
        entered.set()
        assert release.wait(10)
    monkeypatch.setattr(reporting, 'render', render)
    service._run = exhausted
    service.start('owner', identity)
    task = service.tasks[identity]
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        service.cancel('owner', identity)
        await asyncio.sleep(.15)
        assert not task.done()
        with pytest.raises(portalocker.exceptions.LockException):
            with portalocker.Lock(service.folder(identity) / 'search.lock', timeout=0):
                pytest.fail('report writer lost ownership')
    finally:
        release.set()
        await asyncio.wait_for(task, 10)
    result = service.get('owner', identity)
    assert result['status'] == 'cancelled'
    assert result['selected_candidate_id'] is None
