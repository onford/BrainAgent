from typing import Any

from app.integrations.clients.http import HttpExternalToolClient


class GitHubClient(HttpExternalToolClient):
    async def search_repositories(
        self, query: str, *, limit: int = 10
    ) -> dict[str, Any]:
        return await super().search(query, limit=limit)

    def _search_request(self, query: str, kwargs: dict[str, Any]):
        return '/search/repositories', {'q': query, 'per_page': max(1, min(int(kwargs.get('limit', 10)), 100))}
