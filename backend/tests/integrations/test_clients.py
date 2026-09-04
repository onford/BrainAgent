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


def test_arxiv_multi_word_query_is_treated_as_a_phrase() -> None:
    assert HttpExternalToolClient._arxiv_query("EEG dataset") == 'all:"EEG dataset"'


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
