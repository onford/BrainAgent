from pathlib import Path

import pytest

from app.core.exceptions import (
    ToolCredentialInvalidError,
    ToolDisabledError,
    ToolNotConfiguredError,
)
from app.db.session import Database
from app.integrations.credentials import CredentialService
from app.integrations.registry import ExternalToolRegistry, ToolAvailabilityStatus
from app.integrations.security import CredentialCipher
from app.runtime.context import AgentContext
from app.schemas.integration import ToolIntegrationUpdate

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def context(owner_id: str) -> AgentContext:
    return AgentContext(
        owner_id=owner_id,
        session_id="session",
        user_message="search papers",
    )


@pytest.mark.asyncio
async def test_registry_enforces_owner_state_and_never_exposes_credentials(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    await database.create_tables()
    cipher = CredentialCipher(TEST_KEY)
    registry = ExternalToolRegistry(database, cipher)
    async with database.session_factory() as db:
        service = CredentialService(db, cipher)
        await service.save(
            "alice",
            "unpaywall",
            ToolIntegrationUpdate(credentials={"email": "alice@example.org"}),
        )

    client = await registry.get_client("unpaywall", context("alice"))
    assert "alice@example.org" not in repr(client)
    with pytest.raises(ToolNotConfiguredError):
        await registry.get_client("unpaywall", context("bob"))

    async with database.session_factory() as db:
        await CredentialService(db, cipher).save(
            "alice",
            "unpaywall",
            ToolIntegrationUpdate(
                enabled=False, credentials={"email": "alice@example.org"}
            ),
        )
    with pytest.raises(ToolDisabledError):
        await registry.get_client("unpaywall", context("alice"))
    await database.dispose()


@pytest.mark.asyncio
async def test_registry_reports_invalid_and_free_tool_availability(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'availability.db'}")
    await database.create_tables()
    cipher = CredentialCipher(TEST_KEY)
    registry = ExternalToolRegistry(database, cipher)
    async with database.session_factory() as db:
        service = CredentialService(db, cipher)
        await service.save("alice", "github", ToolIntegrationUpdate(credentials={"token": "x"}))
        await service.set_validation(
            "alice",
            "github",
            validation_status="invalid",
            safe_error="Credentials were rejected",
        )

    invalid = await registry.is_available("github", context("alice"))
    free = await registry.is_available("arxiv", context("alice"))
    assert invalid.status == ToolAvailabilityStatus.INVALID
    assert free.status == ToolAvailabilityStatus.AVAILABLE
    with pytest.raises(ToolCredentialInvalidError):
        await registry.get_client("github", context("alice"))
    await database.dispose()
