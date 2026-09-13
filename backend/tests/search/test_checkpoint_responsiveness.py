import asyncio
import threading
import time

import pytest

from app.search.service import SearchService


@pytest.mark.asyncio
async def test_checkpoint_does_not_block_api_event_loop(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    checkpoint_finished = threading.Event()

    class Process:
        returncode = 0

        def __init__(self, *args, **kwargs):
            pass

        def wait(self):
            finished.wait(3)

        def memory_bytes(self):
            return 0

        def kill(self):
            finished.set()

        def close(self):
            pass

    monkeypatch.setattr('app.search.service.ProcessTree', Process)
    service = object.__new__(SearchService)
    service.children = {}
    service.folder = lambda identity: tmp_path

    def slow_checkpoint(state):
        entered.set()
        release.wait(2)
        checkpoint_finished.set()

    service.save = slow_checkpoint
    state = {
        'id': 'run', 'deadline': time.time() + 30,
        'usage': {'peak_worker_memory_bytes': 0},
        'protocol': {'limits': {'memory_limit_bytes': 1024, 'disk_limit_bytes': 1024 * 1024}},
    }
    task = asyncio.create_task(service.child(state, 'panel'))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        # This coroutine represents another incoming API request. It must run
        # before the slow disk operation is released or times out.
        assert not task.done()
        assert not checkpoint_finished.is_set()
        assert not finished.is_set()
        started = time.monotonic()
        await asyncio.sleep(0.01)
        assert time.monotonic() - started < 1
        assert not release.is_set()
    finally:
        release.set()
        finished.set()
        await task
    assert not service.children
