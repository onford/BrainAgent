from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import ScriptedLLMClient

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_integration_api_masks_preserves_removes_and_isolates_secrets(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'integrations.db'}",
        brain_agent_credential_encryption_key=TEST_KEY,
    )
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        alice = {"X-Brain-Agent-Owner-ID": "alice"}
        bob = {"X-Brain-Agent-Owner-ID": "bob"}

        saved = client.put(
            "/api/integrations/tools/github",
            headers=alice,
            json={"enabled": True, "credentials": {"token": "top-secret-token"}},
        )
        assert saved.status_code == 200
        assert "top-secret-token" not in saved.text
        token_field = saved.json()["credential_schema"][0]
        assert token_field["configured"] is True
        assert token_field["masked_value"] == "********"
        assert token_field["value"] is None

        preserved = client.put(
            "/api/integrations/tools/github",
            headers=alice,
            json={"enabled": True, "credentials": {}},
        ).json()
        assert preserved["credential_schema"][0]["configured"] is True

        bob_view = client.get("/api/integrations/tools/github", headers=bob).json()
        assert bob_view["configured"] is False
        assert bob_view["credential_schema"][0]["configured"] is False

        removed = client.put(
            "/api/integrations/tools/github",
            headers=alice,
            json={
                "enabled": True,
                "credentials": {},
                "remove_credentials": ["token"],
            },
        ).json()
        assert removed["credential_schema"][0]["configured"] is False

        response = client.delete("/api/integrations/tools/github", headers=alice)
        assert response.status_code == 204
        assert client.get("/api/integrations/tools/github", headers=alice).json()[
            "configured"
        ] is False


def test_integrations_list_contains_all_initial_definitions(tmp_path: Path) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'definitions.db'}",
        brain_agent_credential_encryption_key=TEST_KEY,
    )
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        body = client.get("/api/integrations/tools").json()
        assert [tool["id"] for tool in body] == [
            "github",
            "semantic_scholar",
            "openalex",
            "crossref",
            "europe_pmc",
            "arxiv",
            "unpaywall",
        ]
