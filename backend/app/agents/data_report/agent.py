import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataReportAgent(BaseAgent):
    name = "data_report"
    description = "Combines evidence, statistics, quality results, and visualizations for users."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        completed = [result.agent_name for result in context.agent_results if result.success]
        report = {
            "mode": "placeholder",
            "title": "EEG Data Survey & Processing Report",
            "sections": [
                "dataset_information", "ingestion_and_consistency", "preprocessing_methods",
                "quality_assessment", "visualizations", "limitations",
            ],
            "evidence_ledger": "planned",
            "source_agents": completed,
            "validation_status": "not_run_without_real_artifacts",
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=report,
            artifacts=[Artifact(name="report_outline", kind="report", data=report)],
            observations=["报告仅为骨架，不包含未经验证的数据事实或图表。"],
        )
