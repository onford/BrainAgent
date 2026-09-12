import asyncio
from types import SimpleNamespace

import pytest

from app.workflows.recovery_reads import read_source
from tests.workflows.fakes import Reader


@pytest.mark.asyncio
async def test_completed_supplement_survives_restart(tmp_path):
    calls = []

    async def read(url, kind):
        calls.append(url)
        return await Reader().read(url, kind)

    first = await read_source(SimpleNamespace(read=read), 'https://example.org/paper', 'paper', tmp_path)
    second = await read_source(SimpleNamespace(read=read), first.url, 'paper', tmp_path)
    assert first == second
    assert calls == [first.url]


@pytest.mark.asyncio
async def test_known_failed_read_can_be_explicitly_retried(tmp_path):
    calls = []

    async def read(url, kind):
        calls.append(url)
        if len(calls) == 1:
            raise OSError('temporary unavailable')
        return await Reader().read(url, kind)

    reader = SimpleNamespace(read=read)
    with pytest.raises(OSError):
        await read_source(reader, 'https://example.org/paper', 'paper', tmp_path)
    document = await read_source(reader, 'https://example.org/paper', 'paper', tmp_path)
    assert await read_source(reader, document.url, 'paper', tmp_path) == document
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unknown_request_remains_unknown_across_multiple_restarts(tmp_path):
    calls = []

    async def read(url, kind):
        calls.append(url)
        raise asyncio.CancelledError()

    reader = SimpleNamespace(read=read)
    with pytest.raises(asyncio.CancelledError):
        await read_source(reader, 'https://example.org/paper', 'paper', tmp_path)
    for _ in range(3):
        with pytest.raises(ValueError, match='outcome unknown'):
            await read_source(reader, 'https://example.org/paper', 'paper', tmp_path)
    assert len(calls) == 1
