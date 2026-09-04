import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataSurveyAgent(BaseAgent):
    name = "data_survey"
    description = "Collects dataset facts, statistics, papers, code, and preprocessing literature."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        survey = {
            "mode": "placeholder",
            "dataset_identity": "awaiting dataset name or URL",
            "information_sources": ["official_page", "local_files", "repository", "papers"],
            "statistics": ["subjects", "sessions", "runs", "channels", "sampling_rate", "events"],
            "literature_buckets": [
                "papers_using_dataset", "papers_discussing_dataset", "preprocessing_papers"
            ],
            "evidence_policy": "每项事实保留可核查来源，不把文献参数写成已执行参数。",
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=survey,
            artifacts=[Artifact(name="survey_outline", kind="manifest", data=survey)],
            observations=["未提供具体数据集，本轮只生成调研框架。"],
        )
