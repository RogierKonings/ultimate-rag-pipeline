"""
Audit log repository for database persistence.

This module provides repository classes for storing and querying
audit logs in PostgreSQL.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
)


class AuditRepository:
    """
    Repository for audit log persistence and queries.

    Provides methods for storing audit entries and querying
    the audit log with various filters.

    Example:
        ```python
        from services.shared.security.audit import AuditRepository

        repo = AuditRepository(session)

        # Store an entry
        await repo.create(entry)

        # Search logs
        query = AuditQuery(
            user_id=user_id,
            start_time=datetime(2024, 1, 1),
            actions=[AuditAction.DOCUMENT_READ],
        )
        results = await repo.search(query)

        # Get user activity
        activity = await repo.get_user_activity(user_id, limit=50)

        # Get resource history
        history = await repo.get_resource_history("document", doc_id)
        ```
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def create(self, entry: AuditLogEntry) -> AuditLogEntry:
        """
        Create a new audit log entry.

        Args:
            entry: Audit log entry to create.

        Returns:
            Created entry with database ID.
        """
        # Import here to avoid circular imports
        from services.shared.database.models.audit_log import AuditLog

        db_entry = AuditLog(
            id=entry.id,
            trace_id=entry.trace_id,
            span_id=entry.span_id,
            timestamp=entry.timestamp,
            duration_ms=entry.duration_ms,
            user_id=entry.user_id,
            username=entry.username,
            tenant_id=entry.tenant_id,
            service_name=entry.service_name,
            api_key_id=entry.api_key_id,
            action=entry.action.value,
            outcome=entry.outcome.value,
            severity=entry.severity.value,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            resource_name=entry.resource_name,
            client_ip=entry.client_ip,
            user_agent=entry.user_agent,
            request_method=entry.request_method,
            request_path=entry.request_path,
            request_id=entry.request_id,
            status_code=entry.status_code,
            error_message=entry.error_message,
            error_code=entry.error_code,
            details=entry.details,
            changes=entry.changes,
            previous_hash=entry.previous_hash,
            entry_hash=entry.entry_hash,
        )

        self.session.add(db_entry)
        await self.session.commit()
        await self.session.refresh(db_entry)

        return entry

    async def search(self, query: AuditQuery) -> list[AuditLogEntry]:
        """
        Search audit logs with filters.

        Args:
            query: Query parameters.

        Returns:
            List of matching audit entries.
        """
        from services.shared.database.models.audit_log import AuditLog

        stmt = select(AuditLog)
        conditions = []

        # Time range
        if query.start_time:
            conditions.append(AuditLog.timestamp >= query.start_time)
        if query.end_time:
            conditions.append(AuditLog.timestamp <= query.end_time)

        # User filter
        if query.user_id:
            conditions.append(AuditLog.user_id == query.user_id)

        # Tenant filter
        if query.tenant_id:
            conditions.append(AuditLog.tenant_id == query.tenant_id)

        # Action filter
        if query.actions:
            action_values = [a.value for a in query.actions]
            conditions.append(AuditLog.action.in_(action_values))

        # Outcome filter
        if query.outcomes:
            outcome_values = [o.value for o in query.outcomes]
            conditions.append(AuditLog.outcome.in_(outcome_values))

        # Severity filter
        if query.severities:
            severity_values = [s.value for s in query.severities]
            conditions.append(AuditLog.severity.in_(severity_values))

        # Resource filter
        if query.resource_type:
            conditions.append(AuditLog.resource_type == query.resource_type)
        if query.resource_id:
            conditions.append(AuditLog.resource_id == query.resource_id)

        # Client IP filter
        if query.client_ip:
            conditions.append(AuditLog.client_ip == query.client_ip)

        # Trace ID filter
        if query.trace_id:
            conditions.append(AuditLog.trace_id == query.trace_id)

        # Apply conditions
        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Ordering
        order_column = getattr(AuditLog, query.order_by, AuditLog.timestamp)
        if query.order_desc:
            stmt = stmt.order_by(desc(order_column))
        else:
            stmt = stmt.order_by(order_column)

        # Pagination
        stmt = stmt.offset(query.offset).limit(query.limit)

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [self._to_entry(row) for row in rows]

    async def get_by_id(self, entry_id: UUID) -> AuditLogEntry | None:
        """Get audit entry by ID."""
        from services.shared.database.models.audit_log import AuditLog

        stmt = select(AuditLog).where(AuditLog.id == entry_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        return self._to_entry(row) if row else None

    async def get_user_activity(
        self,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[AuditLogEntry]:
        """
        Get audit entries for a specific user.

        Args:
            user_id: User ID.
            limit: Max results.
            offset: Results offset.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            List of user's audit entries.
        """
        query = AuditQuery(
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        return await self.search(query)

    async def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        """
        Get audit history for a specific resource.

        Args:
            resource_type: Type of resource.
            resource_id: ID of resource.
            limit: Max results.

        Returns:
            List of audit entries for the resource.
        """
        query = AuditQuery(
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
        )
        return await self.search(query)

    async def get_stats(
        self,
        tenant_id: UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> AuditStats:
        """
        Get audit statistics.

        Args:
            tenant_id: Filter by tenant.
            start_time: Start of time range.
            end_time: End of time range.

        Returns:
            Audit statistics.
        """
        from services.shared.database.models.audit_log import AuditLog

        conditions = []
        if tenant_id:
            conditions.append(AuditLog.tenant_id == tenant_id)
        if start_time:
            conditions.append(AuditLog.timestamp >= start_time)
        if end_time:
            conditions.append(AuditLog.timestamp <= end_time)

        where_clause = and_(*conditions) if conditions else True

        # Total count
        total_stmt = select(func.count(AuditLog.id)).where(where_clause)
        total_result = await self.session.execute(total_stmt)
        total_entries = total_result.scalar() or 0

        # Count by action
        action_stmt = (
            select(AuditLog.action, func.count(AuditLog.id))
            .where(where_clause)
            .group_by(AuditLog.action)
        )
        action_result = await self.session.execute(action_stmt)
        entries_by_action = {row[0]: row[1] for row in action_result}

        # Count by outcome
        outcome_stmt = (
            select(AuditLog.outcome, func.count(AuditLog.id))
            .where(where_clause)
            .group_by(AuditLog.outcome)
        )
        outcome_result = await self.session.execute(outcome_stmt)
        entries_by_outcome = {row[0]: row[1] for row in outcome_result}

        # Count by severity
        severity_stmt = (
            select(AuditLog.severity, func.count(AuditLog.id))
            .where(where_clause)
            .group_by(AuditLog.severity)
        )
        severity_result = await self.session.execute(severity_stmt)
        entries_by_severity = {row[0]: row[1] for row in severity_result}

        # Unique users
        users_stmt = (
            select(func.count(func.distinct(AuditLog.user_id)))
            .where(where_clause)
            .where(AuditLog.user_id.isnot(None))
        )
        users_result = await self.session.execute(users_stmt)
        unique_users = users_result.scalar() or 0

        # Unique resources
        resources_stmt = (
            select(func.count(func.distinct(AuditLog.resource_id)))
            .where(where_clause)
            .where(AuditLog.resource_id.isnot(None))
        )
        resources_result = await self.session.execute(resources_stmt)
        unique_resources = resources_result.scalar() or 0

        return AuditStats(
            total_entries=total_entries,
            entries_by_action=entries_by_action,
            entries_by_outcome=entries_by_outcome,
            entries_by_severity=entries_by_severity,
            unique_users=unique_users,
            unique_resources=unique_resources,
            time_range_start=start_time,
            time_range_end=end_time,
        )

    async def count_by_action(
        self,
        action: AuditAction,
        tenant_id: UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        """Count entries for a specific action."""
        from services.shared.database.models.audit_log import AuditLog

        conditions = [AuditLog.action == action.value]
        if tenant_id:
            conditions.append(AuditLog.tenant_id == tenant_id)
        if start_time:
            conditions.append(AuditLog.timestamp >= start_time)
        if end_time:
            conditions.append(AuditLog.timestamp <= end_time)

        stmt = select(func.count(AuditLog.id)).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def validate_hash_chain(
        self,
        start_id: UUID | None = None,
        limit: int = 1000,
    ) -> tuple[bool, str | None]:
        """
        Validate the integrity of the hash chain.

        Args:
            start_id: Start from this entry ID.
            limit: Max entries to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        from services.shared.database.models.audit_log import AuditLog

        stmt = select(AuditLog).order_by(AuditLog.timestamp).limit(limit)
        if start_id:
            subq = select(AuditLog.timestamp).where(AuditLog.id == start_id)
            stmt = stmt.where(AuditLog.timestamp >= subq.scalar_subquery())

        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        previous_hash = None
        for row in rows:
            entry = self._to_entry(row)

            # Check if previous hash matches
            if entry.previous_hash != previous_hash:
                return False, f"Hash chain broken at entry {entry.id}"

            # Verify entry hash
            computed = entry.compute_hash(previous_hash)
            if entry.entry_hash != computed:
                return False, f"Entry hash mismatch at {entry.id}"

            previous_hash = entry.entry_hash

        return True, None

    async def get_latest_hash(self) -> str | None:
        """Get the hash of the most recent audit entry."""
        from services.shared.database.models.audit_log import AuditLog

        stmt = select(AuditLog.entry_hash).order_by(desc(AuditLog.timestamp)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar()

    def _to_entry(self, row) -> AuditLogEntry:
        """Convert database row to AuditLogEntry."""
        return AuditLogEntry(
            id=row.id,
            trace_id=row.trace_id,
            span_id=row.span_id,
            timestamp=row.timestamp,
            duration_ms=row.duration_ms,
            user_id=row.user_id,
            username=row.username,
            tenant_id=row.tenant_id,
            service_name=row.service_name,
            api_key_id=row.api_key_id,
            action=AuditAction(row.action),
            outcome=AuditOutcome(row.outcome),
            severity=AuditSeverity(row.severity),
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            resource_name=row.resource_name,
            client_ip=row.client_ip,
            user_agent=row.user_agent,
            request_method=row.request_method,
            request_path=row.request_path,
            request_id=row.request_id,
            status_code=row.status_code,
            error_message=row.error_message,
            error_code=row.error_code,
            details=row.details or {},
            changes=row.changes,
            previous_hash=row.previous_hash,
            entry_hash=row.entry_hash,
        )
