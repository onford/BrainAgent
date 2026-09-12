from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import ScriptedLLMClient


def test_build_identity_is_public_stable_and_contains_no_settings(tmp_path):
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'build.db'}",
        log_dir=tmp_path / "logs",
        llm_api_key="private-test-value",
        brain_agent_credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        response = client.get("/api/build-info")
        assert response.status_code == 200
        body = response.json()
        assert len(body["source_sha256"]) == 64
        assert body["core_evaluator_version"] == 4
        assert body["preprocessing_scope"] == "shared_recipe_all_records"
        assert client.get("/api/build-info").json() == body
        assert "private-test-value" not in response.text
        assert "database_url" not in response.text
