"""Abstract base class for index writers."""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class BaseIndexWriter(ABC):
    """Abstract base class for index writers.

    All index writers (Qdrant, OpenSearch, PostgreSQL) must implement
    this interface to ensure consistent behavior across different
    storage backends.

    Supports async context manager protocol for proper resource management.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the store.

        This method should initialize any necessary clients or connection
        pools. It will be called automatically when using the writer as
        an async context manager.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the store.

        This method should properly close any clients or connection pools.
        It will be called automatically when exiting the async context manager.
        """
        pass

    @abstractmethod
    async def ensure_index(self) -> None:
        """Create index/collection/table if it doesn't exist.

        This method should be idempotent - calling it multiple times
        should have the same effect as calling it once.
        """
        pass

    @abstractmethod
    async def write(self, items: list[Any]) -> "WriteResult":  # noqa: F821
        """Write items to the store (upsert).

        This method should perform an upsert operation, creating new
        items or updating existing ones based on their IDs.

        Args:
            items: List of items to write. The exact type depends on
                   the specific writer implementation.

        Returns:
            WriteResult containing success status, counts, and any errors.
        """
        pass

    @abstractmethod
    async def delete(self, ids: list[UUID]) -> "WriteResult":  # noqa: F821
        """Delete items by ID.

        Args:
            ids: List of UUIDs to delete.

        Returns:
            WriteResult containing success status and any errors.
        """
        pass

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> "WriteResult":  # noqa: F821
        """Delete all chunks belonging to a document.

        This method is useful for re-indexing a document - first delete
        all existing chunks, then write the new ones.

        Args:
            document_id: UUID of the document whose chunks should be deleted.

        Returns:
            WriteResult containing success status and any errors.
        """
        pass

    async def __aenter__(self) -> "BaseIndexWriter":
        """Enter async context manager."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager."""
        await self.disconnect()


# Import WriteResult for type hints (avoid circular import at runtime)
from .models import WriteResult  # noqa: E402, F401
