"""Abstract base class for audit logging backends."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from shared.security.audit.models import (
    AuditLogEntry,
    AuditQuery,
    AuditStats,
)


class AuditBackend(ABC):
    """
    Abstract base class for audit log storage backends.

    Implementations should provide persistent storage and querying
    capabilities for audit log entries.
    """

    @abstractmethod
    async def write(self, entry: AuditLogEntry) -> None:
        """
        Write a single audit log entry to the backend.

        Args:
            entry: The audit log entry to persist.

        Raises:
            Exception: If the write operation fails.
        """
        pass

    @abstractmethod
    async def query(self, query: AuditQuery) -> list[AuditLogEntry]:
        """
        Query audit logs based on filter criteria.

        Args:
            query: Query parameters including filters, pagination, and ordering.

        Returns:
            List of matching audit log entries.

        Raises:
            Exception: If the query operation fails.
        """
        pass

    @abstractmethod
    async def get_stats(
        self,
        tenant_id: UUID | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> AuditStats:
        """
        Get aggregated statistics for audit logs.

        Args:
            tenant_id: Optional tenant ID to filter by.
            start_time: Optional start of time range.
            end_time: Optional end of time range.

        Returns:
            Statistics about audit logs in the given scope.

        Raises:
            Exception: If the stats operation fails.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the backend is healthy and accessible.

        Returns:
            True if the backend is healthy, False otherwise.
        """
        pass
