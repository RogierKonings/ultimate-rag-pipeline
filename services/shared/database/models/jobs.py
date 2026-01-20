"""
Models for embedding jobs and retrieval/ingestion logging (US-2.12).
"""

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EmbeddingJob(Base):
    """
    Tracks re-embedding jobs when changing embedding models.

    Used to manage and monitor bulk re-embedding operations.
    """

    __tablename__ = "embedding_jobs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Job status
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        comment="Job status: pending, running, completed, failed",
    )

    # Embedding configuration
    embedding_model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Target embedding model (e.g., BAAI/bge-large-en-v1.5)",
    )

    # Scope for re-embedding
    target_scope: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Filter for documents to re-embed (tenant_id, source_types, etc.)",
    )

    # Multi-tenancy
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    # Error handling
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Statistics
    stats: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Job statistics: documents_processed, chunks_embedded, errors, etc.",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("ix_embedding_jobs_status", "status"),
        Index("ix_embedding_jobs_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<EmbeddingJob(id={self.id}, status='{self.status}', model='{self.embedding_model}')>"
        )


class RetrievalLog(Base):
    """
    Logs retrieval and ingestion events for debugging and evaluation.

    Supports both retrieval service queries and ingestion service events
    with OpenTelemetry trace context for distributed tracing.
    """

    __tablename__ = "retrieval_logs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Multi-tenancy
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Query information (for retrieval events)
    query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    effective_query: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Query after preprocessing/expansion",
    )

    # Retrieval results
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=True,
    )
    scores: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Scores for retrieved chunks",
    )
    filters_applied: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Filters used in the query",
    )

    # Performance metrics
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Ingestion-specific fields (US-2.12)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # OpenTelemetry trace context (US-2.12)
    trace_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="OpenTelemetry trace ID for distributed tracing",
    )
    span_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="OpenTelemetry span ID",
    )

    # Event classification (US-2.12)
    event_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Event type: ingestion, retrieval, evaluation",
    )
    event_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional event-specific metadata",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (Index("ix_retrieval_logs_tenant_created", "tenant_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<RetrievalLog(id={self.id}, tenant_id={self.tenant_id}, event_type='{self.event_type}')>"
