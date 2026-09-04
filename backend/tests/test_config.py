import pytest

from app.core.config import Settings
from app.core.exceptions import CredentialConfigurationError, LLMConfigurationError
from app.main import create_app


def test_app_fails_fast_without_llm_api_key() -> None:
    settings = Settings(llm_api_key=None)
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY is not configured"):
        create_app(settings)


def test_app_fails_fast_without_credential_encryption_key() -> None:
    settings = Settings(llm_api_key="test-key", brain_agent_credential_encryption_key=None)
    with pytest.raises(
        CredentialConfigurationError,
        match="BRAIN_AGENT_CREDENTIAL_ENCRYPTION_KEY is not configured",
    ):
        create_app(settings)
