import logging
from pathlib import Path

import httpx
import pytest

from app.core.logging import configure_logging, log_context, log_scope
from app.llm.client import OpenAICompatibleClient
from app.llm.config import LLMConfig


def flush_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_runtime_and_llm_logs_are_written_to_separate_files(tmp_path: Path) -> None:
    configure_logging(tmp_path, max_bytes=10_000, backup_count=1)

    logging.getLogger("app.agents.orchestrator").info(
        "react_test_event",
        extra=log_context(
            run_id="run-1",
            session_id="session-1",
            agent="planner",
            iteration=2,
            step=1,
        ),
    )
    with log_scope(run_id="run-1", session_id="session-1", agent="planner"):
        logging.getLogger("app.llm.calls").info("llm_test_event")
    flush_handlers()

    runtime_log = (tmp_path / "brain_agent.log").read_text(encoding="utf-8")
    llm_log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    assert "react_test_event" in runtime_log
    assert "run_id=run-1" in runtime_log
    assert "llm_test_event" not in runtime_log
    assert "llm_test_event" in llm_log
    assert "run_id=run-1" in llm_log
    assert "react_test_event" not in llm_log


@pytest.mark.asyncio
async def test_llm_log_records_metadata_without_prompt_response_or_key(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer never-write-this-key"
        return httpx.Response(
            200,
            headers={"x-request-id": "request-123"},
            json={
                "choices": [
                    {
                        "message": {"content": "private model response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    configure_logging(tmp_path)
    client = OpenAICompatibleClient(
        LLMConfig(
            api_key="never-write-this-key",
            base_url="https://llm.example/v1",
            model="test-model",
        ),
        transport=httpx.MockTransport(handler),
    )
    with log_scope(run_id="run-2", session_id="session-2", agent="data_survey"):
        content = await client.chat(
            [{"role": "user", "content": "private user prompt"}]
        )
    flush_handlers()

    log_text = (tmp_path / "llm.log").read_text(encoding="utf-8")
    assert content == "private model response"
    assert "llm_request_started" in log_text
    assert "llm_request_completed" in log_text
    assert "request_id=request-123" in log_text
    assert "prompt_tokens=12" in log_text
    assert "run_id=run-2" in log_text
    assert "never-write-this-key" not in log_text
    assert "private user prompt" not in log_text
    assert "private model response" not in log_text
