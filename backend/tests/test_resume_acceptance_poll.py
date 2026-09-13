import httpx
import pytest

from scripts.resume_workflow_acceptance import poll


@pytest.mark.asyncio
async def test_transient_file_lock_does_not_terminate_formal_monitor():
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(422, json={'detail': "[Errno 13] Permission denied: 'E:/run/search.json'"})
        return httpx.Response(200, json={'status': 'running'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='http://local') as client:
        state, errors = await poll(client, 'workflow')
    assert state['status'] == 'running' and len(errors) == 1 and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('detail', ['changed protocol', "[Errno 13] Permission denied: 'model.pt'"])
async def test_other_failures_still_stop_monitor(detail):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(422, json={'detail': detail})), base_url='http://local') as client:
        with pytest.raises(httpx.HTTPStatusError):
            await poll(client, 'workflow')


@pytest.mark.asyncio
async def test_persistent_snapshot_denial_is_bounded():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(422, json={'detail': "[Errno 13] Permission denied: 'search.json'"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='http://local') as client:
        with pytest.raises(httpx.HTTPStatusError):
            await poll(client, 'workflow', attempts=2)
    assert len(calls) == 2
