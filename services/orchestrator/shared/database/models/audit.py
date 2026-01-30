"""
Audit log model for tracking system events and user actions.
"""

import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditLog(Base):
    """
    Stores audit trail for system events and user actions.

    Used for compliance, debugging, and security monitoring.
    """

    __tablename__ = "audit_logs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Event identification
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Type of event: DOCUMENT_INGESTED, QUERY_EXECUTED, etc.",
    )
    event_source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Service that generated the event",
    )

    # Actor information
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="User who triggered the event, if applicable",
    )

    # Event details
    resource_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Type of resource affected: document, chunk, conversation",
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="ID of the affected resource",
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Action performed: CREATE, READ, UPDATE, DELETE, SEARCH",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable description of the event",
    )

    # Request context
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Correlation ID for distributed tracing",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="Client IP address (supports IPv6)",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Additional context
    audit_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional event-specific data",
    )
    audit_changes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Before/after state for update events",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_user", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, event_type='{self.event_type}', action='{self.action}')>"
