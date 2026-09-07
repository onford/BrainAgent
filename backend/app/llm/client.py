from abc import ABC, abstractmethod
import logging
from time import perf_counter
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from app.llm.config import LLMConfig
from app.core.exceptions import LLMConfigurationError
from app.core.logging import current_log_context

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("app.llm.calls")


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError

    async def structured_output(
        self, messages: list[dict[str, str]], response_model: type[T]
    ) -> T:
        content = await self.chat(messages)
        return response_model.model_validate_json(content)


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        config: LLMConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    async def chat(self, messages: list[dict[str, str]]) -> str:
        started_at = perf_counter()
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        parsed_url = urlsplit(endpoint)
        provider = f"{parsed_url.scheme}://{parsed_url.netloc}"
        input_chars = sum(len(message.get("content", "")) for message in messages)
        log_extra = current_log_context()
        logger.info(
            "llm_request_started model=%s provider=%s message_count=%d input_chars=%d",
            self.config.model,
            provider,
            len(messages),
            input_chars,
            extra=log_extra,
        )
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=60, transport=self._transport) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                response_body = response.json()
            content = str(response_body["choices"][0]["message"]["content"])
            usage = response_body.get("usage") or {}
            finish_reason = response_body["choices"][0].get("finish_reason") or "-"
            logger.info(
                "llm_request_completed model=%s status_code=%d request_id=%s "
                "finish_reason=%s prompt_tokens=%s completion_tokens=%s "
                "output_chars=%d duration_ms=%.1f",
                self.config.model,
                response.status_code,
                response.headers.get("x-request-id", "-"),
                finish_reason,
                usage.get("prompt_tokens", "-"),
                usage.get("completion_tokens", "-"),
                len(content),
                (perf_counter() - started_at) * 1000,
                extra=log_extra,
            )
            return content
        except Exception:
            logger.exception(
                "llm_request_failed model=%s provider=%s duration_ms=%.1f",
                self.config.model,
                provider,
                (perf_counter() - started_at) * 1000,
                extra=log_extra,
            )
            raise


def create_llm_client(config: LLMConfig) -> LLMClient:
    if not config.api_key or not config.api_key.strip():
        raise LLMConfigurationError(
            "LLM_API_KEY is not configured. Copy .env.example to .env and set "
            "LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL before starting the backend."
        )
    return OpenAICompatibleClient(config)
