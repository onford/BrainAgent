import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataPreprocessingAgent(BaseAgent):
    name = "data_preprocessing"
    description = "Builds candidate workflows from reusable preprocessing units and literature methods."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        output = {
            "mode": "placeholder",
            "unit_library": [
                {"name": "notch_filter", "parameters": {"frequency": "from metadata"}},
                {"name": "bandpass_filter", "parameters": {"l_freq": 1.0, "h_freq": 40.0}},
                {"name": "bad_channel_detection", "parameters": {"policy": "robust"}},
                {"name": "ica", "parameters": {"components": "auto"}},
                {"name": "epoching", "parameters": {"events": "from BIDS"}},
            ],
            "candidate_methods": ["MNE baseline", "RELAX", "validated literature methods"],
            "deduplication": "pending real method cards",
            "execution_status": "simulated_no_raw_data",
            "output_rule": "Raw 与 derivatives 分离，并保存参数、版本、日志和失败记录。",
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            artifacts=[Artifact(name="preprocessing_candidates", kind="pipeline", data=output)],
            observations=["未读取真实 Raw，未执行滤波、ICA 或坏道删除。"],
        )
