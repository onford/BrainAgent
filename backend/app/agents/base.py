from abc import ABC, abstractmethod

from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult


class BaseAgent(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        raise NotImplementedError
