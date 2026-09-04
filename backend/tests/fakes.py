import json

from app.llm.client import LLMClient


class ScriptedLLMClient(LLMClient):
    """Deterministic test double; it is never imported by application code."""

    def __init__(self, responses: list[dict[str, str | None]]) -> None:
        self.responses = list(responses)
        self.messages_seen: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.messages_seen.append(messages)
        if not self.responses:
            raise AssertionError("No scripted LLM response remains")
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def delegate(agent_name: str, instruction: str) -> dict[str, str]:
    return {
        "action": "delegate",
        "rationale": f"需要调用 {agent_name}",
        "agent_name": agent_name,
        "instruction": instruction,
    }


def finish(answer: str = "完整流程已执行，当前领域结果仍为占位产物。") -> dict[str, str]:
    return {"action": "finish", "rationale": "任务已经完成", "final_answer": answer}


def full_workflow_responses() -> list[dict[str, str]]:
    names = [
        "data_survey",
        "data_collection",
        "data_preprocessing",
        "data_evaluation",
        "data_report",
        "data_delivery",
    ]
    return [delegate(name, f"执行 {name}") for name in names] + [finish()]
