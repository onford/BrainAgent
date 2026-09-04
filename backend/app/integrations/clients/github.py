from typing import Any

from app.integrations.clients.http import HttpExternalToolClient


class GitHubClient(HttpExternalToolClient):
    async def search_repositories(
        self, query: str, *, limit: int = 10
    ) -> dict[str, Any]:
        response = await self._request(
            "/search/repositories",
            params={"q": query, "per_page": max(1, min(limit, 100))},
        )
        return response.json()

    async def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return await self.search_repositories(query, limit=int(kwargs.get("limit", 10)))
