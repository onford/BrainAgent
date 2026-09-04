import asyncio
from typing import Any

import httpx

from app.core.exceptions import (
    ExternalToolRateLimitError,
    ExternalToolUnavailableError,
    ToolCredentialInvalidError,
)
from app.integrations.clients.base import ExternalToolClient
from app.integrations.definitions import ToolDefinition


class HttpExternalToolClient(ExternalToolClient):
    def __init__(
        self,
        definition: ToolDefinition,
        credentials: dict[str, Any],
        *,
        timeout_seconds: float,
        max_retries: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tool_id = definition.id
        self._definition = definition
        self._credentials = credentials
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._transport = transport

    def __repr__(self) -> str:
        return f"{type(self).__name__}(tool_id={self.tool_id!r})"

    async def validate_connection(self) -> None:
        await self._request(
            self._definition.validation.path,
            params=self._definition.validation.params,
        )

    async def search(self, query: str, **kwargs: Any) -> Any:
        path, params = self._search_request(query, kwargs)
        response = await self._request(path, params=params)
        content_type = response.headers.get("content-type", "")
        return response.json() if "json" in content_type else response.text

    def _search_request(
        self, query: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        limit = max(1, min(int(kwargs.get("limit", 10)), 100))
        requests: dict[str, tuple[str, dict[str, Any]]] = {
            "semantic_scholar": (
                "/paper/search",
                {"query": query, "limit": limit, "fields": "title,url,year,authors"},
            ),
            "openalex": ("/works", {"search": query, "per-page": limit}),
            "crossref": ("/works", {"query": query, "rows": limit}),
            "europe_pmc": (
                "/search",
                {"query": query, "pageSize": limit, "format": "json"},
            ),
            "arxiv": (
                "/query",
                {"search_query": self._arxiv_query(query), "max_results": limit},
            ),
            "unpaywall": ("/search", {"query": query}),
        }
        try:
            return requests[self.tool_id]
        except KeyError as exc:
            raise NotImplementedError(
                f"{self.tool_id} does not expose a default search operation"
            ) from exc

    @staticmethod
    def _arxiv_query(query: str) -> str:
        cleaned = " ".join(query.replace('"', "").split())
        if not cleaned:
            return "all:*"
        return f'all:"{cleaned}"' if " " in cleaned else f"all:{cleaned}"

    async def _request(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        request_params = dict(params or {})
        headers = {
            "Accept": "application/json",
            "User-Agent": "BrainAgent/0.1",
            **self._definition.headers,
        }
        self._apply_auth(headers, request_params)
        async with httpx.AsyncClient(
            base_url=self._definition.base_url,
            timeout=self._timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.get(path, params=request_params, headers=headers)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise ExternalToolUnavailableError(
                        f"{self.tool_id} is temporarily unavailable"
                    ) from exc
                if response.status_code in {401, 403}:
                    raise ToolCredentialInvalidError(
                        f"{self.tool_id} rejected the configured credentials"
                    )
                if response.status_code == 429:
                    raise ExternalToolRateLimitError(
                        f"{self.tool_id} rate limit was exceeded"
                    )
                if response.status_code >= 500 and attempt < self._max_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                if response.status_code >= 400:
                    raise ExternalToolUnavailableError(
                        f"{self.tool_id} returned HTTP {response.status_code}"
                    )
                return response
        raise ExternalToolUnavailableError(f"{self.tool_id} is unavailable")

    def _apply_auth(
        self, headers: dict[str, str], params: dict[str, Any]
    ) -> None:
        for binding in self._definition.credential_bindings:
            value = self._credentials.get(binding.field)
            if value is None or value == "":
                continue
            rendered = f"{binding.prefix}{value}"
            if binding.location == "header":
                headers[binding.name] = rendered
            elif binding.location == "query":
                params[binding.name] = rendered
            else:
                raise ValueError(
                    f"Unsupported credential binding location: {binding.location}"
                )
