import asyncio
import json

import httpx
import pytest

from app.core.exceptions import ExternalToolRateLimitError, ExternalToolUnavailableError
from app.integrations.clients.http import HttpExternalToolClient
from app.integrations.clients.github import GitHubClient
from app.integrations.clients.state import ProviderState, response_ttl
from app.integrations.definitions import TOOL_DEFINITION_BY_ID
from app.preprocessing.storage import digest


def client(
    root,
    handler,
    *,
    owner="owner",
    secret="private-test-key",
    clock=None,
    provider="semantic_scholar",
):
    cls = GitHubClient if provider == "github" else HttpExternalToolClient
    instance = cls(
        TOOL_DEFINITION_BY_ID[provider],
        {"api_key": secret},
        timeout_seconds=1,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    instance.attach_state(
        ProviderState(root, **({"clock": clock} if clock else {})), owner
    )
    return instance


@pytest.mark.asyncio
async def test_same_owner_searches_coalesce_across_instances_and_survive_restart(
    tmp_path,
):
    calls = []
    now = [1000.0]

    async def handler(request):
        calls.append(request.url)
        await asyncio.sleep(0.08)
        return httpx.Response(200, json={"data": [{"title": "actual provider result"}]})

    a, b = [client(tmp_path, handler, clock=lambda: now[0]) for _ in range(2)]
    first, second = await asyncio.gather(a.search("EEG"), b.search("EEG"))
    assert first == second and len(calls) == 1
    assert {a.last_request_metadata["cache"], b.last_request_metadata["cache"]} == {
        "hit",
        "miss",
    }
    second["data"][0]["title"] = "caller mutation"
    now[0] += 20
    resumed = client(tmp_path, handler, clock=lambda: now[0])
    assert (await resumed.search("EEG"))["data"][0]["title"] == "actual provider result"
    assert resumed.last_request_metadata["snapshot_age_seconds"] == 20
    assert resumed.last_request_metadata['transport_attempts'] == 0
    now[0] += 601
    await resumed.search("EEG")
    assert len(calls) == 2 and resumed.last_request_metadata["cache"] == "miss"
    assert all(
        "private-test-key" not in p.read_text()
        for p in tmp_path.rglob("*")
        if p.is_file()
    )


@pytest.mark.asyncio
async def test_owner_credentials_query_and_limit_are_separate_cache_identities(
    tmp_path,
):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json={"data": []})

    a = client(tmp_path, handler)
    await a.search("EEG", limit=1)
    await a.search("EEG", limit=1)
    await client(tmp_path, handler, owner="another").search("EEG", limit=1)
    await client(tmp_path, handler, secret="rotated-secret").search("EEG", limit=1)
    await a.search("ERP", limit=1)
    await a.search("EEG", limit=2)
    assert len(calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, error",
    [(429, ExternalToolRateLimitError), (503, ExternalToolUnavailableError)],
)
async def test_server_cooldown_survives_new_client_and_does_not_block_other_provider(
    tmp_path, status, error
):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status, headers={"retry-after": "120"})

    with pytest.raises(error):
        await client(tmp_path, handler).search("EEG")
    with pytest.raises(error, match="shared cooldown"):
        blocked = client(tmp_path, handler, owner="another")
        await blocked.search("different query")
    assert blocked.last_request_metadata['transport_attempts'] == 0
    assert blocked.last_request_metadata['request_outcome'] == 'shared_cooldown'
    assert len(calls) == 1
    other = client(
        tmp_path, lambda _: httpx.Response(200, json={"items": []}), provider="github"
    )
    assert await other.search_repositories("EEG") == {"items": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,payload",
    [
        ({"cache-control": "no-store"}, {"data": []}),
        ({"cache-control": "no-cache"}, {"data": []}),
        ({"vary": "*"}, {"data": []}),
        ({}, {}),
    ],
)
async def test_prohibited_or_malformed_results_are_never_cached(
    tmp_path, headers, payload
):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=payload, headers=headers)

    a = client(tmp_path, handler)
    await a.search("EEG")
    await a.search("EEG")
    assert len(calls) == 2 and not list((tmp_path / "cache").glob("*.json"))


def test_cache_size_limits_corruption_and_freshness(tmp_path):
    now = [1000.0]
    state = ProviderState(tmp_path, clock=lambda: now[0], max_entries=2, max_bytes=1000)
    for i in range(5):
        state.store(digest(i), {"title": "x" * 150}, fetched_at=1000, ttl=600)
    paths = list((tmp_path / "cache").glob("*.json"))
    assert len(paths) <= 2 and sum(p.stat().st_size for p in paths) <= 1000
    key = digest(4)
    assert state.cached(key)
    row = json.loads(state.path("cache", key).read_text())
    row["output"]["title"] = "tampered"
    state.path("cache", key).write_text(json.dumps(row))
    assert state.cached(key) is None
    state.defer(digest("provider"), 120, "rate_limit")
    state.defer(digest("provider"), 10, "rate_limit")
    assert state.cooldown(digest("provider"))["until"] == 1120
    state.path("cooldowns", digest("provider")).write_text("{}")
    with pytest.raises(ExternalToolUnavailableError, match="cannot be verified"):
        state.cooldown(digest("provider"))


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"cache-control": "max-age=600", "age": "590"}, 8),
        ({"cache-control": "no-cache, max-age=600"}, 0),
        ({"cache-control": "max-age=oops"}, 0),
        ({"cache-control": "max-age=600, max-age=900"}, 0),
        ({"age": "nan"}, 0),
        (
            {
                "expires": "Thu, 01 Jan 1970 00:16:45 GMT",
                "date": "Thu, 01 Jan 1970 00:16:40 GMT",
            },
            3,
        ),
        ({"expires": "Thu, 01 Jan 1970 00:16:39 GMT"}, 0),
    ],
)
def test_http_expiration_and_age_do_not_gain_a_new_full_ttl(headers, expected):
    assert response_ttl(httpx.Headers(headers), 1000, 2, 600) == expected


@pytest.mark.asyncio
async def test_failed_provider_attempt_metadata_reaches_workflow_journal(tmp_path):
    from app.tools.registry import ToolRegistry
    from app.workflows.cognition_contracts import ResearchAction, ResearchSources
    from tests.workflows.test_parallel_research import make_cognition
    from tests.workflows.fakes import Reader
    registry = ToolRegistry()
    async def get_client(name, context):
        return client(tmp_path/'provider-state', lambda _: httpx.Response(429, headers={'retry-after':'60'}))
    registry.get_client = get_client
    cognition = make_cognition(tmp_path/'workflow', Reader())
    cognition.tools = registry
    sources = ResearchSources(documents=[], observations=[])
    action = ResearchAction(action='search', tool='semantic_scholar', query='EEG', rationale='test recorded attempts')
    for _ in range(2):
        await cognition.research_tool(action, sources, {'semantic_scholar'})
    assert all(not row.success for row in sources.observations)
    assert [row.output['retrieval']['transport_attempts'] for row in sources.observations] == [1, 0]
    assert sources.observations[-1].output['retrieval']['request_outcome'] == 'shared_cooldown'
