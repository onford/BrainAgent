from abc import ABC, abstractmethod
from typing import Any


class ExternalToolClient(ABC):
    tool_id: str

    @abstractmethod
    async def validate_connection(self) -> None:
        """Raise a normalized integration error when the service is unusable."""

    @abstractmethod
    async def search(self, query: str, **kwargs: Any) -> Any:
        """Run the tool's default search operation."""

