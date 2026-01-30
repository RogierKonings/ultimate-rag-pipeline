"""
Audit logger implementation.

This module provides the AuditLogger class for recording
audit events to structured logs and optional database storage.
"""

import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .models import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditSeverity,
)

# Configure audit logger
audit_logger = logging.getLogger("audit")


class AuditLogHandler(logging.Handler):
    """
    Custom log handler for audit events.

    Outputs structured JSON for log aggregation systems (Loki, ELK).
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record as structured JSON."""
        try:
            if hasattr(record, "audit_entry"):
                entry: AuditLogEntry = record.audit_entry
                log_data = entry.to_log_dict()
                log_data["log_level"] = record.levelname
                log_data["logger"] = record.name

                # Write as JSON to stdout
                print(json.dumps(log_data), file=sys.stdout)
            else:
                # Standard log format
                print(
                    json.dumps(
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "level": record.levelname,
                            "message": record.getMessage(),
                            "logger": record.name,
                        },
                    ),
                    file=sys.stdout,
                )
        except Exception:
            self.handleError(record)


class AuditLogger:
    """
    Audit logger for recording security-relevant events.

    Provides methods for logging various types of audit events
    with structured output suitable for log aggregation.

    Example:
        ```python
        from shared.security.audit import AuditLogger

        logger = AuditLogger(service_name="ingestion-service")

        # Log a login event
        await logger.log_login(
            user_id=user_id,
            username="john@example.com",
            success=True,
            client_ip="192.168.1.1",
        )

        # Log document access
        await logger.log_document_access(
            user_id=user_id,
            document_id=doc_id,
            action=AuditAction.DOCUMENT_READ,
            tenant_id=tenant_id,
        )

        # Log access denied
        await logger.log_access_denied(
            user_id=user_id,
            resource_type="document",
            resource_id=str(doc_id),
            action=AuditAction.DOCUMENT_READ,
            reason="Insufficient permissions",
        )
        ```
    """

    def __init__(
        self,
        service_name: str = "rag-pipeline",
        persist_callback: Callable[[AuditLogEntry], None] | None = None,
        get_previous_hash: Callable[[], str | None] | None = None,
    ):
        """
        Initialize audit logger.

        Args:
            service_name: Name of the service generating events.
            persist_callback: Optional callback to persist entries to database.
            get_previous_hash: Optional callback to get previous entry hash.
        """
        self.service_name = service_name
        self._persist_callback = persist_callback
        self._get_previous_hash = get_previous_hash
        self._last_hash: str | None = None

        # Configure handler if not already configured
        if not audit_logger.handlers:
            handler = AuditLogHandler()
            audit_logger.addHandler(handler)
            audit_logger.setLevel(logging.INFO)

    async def log(
        self,
        action: AuditAction,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: AuditSeverity = AuditSeverity.INFO,
        user_id: UUID | None = None,
        username: str | None = None,
        tenant_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_name: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        request_method: str | None = None,
        request_path: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        status_code: int | None = None,
        duration_ms: float | None = None,
        error_message: str | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """
        Log an audit event.

        Args:
            action: Type of action performed.
            outcome: Outcome of the action.
            severity: Severity level.
            user_id: User who performed the action.
            username: Username for display.
            tenant_id: Tenant context.
            resource_type: Type of resource affected.
            resource_id: ID of the resource.
            resource_name: Name/title of resource.
            client_ip: Client IP address.
            user_agent: Client user agent.
            request_method: HTTP method.
            request_path: Request path.
            request_id: Request ID.
            trace_id: Distributed trace ID.
            span_id: Span ID within trace.
            status_code: HTTP status code.
            duration_ms: Duration in milliseconds.
            error_message: Error message if failed.
            error_code: Error code if failed.
            details: Additional event details.
            changes: Before/after values for updates.

        Returns:
            Created AuditLogEntry.
        """
        # Get previous hash for chain
        previous_hash = None
        if self._get_previous_hash:
            previous_hash = self._get_previous_hash()
        elif self._last_hash:
            previous_hash = self._last_hash

        # Create entry
        entry = AuditLogEntry(
            action=action,
            outcome=outcome,
            severity=severity,
            user_id=user_id,
            username=username,
            tenant_id=tenant_id,
            service_name=self.service_name,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            client_ip=client_ip,
            user_agent=user_agent,
            request_method=request_method,
            request_path=request_path,
            request_id=request_id,
            trace_id=trace_id,
            span_id=span_id,
            status_code=status_code,
            duration_ms=duration_ms,
            error_message=error_message,
            error_code=error_code,
            details=details or {},
            changes=changes,
            previous_hash=previous_hash,
        )

        # Compute hash
        entry.entry_hash = entry.compute_hash(previous_hash)
        self._last_hash = entry.entry_hash

        # Log to structured output
        log_level = self._severity_to_log_level(severity)
        record = logging.LogRecord(
            name="audit",
            level=log_level,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        )
        record.audit_entry = entry
        audit_logger.handle(record)

        # Persist to database if callback provided
        if self._persist_callback:
            try:
                self._persist_callback(entry)
            except Exception as e:
                logging.error(f"Failed to persist audit entry: {e}")

        return entry

    def _severity_to_log_level(self, severity: AuditSeverity) -> int:
        """Convert audit severity to logging level."""
        mapping = {
            AuditSeverity.DEBUG: logging.DEBUG,
            AuditSeverity.INFO: logging.INFO,
            AuditSeverity.WARNING: logging.WARNING,
            AuditSeverity.ERROR: logging.ERROR,
            AuditSeverity.CRITICAL: logging.CRITICAL,
        }
        return mapping.get(severity, logging.INFO)

    # Convenience methods for common events

    async def log_login(
        self,
        user_id: UUID | None = None,
        username: str | None = None,
        tenant_id: UUID | None = None,
        success: bool = True,
        client_ip: str | None = None,
        user_agent: str | None = None,
        failure_reason: str | None = None,
        mfa_used: bool = False,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a login attempt."""
        return await self.log(
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
            user_id=user_id,
            username=username,
            tenant_id=tenant_id,
            client_ip=client_ip,
            user_agent=user_agent,
            error_message=failure_reason,
            details={"mfa_used": mfa_used},
            **kwargs,
        )

    async def log_logout(
        self,
        user_id: UUID,
        username: str | None = None,
        tenant_id: UUID | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a logout event."""
        return await self.log(
            action=AuditAction.AUTH_LOGOUT,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            username=username,
            tenant_id=tenant_id,
            client_ip=client_ip,
            **kwargs,
        )

    async def log_token_refresh(
        self,
        user_id: UUID,
        tenant_id: UUID | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a token refresh."""
        return await self.log(
            action=AuditAction.AUTH_TOKEN_REFRESH,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.DEBUG,
            user_id=user_id,
            tenant_id=tenant_id,
            client_ip=client_ip,
            **kwargs,
        )

    async def log_document_access(
        self,
        user_id: UUID,
        document_id: UUID,
        action: AuditAction,
        tenant_id: UUID | None = None,
        document_name: str | None = None,
        success: bool = True,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log document access."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=str(document_id),
            resource_name=document_name,
            client_ip=client_ip,
            **kwargs,
        )

    async def log_query(
        self,
        user_id: UUID,
        query_text: str,
        tenant_id: UUID | None = None,
        results_count: int = 0,
        duration_ms: float | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a search/retrieval query."""
        # Don't log actual query text for privacy
        return await self.log(
            action=AuditAction.QUERY_SEARCH,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type="query",
            client_ip=client_ip,
            duration_ms=duration_ms,
            details={
                "query_length": len(query_text),
                "results_count": results_count,
            },
            **kwargs,
        )

    async def log_access_denied(
        self,
        user_id: UUID | None,
        resource_type: str,
        resource_id: str,
        action: AuditAction,
        reason: str,
        tenant_id: UUID | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log an access denied event."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.DENIED,
            severity=AuditSeverity.WARNING,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            client_ip=client_ip,
            error_message=reason,
            status_code=403,
            **kwargs,
        )

    async def log_unauthorized(
        self,
        resource_type: str | None = None,
        resource_id: str | None = None,
        client_ip: str | None = None,
        reason: str = "Authentication required",
        **kwargs,
    ) -> AuditLogEntry:
        """Log an unauthorized access attempt."""
        return await self.log(
            action=AuditAction.GENERIC_READ,
            outcome=AuditOutcome.UNAUTHORIZED,
            severity=AuditSeverity.WARNING,
            resource_type=resource_type,
            resource_id=resource_id,
            client_ip=client_ip,
            error_message=reason,
            status_code=401,
            **kwargs,
        )

    async def log_error(
        self,
        action: AuditAction,
        error_message: str,
        error_code: str | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a server error."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.ERROR,
            severity=AuditSeverity.ERROR,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            client_ip=client_ip,
            error_message=error_message,
            error_code=error_code,
            status_code=500,
            **kwargs,
        )

    async def log_acl_change(
        self,
        user_id: UUID,
        document_id: UUID,
        action: AuditAction,
        changes: dict[str, Any],
        tenant_id: UUID | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log an ACL change."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type="document_acl",
            resource_id=str(document_id),
            client_ip=client_ip,
            changes=changes,
            **kwargs,
        )

    async def log_admin_action(
        self,
        user_id: UUID,
        action: AuditAction,
        target_type: str,
        target_id: str,
        target_name: str | None = None,
        tenant_id: UUID | None = None,
        changes: dict[str, Any] | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log an administrative action."""
        return await self.log(
            action=action,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.WARNING,  # Admin actions warrant attention
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=target_type,
            resource_id=target_id,
            resource_name=target_name,
            client_ip=client_ip,
            changes=changes,
            **kwargs,
        )

    async def log_data_export(
        self,
        user_id: UUID,
        export_type: str,
        record_count: int,
        tenant_id: UUID | None = None,
        client_ip: str | None = None,
        **kwargs,
    ) -> AuditLogEntry:
        """Log a data export event."""
        return await self.log(
            action=AuditAction.DATA_EXPORT,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.WARNING,  # Data exports warrant attention
            user_id=user_id,
            tenant_id=tenant_id,
            resource_type=export_type,
            client_ip=client_ip,
            details={"record_count": record_count},
            **kwargs,
        )


# Global audit logger instance
_audit_logger: AuditLogger | None = None


def get_audit_logger(service_name: str = "rag-pipeline") -> AuditLogger:
    """
    Get or create global audit logger.

    Args:
        service_name: Service name for new logger.

    Returns:
        AuditLogger instance.
    """
    global _audit_logger

    if _audit_logger is None:
        _audit_logger = AuditLogger(service_name)

    return _audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """Set the global audit logger instance."""
    global _audit_logger
    _audit_logger = logger
