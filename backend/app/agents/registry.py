from collections.abc import Iterable

from app.agents.base import BaseAgent
from app.core.exceptions import AgentNotFoundError


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' is already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentNotFoundError(f"Unknown agent: {name}") from exc

    def list(self) -> Iterable[BaseAgent]:
        return tuple(self._agents.values())
