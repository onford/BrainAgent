import asyncio
import json
import logging
from enum import StrEnum
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agents.base import BaseAgent
from app.agents.data_survey.prompt import DATA_SURVEY_SYSTEM_PROMPT
from app.llm.client import LLMClient
from app.core.logging import log_context, log_scope
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact
from app.tools.registry import ToolRegistry
from app.preprocessing.schemas import SurveyLiteratureBundle


logger = logging.getLogger(__name__)


class SurveyAction(StrEnum):
    CALL_TOOL = "call_tool"
    FINISH = "finish"


class SurveyDecision(BaseModel):
    action: SurveyAction
    rationale: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    literature_bundle: SurveyLiteratureBundle | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "SurveyDecision":
        if self.action is SurveyAction.CALL_TOOL and not self.tool_name:
            raise ValueError("tool_name is required when action is call_tool")
        if self.action is SurveyAction.FINISH and not self.summary:
            raise ValueError("summary is required when action is finish")
        return self


class DataSurveyAgent(BaseAgent):
    name = "data_survey"
    description = "Collects dataset facts, statistics, papers, code, and preprocessing literature."

    def __init__(
        self,
        llm: LLMClient | None = None,
        tools: ToolRegistry | None = None,
        *,
        max_tool_calls: int = 8,
        preprocessing=None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_tool_calls = max(1, max_tool_calls)
        self.preprocessing = preprocessing

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        if task.inputs.get("literature_bundle") and self.preprocessing:
            bundle = SurveyLiteratureBundle.model_validate(task.inputs["literature_bundle"])
            ref = self.preprocessing.register_bundle(context.owner_id, bundle)
            return AgentResult(agent_name=self.name, success=True, output={"literature_ref": ref.model_dump(), "survey_run_id": bundle.survey_run_id}, observations=["已发布完整文献证据包供 Preprocess 接入。"])
        if self.llm is not None and self.tools is not None:
            return await self._run_with_tools(task, context)

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

    async def _run_with_tools(
        self, task: AgentTask, context: AgentContext
    ) -> AgentResult:
        catalog = await self.tools.catalog(context)
        available_names = {item["name"] for item in catalog if item["available"]}
        tool_calls: list[dict[str, Any]] = []
        observations: list[str] = []

        logger.info(
            "survey_tool_loop_started catalog_size=%d available_tools=%d max_tool_calls=%d",
            len(catalog),
            len(available_names),
            self.max_tool_calls,
            extra=log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.name,
                step=task.step,
            ),
        )
        for iteration in range(1, self.max_tool_calls + 2):
            log_extra = log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.name,
                iteration=iteration,
                step=task.step,
            )
            try:
                with log_scope(**log_extra):
                    decision = await self.llm.structured_output(
                        [
                            {"role": "system", "content": DATA_SURVEY_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": self._decision_context(
                                    task, context, catalog, tool_calls
                                ),
                            },
                        ],
                        SurveyDecision,
                    )
            except Exception:
                logger.exception("survey_decision_failed", extra=log_extra)
                raise
            logger.info(
                "survey_decision_completed action=%s tool=%s calls_used=%d",
                decision.action.value,
                decision.tool_name or "-",
                len(tool_calls),
                extra=log_extra,
            )
            if decision.action is SurveyAction.FINISH:
                output = {
                    "summary": decision.summary,
                    "tool_calls": tool_calls,
                    "evidence_policy": (
                        "每项事实保留可核查来源，不把文献参数写成已执行参数。"
                    ),
                }
                if decision.literature_bundle and self.preprocessing:
                    ref = self.preprocessing.register_bundle(context.owner_id, decision.literature_bundle)
                    output["literature_ref"] = ref.model_dump()
                result = AgentResult(
                    agent_name=self.name,
                    success=True,
                    output=output,
                    artifacts=[
                        Artifact(name="data_survey", kind="manifest", data=output)
                    ],
                    observations=observations or ["调研完成，未调用外部工具。"],
                    metadata={"tool_call_count": len(tool_calls)},
                )
                logger.info(
                    "survey_tool_loop_completed tool_calls=%d",
                    len(tool_calls),
                    extra=log_extra,
                )
                return result

            tool_name = decision.tool_name or ""
            arguments = dict(decision.arguments)
            if len(tool_calls) >= self.max_tool_calls:
                break
            if tool_name not in available_names:
                result_record = {
                    "tool": tool_name,
                    "arguments": self._public_arguments(arguments),
                    "success": False,
                    "error": "工具不存在或当前不可用。",
                    "metadata": {"error_code": "tool_unavailable"},
                }
            else:
                tool_started_at = perf_counter()
                logger.info(
                    "survey_tool_call_started tool=%s argument_keys=%s",
                    tool_name,
                    sorted(arguments),
                    extra=log_extra,
                )
                result = await self.tools.execute(tool_name, context, **arguments)
                result_count = (
                    result.output.get("result_count", "-")
                    if isinstance(result.output, dict)
                    else "-"
                )
                logger.info(
                    "survey_tool_call_completed tool=%s success=%s result_count=%s "
                    "error_code=%s duration_ms=%.1f",
                    tool_name,
                    result.success,
                    result_count,
                    result.metadata.get("error_code", "-"),
                    (perf_counter() - tool_started_at) * 1000,
                    extra=log_extra,
                )
                result_record = {
                    "tool": tool_name,
                    "arguments": self._public_arguments(arguments),
                    "success": result.success,
                    "output": result.output if result.success else None,
                    "error": result.error,
                    "metadata": result.metadata,
                }
            tool_calls.append(result_record)
            state = "成功" if result_record["success"] else "失败"
            observations.append(f"工具 {tool_name} 调用{state}。")

        output = {
            "summary": self._limit_summary(tool_calls),
            "tool_calls": tool_calls,
            "evidence_policy": "每项事实保留可核查来源，不把文献参数写成已执行参数。",
        }
        logger.warning(
            "survey_tool_call_limit_reached tool_calls=%d",
            len(tool_calls),
            extra=log_context(
                run_id=context.run_id,
                session_id=context.session_id,
                agent=self.name,
                iteration=self.max_tool_calls + 1,
                step=task.step,
            ),
        )
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            artifacts=[Artifact(name="data_survey", kind="manifest", data=output)],
            observations=observations,
            metadata={"tool_call_count": len(tool_calls), "tool_limit_reached": True},
        )

    @staticmethod
    def _public_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        """Keep useful provenance while never reflecting credentials or file content."""
        public: dict[str, Any] = {}
        if "query" in arguments:
            public["query"] = str(arguments["query"])[:500]
        if "limit" in arguments:
            public["limit"] = arguments["limit"]
        return public

    @staticmethod
    def _limit_summary(tool_calls: list[dict[str, Any]]) -> str:
        successful = [call for call in tool_calls if call.get("success")]
        sources = list(dict.fromkeys(str(call.get("tool")) for call in successful))
        titles: list[str] = []
        evidence_count = 0
        for call in successful:
            output = call.get("output")
            if not isinstance(output, dict):
                continue
            items = output.get("items", [])
            if not isinstance(items, list):
                continue
            evidence_count += len(items)
            for item in items:
                if isinstance(item, dict) and item.get("title"):
                    titles.append(str(item["title"]))
        source_text = "、".join(sources) or "无"
        title_text = "；".join(titles[:3])
        summary = (
            f"工具调用达到上限；已完成 {len(tool_calls)} 次调用，其中 "
            f"{len(successful)} 次成功，从 {source_text} 获得 {evidence_count} 条候选证据。"
        )
        if title_text:
            summary += f" 代表性结果：{title_text}。"
        return summary

    def _decision_context(
        self,
        task: AgentTask,
        context: AgentContext,
        catalog: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> str:
        # Bound model context even when a provider returns unexpectedly large payloads.
        prior_results = json.dumps(tool_calls, ensure_ascii=False, default=str)
        if len(prior_results) > 40_000:
            prior_results = prior_results[-40_000:]
        return (
            f"Assigned task: {task.instruction}\n"
            f"Structured upstream inputs and supplement requests: {json.dumps(task.inputs, ensure_ascii=False)}\n"
            f"Original user request: {context.user_message}\n"
            f"Available tool catalog: {json.dumps(catalog, ensure_ascii=False)}\n"
            f"Remaining tool calls: {max(0, self.max_tool_calls - len(tool_calls))}\n"
            f"Prior tool calls and results: {prior_results}"
        )
