import pytest

from app.agents.base import BaseAgent
from app.agents import build_agent_registry
from app.agents.registry import AgentRegistry
from app.core.exceptions import AgentNotFoundError
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult


class ExampleAgent(BaseAgent):
    name = "example"
    description = "test"

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        return AgentResult(agent_name=self.name, success=True)


def test_register_and_get_agent() -> None:
    registry = AgentRegistry()
    agent = ExampleAgent()
    registry.register(agent)
    assert registry.get("example") is agent


def test_unknown_agent_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        AgentRegistry().get("missing")


def test_default_registry_contains_six_domain_agents() -> None:
    names = {agent.name for agent in build_agent_registry().list()}
    assert names == {
        "data_survey",
        "data_collection",
        "data_preprocessing",
        "data_evaluation",
        "data_report",
        "data_delivery",
    }
