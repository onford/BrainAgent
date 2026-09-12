from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
from math import isfinite
from time import perf_counter
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.config import LLMConfig
from app.core.exceptions import LLMConfigurationError
from app.core.logging import current_log_context

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("app.llm.calls")
_MAX_RETRIES = 3  # In addition to the initial request.
_MAX_RETRY_DELAY_SECONDS = 30.0


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    delay = float(2 ** (attempt - 1))
    if retry_after is not None:
        try:
            requested = float(retry_after)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                requested = (date - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                requested = 0.0
        if isfinite(requested):
            delay = max(delay, requested)
    return delay


class StructuredOutputError(ValueError):
    """Keep the rejected model reply so a caller can request a focused correction."""

    def __init__(self, content: str, cause: ValidationError):
        super().__init__(str(cause))
        self.content = content


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError

    async def structured_output(
        self, messages: list[dict[str, str]], response_model: type[T]
    ) -> T:
        content = await self.chat(messages)
        try:
            return response_model.model_validate_json(content)
        except ValidationError as exc:
            raise StructuredOutputError(content, exc) from exc


class OpenAICompatibleClient(LLMClient):
    def __init__(
        self,
        config: LLMConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer")
        self.config = config
        self._transport = transport
        self._max_retries = max_retries

    async def chat(self, messages: list[dict[str, str]]) -> str:
        from .usage import metered_call

        with metered_call(self.config, messages):
            return await self._chat(messages)

    async def _chat(self, messages: list[dict[str, str]]) -> str:
        from .usage import record, output_limit, reserve_attempt, complete_attempt

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
        if output_limit() is not None:
            payload['max_tokens'] = output_limit()
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=10.0)
        if self.config.reasoning_effort is not None:
            payload["reasoning_effort"] = self.config.reasoning_effort
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=self._transport
            ) as client:
                # Serialize once: retries preserve the exact body and model options.
                request = client.build_request(
                    "POST", endpoint, headers=headers, json=payload
                )
                for attempt in range(1, self._max_retries + 2):
                    ticket, seconds_left = reserve_attempt(len(request.content))
                    record(status="running", attempts=attempt)
                    try:
                        async with asyncio.timeout(seconds_left):
                            response = await client.send(request)
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        failed = (
                            exc.response
                            if isinstance(exc, httpx.HTTPStatusError)
                            else None
                        )
                        status = failed.status_code if failed is not None else "-"
                        complete_attempt(ticket, status='failed', error_type=type(exc).__name__,
                            http_status=failed.status_code if failed is not None else None)
                        request_id = (
                            failed.headers.get("x-request-id", "-")
                            if failed is not None
                            else "-"
                        )
                        retryable = isinstance(
                            exc,
                            (
                                httpx.TimeoutException,
                                httpx.NetworkError,
                                httpx.RemoteProtocolError,
                            ),
                        ) or (
                            failed is not None
                            and (status in {408, 429} or 500 <= status < 600)
                        )
                        details = (
                            f"model={self.config.model} provider={provider} "
                            f"status_code={status} request_id={request_id} "
                            f"attempt={attempt}/{self._max_retries + 1} "
                            f"error={type(exc).__name__}"
                        )
                        if not retryable or attempt > self._max_retries:
                            raise RuntimeError(
                                f"LLM request failed: {details}"
                            ) from exc
                        delay = _retry_delay(
                            failed.headers.get("Retry-After")
                            if failed is not None
                            else None,
                            attempt,
                        )
                        if delay > _MAX_RETRY_DELAY_SECONDS:
                            raise RuntimeError(
                                f'LLM provider requested a retry delay beyond this call budget ({delay:.1f}s); request not resent: {details}'
                            ) from exc
                        logger.warning(
                            "llm_request_retry %s delay_seconds=%.1f",
                            details,
                            delay,
                            extra=log_extra,
                        )
                        await asyncio.sleep(delay)
                    else:
                        try:
                            attempt_body = response.json()
                            attempt_usage = attempt_body.get('usage') if isinstance(attempt_body, dict) else None
                        except ValueError:
                            attempt_usage = None
                        complete_attempt(ticket, status='completed', http_status=response.status_code,
                            usage=attempt_usage, request_id=response.headers.get('x-request-id'))
                        break
            details = (
                f"model={self.config.model} provider={provider} "
                f"status_code={response.status_code} "
                f"request_id={response.headers.get('x-request-id', '-')} "
                f"attempt={attempt}/{self._max_retries + 1}"
            )
            try:
                response_body = response.json()
                record(usage=response_body.get("usage"), http_status=response.status_code,
                    request_id=response.headers.get("x-request-id"),
                    usage_scope="last_response_only; failed/unknown attempts may also be billed")
                choice = response_body["choices"][0]
                finish_reason = choice.get("finish_reason") or "-"
                if finish_reason == "length":
                    raise RuntimeError(
                        "LLM output truncated (finish_reason=length); "
                        f"output/capacity limit reached: {details}"
                    )
                content = choice["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError("message content is not text")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                raise RuntimeError(f"LLM invalid response envelope: {details}") from exc
            usage = response_body.get("usage") or {}
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
