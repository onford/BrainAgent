import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataEvaluationAgent(BaseAgent):
    name = "data_evaluation"
    description = "Evaluates candidate preprocessing outputs and selects the best eligible result."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        has_preprocessing = "data_preprocessing" in context.shared_memory
        output = {
            "mode": "placeholder",
            "input_available": has_preprocessing,
            "metric_contract": [
                "bad_channel_removal_rate", "trial_retention", "residual_artifact",
                "spectral_noise", "effective_rank", "reconstruction_error", "CSP-SVM posterior",
            ],
            "selection_policy": "先过硬性质量门槛，再在共同对象与共同尺度上比较。",
            "best_output": None,
            "status": "awaiting_real_derivatives",
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            artifacts=[Artifact(name="quality_manifest", kind="metrics", data=output)],
            observations=["没有真实候选数据，未虚构评分或 best output。"],
        )
