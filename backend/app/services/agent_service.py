from app.agents.registry import AgentRegistry
from app.schemas.agent import AgentInfo


class AgentService:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry

    def list_agents(self) -> list[AgentInfo]:
        return [
            AgentInfo(name=agent.name, description=agent.description)
            for agent in self.registry.list()
        ]
