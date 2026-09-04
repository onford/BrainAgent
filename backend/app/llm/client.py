from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.llm.config import LLMConfig
from app.core.exceptions import LLMConfigurationError

T = TypeVar("T", bound=BaseModel)


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
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    async def chat(self, messages: list[dict[str, str]]) -> str:
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])


def create_llm_client(config: LLMConfig) -> LLMClient:
    if not config.api_key or not config.api_key.strip():
        raise LLMConfigurationError(
            "LLM_API_KEY is not configured. Copy .env.example to .env and set "
            "LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL before starting the backend."
        )
    return OpenAICompatibleClient(config)
