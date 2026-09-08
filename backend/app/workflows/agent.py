from app.agents.base import BaseAgent
from app.runtime.result import AgentResult


class WorkflowAgent(BaseAgent):
    def __init__(self, workflow=None):
        self.workflow = workflow

    async def run(self, task, context):
        if self.workflow and task.inputs.get("action") == "workflow_stage":
            return await self.workflow.execute_stage(
                self.name, context.owner_id, task.inputs["workflow_id"]
            )
        return AgentResult(
            agent_name=self.name,
            success=True,
            output={"status": "needs_input", "missing_fields": ["workflow_id"]},
            observations=["请通过完整数据流程提供该模块的上游结果。"],
        )
