"""Base search interface."""

from abc import ABC, abstractmethod
from typing import Any


class BaseSearcher(ABC):
    """Abstract base class for search implementations."""

    @abstractmethod
    async def search(
        self,
        query: Any,
        top_k: int = 10,
        filters: dict | None = None,
        **kwargs,
    ) -> Any:
        """Execute search and return results."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if search backend is healthy."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to search backend."""

    @abstractmethod
    async def close(self) -> None:
        """Close connections."""

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
