import asyncio
import re
from time import time
from math import isfinite
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
        self._state = None
        self._owner = None
        self.last_request_metadata = None

    def attach_state(self, state, owner):
        from app.preprocessing.storage import digest
        self._state, self._owner = state, owner
        # Cooldowns follow the actual provider credential/IP bucket; cached
        # content additionally binds the owner. Only digests reach filenames.
        self._provider_scope = digest([self.tool_id, self._definition.base_url, self._credentials])

    def __repr__(self) -> str:
        return f"{type(self).__name__}(tool_id={self.tool_id!r})"

    async def validate_connection(self) -> None:
        await self._request(
            self._definition.validation.path,
            params=self._definition.validation.params,
        )

    async def search(self, query: str, **kwargs: Any) -> Any:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        self.last_request_metadata = dict(cache='lookup', transport_attempts=0, request_outcome='not_sent')
        path, params = self._search_request(query, kwargs)
        if self._state is None:
            return await self._search_response(path, params)
        from app.preprocessing.storage import digest
        key = digest(['provider-search-cache-v1', self._owner, self._provider_scope, self._definition.headers, path, params])
        async with self._state.coalesce(key, self._timeout_seconds):
            saved = self._state.cached(key)
            if saved:
                self.last_request_metadata = dict(cache='hit', fetched_at=saved['fetched_at'],
                    expires_at=saved['expires_at'], output_sha256=saved['output_sha256'],
                    snapshot_age_seconds=max(0, self._state.clock() - saved['fetched_at']),
                    transport_attempts=0, request_outcome='cached_snapshot')
                return saved['output']
            return await self._search_response(path, params, cache_key=key)

    async def _search_response(self, path, params, cache_key=None):
        started = time()
        response = await self._request(path, params=params)
        content_type = response.headers.get("content-type", "")
        try:
            output = response.json() if "json" in content_type else response.text
        except ValueError as exc:
            raise ExternalToolUnavailableError(
                f"{self.tool_id} returned invalid JSON"
            ) from exc
        if self._state is not None:
            from app.preprocessing.storage import digest
            fetched = self._state.clock()
            self.last_request_metadata = dict(self.last_request_metadata or {}, cache='miss', fetched_at=fetched, snapshot_age_seconds=0,
                                              output_sha256=digest(output))
            # Cache only provider-shaped successful searches. Validation probes,
            # malformed bodies and API error payloads cannot become cache hits.
            from app.tools.output import normalize_tool_output
            try:
                normalized = normalize_tool_output(self.tool_id, output)
                valid = not (isinstance(normalized, dict) and normalized.get('warning'))
            except (ExternalToolUnavailableError, ValueError, TypeError, KeyError):
                valid = False
            from .state import response_ttl
            ttl = response_ttl(response.headers, fetched, max(0, time()-started), self._state.ttl)
            if valid and cache_key:
                self._state.store(cache_key, output, fetched_at=fetched, ttl=ttl)
                self.last_request_metadata['expires_at'] = fetched + ttl if ttl > 0 else None
        return output

    def _search_request(
        self, query: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        limit = max(1, min(int(kwargs.get("limit", 10)), 100))
        requests: dict[str, tuple[str, dict[str, Any]]] = {
            "semantic_scholar": (
                "/paper/search",
                {
                    "query": query,
                    "limit": limit,
                    "fields": "title,url,year,authors,abstract,externalIds,openAccessPdf,citationCount,venue",
                },
            ),
            "openalex": ("/works", {"search": query, "per-page": limit}),
            "crossref": ("/works", {"query": query, "rows": limit}),
            "europe_pmc": (
                "/search",
                {
                    "query": query,
                    "pageSize": limit,
                    "format": "json",
                    "resultType": "core",
                },
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
        cleaned = " ".join(query.split())
        if not cleaned:
            raise ValueError("query must be a non-empty string")
        # Preserve native field/Boolean expressions, including explicit phrases.
        if re.search(
            r"\b(?:ti|au|abs|co|jr|cat|rn|id|all):|\b(?:AND|OR|ANDNOT)\b", cleaned
        ):
            return cleaned
        terms = re.findall(r'"[^"]+"|[^\s"]+', cleaned)
        return " AND ".join(f"all:{term}" for term in terms)

    async def _request(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        self.last_request_metadata = dict(cache='not_used', transport_attempts=0, request_outcome='not_sent')
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
                if self._state is not None and (cooldown := self._state.cooldown(self._provider_scope)):
                    seconds = max(0, cooldown['until'] - self._state.clock())
                    self.last_request_metadata.update(request_outcome='shared_cooldown', cooldown_until=cooldown['until'])
                    error = ExternalToolRateLimitError if cooldown['kind'] == 'rate_limit' else ExternalToolUnavailableError
                    raise error(f'{self.tool_id} shared cooldown: {seconds:.1f}s remaining; no request sent')
                try:
                    self.last_request_metadata.update(transport_attempts=attempt+1, request_outcome='transport_attempt_started', status_code=None)
                    response = await client.get(
                        path, params=request_params, headers=headers
                    )
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                    self.last_request_metadata['request_outcome'] = 'transport_error_outcome_unknown'
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.1 * (2**attempt))
                        continue
                    raise ExternalToolUnavailableError(
                        f"{self.tool_id} is temporarily unavailable"
                    ) from exc
                self.last_request_metadata.update(request_outcome='response_received', status_code=response.status_code)
                rate_limited = response.status_code == 429
                if self.tool_id == 'github' and response.status_code == 403:
                    rate_limited = (response.headers.get('x-ratelimit-remaining') == '0'
                        or 'retry-after' in response.headers
                        or 'rate limit' in response.text[:2000].lower())
                if rate_limited:
                    from app.llm.client import _retry_delay
                    delay = _retry_delay(response.headers.get('retry-after'), attempt+1)
                    if self.tool_id == 'github':
                        if response.headers.get('x-ratelimit-remaining') == '0':
                            try:
                                reset = float(response.headers['x-ratelimit-reset']) - time()
                                if isfinite(reset):
                                    delay = max(delay, reset)
                                else:
                                    delay = max(delay, 60)
                            except (KeyError, ValueError):
                                delay = max(delay, 60)
                        elif 'retry-after' not in response.headers:
                            delay = max(delay, 60)
                    # Respect the server minimum. A long cooldown is returned
                    # to the caller for fallback, never shortened to retry early.
                    if self._state is not None:
                        cooldown = self._state.defer(self._provider_scope, delay, 'rate_limit')
                        self.last_request_metadata['cooldown_until'] = cooldown['until']
                    if attempt < self._max_retries and delay <= min(30, self._timeout_seconds):
                        await asyncio.sleep(delay)
                        continue
                    raise ExternalToolRateLimitError(
                        f'{self.tool_id} rate limit; requested wait {delay:.1f}s, request not resent')
                if response.status_code in {401, 403}:
                    raise ToolCredentialInvalidError(
                        f"{self.tool_id} rejected the configured credentials"
                    )
                if response.status_code >= 500:
                    from app.llm.client import _retry_delay
                    delay = _retry_delay(response.headers.get('retry-after'), attempt+1)
                    if self._state is not None:
                        self._state.defer(self._provider_scope, delay, 'unavailable')
                    if attempt >= self._max_retries or delay > min(30, self._timeout_seconds):
                        raise ExternalToolUnavailableError(f'{self.tool_id} requested a longer cooldown; request not resent')
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise ExternalToolUnavailableError(
                        f"{self.tool_id} returned HTTP {response.status_code}"
                    )
                return response
        raise ExternalToolUnavailableError(f"{self.tool_id} is unavailable")

    def _apply_auth(self, headers: dict[str, str], params: dict[str, Any]) -> None:
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
