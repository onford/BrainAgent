from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.registry import AgentRegistry
from app.api.deps import get_agent_registry
from app.schemas.agent import AgentInfo
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
async def list_agents(
    registry: Annotated[AgentRegistry, Depends(get_agent_registry)],
) -> list[AgentInfo]:
    return AgentService(registry).list_agents()
