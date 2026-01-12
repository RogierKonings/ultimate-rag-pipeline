"""
Audit log database model.

This module defines the SQLAlchemy model for audit log entries.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AuditLog(Base):
    """
    Audit log entry database model.

    Stores all audit events for compliance and security monitoring.
    Includes hash chaining for tamper evidence.
    """

    __tablename__ = "audit_logs"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Correlation
    trace_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    span_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )

    # Timing
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    duration_ms: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )

    # Actor
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    username: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    tenant_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    service_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    api_key_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    # Action
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    # Resource
    resource_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    resource_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    resource_name: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    # Request context
    client_ip: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True,
        index=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    request_method: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )
    request_path: Mapped[Optional[str]] = mapped_column(
        String(2000),
        nullable=True,
    )
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    # Response
    status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    # Additional context
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    changes: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Tamper evidence
    previous_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    entry_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )

    # Composite indexes for common queries
    __table_args__ = (
        # Query by user in time range
        Index(
            "ix_audit_logs_user_timestamp",
            "user_id",
            "timestamp",
        ),
        # Query by tenant in time range
        Index(
            "ix_audit_logs_tenant_timestamp",
            "tenant_id",
            "timestamp",
        ),
        # Query by action and outcome
        Index(
            "ix_audit_logs_action_outcome",
            "action",
            "outcome",
        ),
        # Query by resource
        Index(
            "ix_audit_logs_resource",
            "resource_type",
            "resource_id",
        ),
        # Query for failures/errors
        Index(
            "ix_audit_logs_outcome_timestamp",
            "outcome",
            "timestamp",
            postgresql_where="outcome IN ('failure', 'denied', 'error')",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"user_id={self.user_id}, timestamp={self.timestamp})>"
        )
