import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataDeliveryAgent(BaseAgent):
    name = "data_delivery"
    description = "Packages selected derivatives and a frontend-readable delivery manifest."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        output = {
            "mode": "placeholder",
            "delivery_status": "manifest_only",
            "frontend_contract": {
                "dataset_summary": "JSON", "quality_metrics": "JSON/TSV",
                "figures": "PNG/SVG", "processed_data": "BIDS derivatives URI",
            },
            "required_gates": [
                "run-validation pass", "report-validation pass", "artifact links resolvable"
            ],
            "delivered_files": [],
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            artifacts=[Artifact(name="delivery_manifest", kind="manifest", data=output)],
            observations=["真实产物尚不存在，本轮不生成伪造下载链接。"],
        )
