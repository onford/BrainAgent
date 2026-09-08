import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import CredentialConfigurationError, LLMConfigurationError
from app.main import create_app


def test_app_fails_fast_without_llm_api_key() -> None:
    settings = Settings(llm_api_key=None)
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY is not configured"):
        create_app(settings)


def test_app_fails_fast_without_credential_encryption_key() -> None:
    settings = Settings(
        llm_api_key="test-key", brain_agent_credential_encryption_key=None
    )
    with pytest.raises(
        CredentialConfigurationError,
        match="BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY is not configured",
    ):
        create_app(settings)


@pytest.mark.asyncio
async def test_configured_llm_timeout_reaches_http_request(monkeypatch, tmp_path):
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://llm.example.test/v1",
        llm_timeout_seconds=240,
        brain_agent_credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        preprocessing_root=str(tmp_path / "output"),
    )
    app = create_app(settings)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    llm = app.state.agent_registry.get("planner").llm
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(respond))
    assert await llm.chat([{"role": "user", "content": "extract a method"}]) == "{}"
    assert requests[0].extensions["timeout"]["read"] == 240
    assert requests[0].extensions["timeout"]["connect"] == 10


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), 601])
def test_invalid_llm_timeout_is_rejected(value):
    with pytest.raises(ValidationError):
        Settings(llm_timeout_seconds=value)


@pytest.mark.asyncio
async def test_workflow_reasoning_setting_is_separate_from_chat(monkeypatch, tmp_path):
    import json

    settings = Settings(
        llm_api_key="test",
        llm_base_url="https://api.deepseek.com",
        workflow_reasoning_effort="low",
        brain_agent_credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        preprocessing_root=str(tmp_path / "prep"),
    )
    app = create_app(settings)
    assert app.state.agent_registry.get("planner").llm.config.reasoning_effort is None
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(
        app.state.workflows.llm, "_transport", httpx.MockTransport(respond)
    )
    await app.state.workflows.llm.chat([{"role": "user", "content": "JSON decision"}])
    assert requests[0]["reasoning_effort"] == "low"
