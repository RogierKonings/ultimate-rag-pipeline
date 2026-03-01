"""
Audit logging data models.

This module defines the data structures for audit log entries,
including actions, outcomes, and query models.
"""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AuditAction(StrEnum):
    """Types of auditable actions."""

    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"  # noqa: S105
    AUTH_TOKEN_REVOKE = "auth.token_revoke"  # noqa: S105
    AUTH_PASSWORD_CHANGE = "auth.password_change"  # noqa: S105
    AUTH_MFA_ENABLE = "auth.mfa_enable"
    AUTH_MFA_DISABLE = "auth.mfa_disable"

    # Document operations
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_READ = "document.read"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_DOWNLOAD = "document.download"
    DOCUMENT_SHARE = "document.share"
    DOCUMENT_UNSHARE = "document.unshare"

    # Query operations
    QUERY_SEARCH = "query.search"
    QUERY_RETRIEVE = "query.retrieve"
    QUERY_CHAT = "query.chat"

    # ACL operations
    ACL_CREATE = "acl.create"
    ACL_UPDATE = "acl.update"
    ACL_DELETE = "acl.delete"
    ACL_GRANT = "acl.grant"
    ACL_REVOKE = "acl.revoke"

    # Admin operations
    ADMIN_USER_CREATE = "admin.user_create"
    ADMIN_USER_UPDATE = "admin.user_update"
    ADMIN_USER_DELETE = "admin.user_delete"
    ADMIN_USER_DISABLE = "admin.user_disable"
    ADMIN_ROLE_ASSIGN = "admin.role_assign"
    ADMIN_ROLE_REVOKE = "admin.role_revoke"
    ADMIN_GROUP_CREATE = "admin.group_create"
    ADMIN_GROUP_UPDATE = "admin.group_update"
    ADMIN_GROUP_DELETE = "admin.group_delete"

    # Configuration
    CONFIG_UPDATE = "config.update"
    CONFIG_SECRET_ACCESS = "config.secret_access"  # noqa: S105
    CONFIG_KEY_ROTATE = "config.key_rotate"

    # Data operations
    DATA_EXPORT = "data.export"
    DATA_IMPORT = "data.import"
    DATA_PURGE = "data.purge"
    DATA_BACKUP = "data.backup"
    DATA_RESTORE = "data.restore"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Generic
    GENERIC_READ = "generic.read"
    GENERIC_WRITE = "generic.write"
    GENERIC_DELETE = "generic.delete"


class AuditOutcome(StrEnum):
    """Outcome of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"  # Access denied (403)
    UNAUTHORIZED = "unauthorized"  # Not authenticated (401)
    ERROR = "error"  # Server error (5xx)
    PARTIAL = "partial"  # Partially successful


class AuditSeverity(StrEnum):
    """Severity level of audit event."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditLogEntry(BaseModel):
    """
    A single audit log entry.

    Contains all information about an auditable event including
    who performed the action, what was done, and when.
    """

    # Identity
    id: UUID = Field(default_factory=uuid4, description="Unique audit entry ID")
    trace_id: str | None = Field(
        default=None,
        description="Distributed trace ID for correlation",
    )
    span_id: str | None = Field(default=None, description="Span ID within trace")

    # Timing
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the event occurred",
    )
    duration_ms: float | None = Field(
        default=None,
        description="Duration of operation in milliseconds",
    )

    # Actor
    user_id: UUID | None = Field(
        default=None,
        description="User who performed the action",
    )
    username: str | None = Field(default=None, description="Username for display")
    tenant_id: UUID | None = Field(default=None, description="Tenant context")
    service_name: str | None = Field(
        default=None,
        description="Service that generated the event",
    )
    api_key_id: str | None = Field(
        default=None,
        description="API key used (if applicable)",
    )

    # Action
    action: AuditAction = Field(..., description="Type of action performed")
    outcome: AuditOutcome = Field(
        default=AuditOutcome.SUCCESS,
        description="Outcome of the action",
    )
    severity: AuditSeverity = Field(
        default=AuditSeverity.INFO,
        description="Severity level",
    )

    # Resource
    resource_type: str | None = Field(
        default=None,
        description="Type of resource (document, user, etc.)",
    )
    resource_id: str | None = Field(default=None, description="ID of the resource")
    resource_name: str | None = Field(
        default=None,
        description="Name/title of resource",
    )

    # Request context
    client_ip: str | None = Field(default=None, description="Client IP address")
    user_agent: str | None = Field(default=None, description="Client user agent")
    request_method: str | None = Field(default=None, description="HTTP method")
    request_path: str | None = Field(default=None, description="Request path")
    request_id: str | None = Field(default=None, description="Request ID")

    # Response
    status_code: int | None = Field(default=None, description="HTTP status code")
    error_message: str | None = Field(
        default=None,
        description="Error message if failed",
    )
    error_code: str | None = Field(default=None, description="Error code if failed")

    # Additional context
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event details",
    )
    changes: dict[str, Any] | None = Field(
        default=None,
        description="Before/after values for updates",
    )

    # Tamper evidence
    previous_hash: str | None = Field(
        default=None,
        description="Hash of previous audit entry",
    )
    entry_hash: str | None = Field(default=None, description="Hash of this entry")

    def compute_hash(self, previous_hash: str | None = None) -> str:
        """
        Compute SHA-256 hash of this entry for tamper evidence.

        Args:
            previous_hash: Hash of the previous entry in chain.

        Returns:
            Hex-encoded SHA-256 hash.
        """
        # Create deterministic representation
        data = {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "client_ip": self.client_ip,
            "status_code": self.status_code,
            "previous_hash": previous_hash,
        }

        # Compute hash
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def to_log_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for structured logging.

        Returns:
            Dict suitable for JSON logging.
        """
        return {
            "audit_id": str(self.id),
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "username": self.username,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "client_ip": self.client_ip,
            "request_method": self.request_method,
            "request_path": self.request_path,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "entry_hash": self.entry_hash,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary excluding sensitive details.

        For external reporting/export.
        """
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "status_code": self.status_code,
        }


