from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import Orchestrator
from app.agents.registry import AgentRegistry
from app.db.session import Database


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database = cast(Database, request.app.state.database)
    async for session in database.sessions():
        yield session


def get_orchestrator(request: Request) -> Orchestrator:
    return cast(Orchestrator, request.app.state.orchestrator)


def get_agent_registry(request: Request) -> AgentRegistry:
    return cast(AgentRegistry, request.app.state.agent_registry)
