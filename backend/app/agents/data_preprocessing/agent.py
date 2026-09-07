import asyncio

from app.agents.base import BaseAgent
from app.preprocessing.schemas import PlanRequest, Ref, SurveyLiteratureBundle
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataPreprocessingAgent(BaseAgent):
    name = "data_preprocessing"
    description = "Plans or submits real EEG preprocessing using upstream references; reports durable job status."

    def __init__(self, service=None):
        self.service = service

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        inputs = task.inputs
        if self.service is None or not inputs:
            return AgentResult(
                agent_name=self.name,
                success=True,
                output={
                    "execution_status": "needs_input",
                    "missing_fields": [
                        "verified Survey/Collection input_ref",
                        "method references",
                        "scientific analysis parameters",
                    ],
                    "supplement_requests": [
                        {
                            "target_agent": "data_survey",
                            "missing_fields": ["survey facts and evidence"],
                        },
                        {
                            "target_agent": "data_collection",
                            "missing_fields": [
                                "standardized file inventory and selected recordings"
                            ],
                        },
                    ],
                },
                observations=["尚未启动处理；请提供上游输入引用。"],
                metadata={"execution_status": "needs_input"},
            )
        owner = context.owner_id
        try:
            action = inputs.get("action", "plan")
            if action == "plan":
                ref, plan = await asyncio.to_thread(
                    self.service.plan,
                    owner,
                    PlanRequest.model_validate(inputs["request"]),
                )
                output = {
                    "execution_status": "planned",
                    "plan_ref": ref.model_dump(),
                    "screening": [s.model_dump(mode="json") for s in plan.screening],
                    "record_count": len(plan.records),
                    "plan_url": f"/api/preprocessing/plans/{ref.id}",
                }
            elif action == "submit":
                result = await asyncio.to_thread(
                    self.service.submit, owner, Ref.model_validate(inputs["plan_ref"])
                )
                output = {
                    **result.model_dump(mode="json"),
                    "execution_status": "submitted"
                    if result.status in ("queued", "running", "interrupted")
                    else result.status,
                    "status_url": f"/api/preprocessing/jobs/{result.job_id}",
                }
            elif action == "status":
                result = await asyncio.to_thread(
                    self.service.store.status, owner, inputs["job_id"]
                )
                output = {
                    **result.model_dump(mode="json"),
                    "execution_status": result.status,
                    "status_url": f"/api/preprocessing/jobs/{result.job_id}",
                }
            elif action == "literature":
                bundle = SurveyLiteratureBundle.model_validate(
                    self.service.store.get(
                        owner,
                        Ref.model_validate(inputs["literature_ref"]),
                        "literature",
                    )
                )
                result = await self.service.methods.intake(owner, bundle)
                output = {
                    "execution_status": "methods_drafted",
                    "methods": [r.model_dump() for r in result["methods"]],
                    "supplement_requests": result["supplement_requests"],
                }
            else:
                raise ValueError("action must be plan, submit, status or literature")
            return AgentResult(
                agent_name=self.name,
                success=True,
                output=output,
                artifacts=[
                    Artifact(name="preprocessing", kind="reference", data=output)
                ],
                metadata={"execution_status": output["execution_status"]},
            )
        except (ValueError, KeyError, OSError, ImportError) as exc:
            return AgentResult(
                agent_name=self.name,
                success=True,
                output={"execution_status": "needs_input", "blocking_reason": str(exc)},
                observations=["输入或方法未通过执行检查，尚未启动处理。"],
                metadata={"execution_status": "needs_input"},
            )
