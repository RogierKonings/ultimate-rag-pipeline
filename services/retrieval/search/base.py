"""Base search interface."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from search.models import SearchResultItem


class BaseSearcher(ABC):
    """Abstract base class for search implementations."""

    @abstractmethod
    async def search(
        self,
        query: Any,
        top_k: int = 10,
        filters: Optional[dict] = None,
        **kwargs,
    ) -> Any:
        """Execute search and return results."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if search backend is healthy."""
        pass

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to search backend."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connections."""
        pass

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