class AuditQuery(BaseModel):
    """Query parameters for searching audit logs."""

    # Time range
    start_time: datetime | None = Field(
        default=None,
        description="Start of time range",
    )
    end_time: datetime | None = Field(default=None, description="End of time range")

    # Filters
    user_id: UUID | None = Field(default=None, description="Filter by user")
    tenant_id: UUID | None = Field(default=None, description="Filter by tenant")
    actions: list[AuditAction] | None = Field(
        default=None,
        description="Filter by actions",
    )
    outcomes: list[AuditOutcome] | None = Field(
        default=None,
        description="Filter by outcomes",
    )
    severities: list[AuditSeverity] | None = Field(
        default=None,
        description="Filter by severity levels",
    )
    resource_type: str | None = Field(
        default=None,
        description="Filter by resource type",
    )
    resource_id: str | None = Field(
        default=None,
        description="Filter by resource ID",
    )
    client_ip: str | None = Field(default=None, description="Filter by client IP")
    trace_id: str | None = Field(default=None, description="Filter by trace ID")

    # Search
    search_text: str | None = Field(
        default=None,
        description="Full-text search in details",
    )

    # Pagination
    limit: int = Field(default=100, ge=1, le=1000, description="Max results")
    offset: int = Field(default=0, ge=0, description="Results offset")

    # Ordering
    order_by: str = Field(default="timestamp", description="Field to order by")
    order_desc: bool = Field(default=True, description="Descending order")


class AuditStats(BaseModel):
    """Statistics about audit logs."""

    total_entries: int = Field(default=0, description="Total audit entries")
    entries_by_action: dict[str, int] = Field(
        default_factory=dict,
        description="Count by action",
    )
    entries_by_outcome: dict[str, int] = Field(
        default_factory=dict,
        description="Count by outcome",
    )
    entries_by_severity: dict[str, int] = Field(
        default_factory=dict,
        description="Count by severity",
    )
    unique_users: int = Field(default=0, description="Unique users")
    unique_resources: int = Field(default=0, description="Unique resources accessed")
    time_range_start: datetime | None = Field(default=None)
    time_range_end: datetime | None = Field(default=None)


class AuditExportRequest(BaseModel):
    """Request for exporting audit logs."""

    query: AuditQuery = Field(default_factory=AuditQuery, description="Query filters")
    format: str = Field(default="json", description="Export format (json, csv)")
    include_details: bool = Field(
        default=False,
        description="Include full details field",
    )
    include_hash: bool = Field(
        default=True,
        description="Include hash chain validation",
    )


class AuditExportResponse(BaseModel):
    """Response for audit log export."""

    total_entries: int = Field(description="Total entries exported")
    file_path: str | None = Field(default=None, description="Path to export file")
    hash_chain_valid: bool = Field(
        default=True,
        description="Whether hash chain is valid",
    )
    export_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
