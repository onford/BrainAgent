from collections.abc import AsyncIterator
from typing import cast

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import Orchestrator
from app.agents.registry import AgentRegistry
from app.db.session import Database
from app.api.user import CurrentUser
from app.core.config import Settings
from app.integrations.registry import ExternalToolRegistry
from app.integrations.security import CredentialCipher
from app.tools.registry import ToolRegistry


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async for session in database.sessions():
        yield session


def get_orchestrator(request: Request) -> Orchestrator:
    return cast(Orchestrator, request.app.state.orchestrator)


def get_agent_registry(request: Request) -> AgentRegistry:
    return cast(AgentRegistry, request.app.state.agent_registry)


def get_current_user(
    request: Request,
    owner_id: str | None = Header(default=None, alias="X-Brain-Agent-Owner-ID"),
) -> CurrentUser:
    settings = cast(Settings, request.app.state.settings)
    resolved = (owner_id or settings.default_owner_id).strip()
    if not resolved or len(resolved) > 191:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid owner id")
    return CurrentUser(owner_id=resolved)


def get_credential_cipher(request: Request) -> CredentialCipher:
    return cast(CredentialCipher, request.app.state.credential_cipher)


def get_external_tool_registry(request: Request) -> ExternalToolRegistry:
    return cast(ExternalToolRegistry, request.app.state.external_tool_registry)


def get_tool_registry(request: Request) -> ToolRegistry:
    return cast(ToolRegistry, request.app.state.tool_registry)
