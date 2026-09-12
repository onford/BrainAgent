import httpx
import pytest

from app.core.exceptions import (
    ExternalToolRateLimitError,
    ExternalToolUnavailableError,
    ToolCredentialInvalidError,
)
from app.integrations.clients.http import HttpExternalToolClient
from app.integrations.definitions import TOOL_DEFINITION_BY_ID


def client_for(handler) -> HttpExternalToolClient:
    return HttpExternalToolClient(
        TOOL_DEFINITION_BY_ID["semantic_scholar"],
        {"api_key": "never-log-this"},
        timeout_seconds=0.1,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("EEG motor imagery", "all:EEG AND all:motor AND all:imagery"),
        ('EEG "motor imagery"', 'all:EEG AND all:"motor imagery"'),
        (
            "ti:EEG AND (abs:imagery OR abs:movement)",
            "ti:EEG AND (abs:imagery OR abs:movement)",
        ),
        ('"EEG dataset"', 'all:"EEG dataset"'),
    ],
)
def test_arxiv_preserves_query_intent(query, expected) -> None:
    assert HttpExternalToolClient._arxiv_query(query) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "   ", None])
async def test_empty_query_does_not_make_an_upstream_request(query):
    def handler(request):
        pytest.fail("invalid search must not reach provider")

    with pytest.raises(ValueError, match="non-empty"):
        await client_for(handler).search(query)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "path", "parameter"),
    [
        ("semantic_scholar", "/graph/v1/paper/search", "query"),
        ("europe_pmc", "/europepmc/webservices/rest/search", "query"),
        ("arxiv", "/api/query", "search_query"),
    ],
)
async def test_search_preserves_base_path_and_requests_readable_metadata(
    provider, path, parameter
):
    def handler(request):
        assert request.url.path == path
        assert parameter in request.url.params
        if provider == "europe_pmc":
            assert request.url.params["resultType"] == "core"
        if provider == "semantic_scholar":
            assert "abstract" in request.url.params["fields"]
        return httpx.Response(200, json={})

    client = HttpExternalToolClient(
        TOOL_DEFINITION_BY_ID[provider],
        {},
        timeout_seconds=1,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    await client.search("EEG motor imagery")


@pytest.mark.asyncio
async def test_validation_accepts_200_and_sends_expected_auth_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "never-log-this"
        return httpx.Response(200, json={"data": []})

    await client_for(handler).validate_connection()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_validation_normalizes_rejected_credentials(status_code: int) -> None:
    client = client_for(lambda _: httpx.Response(status_code))
    with pytest.raises(ToolCredentialInvalidError, match="rejected"):
        await client.validate_connection()


@pytest.mark.asyncio
async def test_validation_normalizes_rate_limit() -> None:
    client = client_for(lambda _: httpx.Response(429))
    with pytest.raises(ExternalToolRateLimitError):
        await client.validate_connection()


@pytest.mark.asyncio
async def test_validation_normalizes_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ExternalToolUnavailableError):
        await client_for(handler).validate_connection()
