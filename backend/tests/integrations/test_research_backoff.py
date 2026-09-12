import httpx
import pytest

from app.core.exceptions import ExternalToolRateLimitError, ExternalToolUnavailableError
from app.integrations.clients.http import HttpExternalToolClient
from app.integrations.clients.github import GitHubClient
from app.integrations.definitions import TOOL_DEFINITION_BY_ID


def client(handler, provider='github'):
    cls = GitHubClient if provider == 'github' else HttpExternalToolClient
    return cls(TOOL_DEFINITION_BY_ID[provider], {},
        timeout_seconds=30, max_retries=2, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,body', [
    ({'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '9999999999'}, {}),
    ({'Retry-After': '120'}, {}),
    ({}, {'message': 'You have exceeded a secondary rate limit.'}),
    ({'x-ratelimit-remaining': '0', 'x-ratelimit-reset': 'NaN'}, {}),
])
async def test_github_rate_limit_is_not_a_credential_failure_or_early_retry(headers, body):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(403, headers=headers, json=body)
    with pytest.raises(ExternalToolRateLimitError, match='not resent'):
        await client(handler).search('EEG')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_short_rate_limit_wait_is_observed_before_retry(monkeypatch):
    import app.integrations.clients.http as module
    waits, calls = [], []
    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After': '7'}) if len(calls) == 1 else httpx.Response(200, json={'items': []})
    assert await client(handler).search('EEG') == {'items': []}
    assert waits == [7] and len(calls) == 2


@pytest.mark.asyncio
async def test_server_unavailable_with_long_cooldown_returns_without_retry():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, headers={'Retry-After': '3600'})
    with pytest.raises(ExternalToolUnavailableError, match='not resent'):
        await client(handler, 'crossref').search('EEG')
    assert len(calls) == 1
