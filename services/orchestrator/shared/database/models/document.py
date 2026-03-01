"""
Document and Chunk models for storing document metadata and chunked content.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin


class IndexStatus(StrEnum):
    """Indexing status for external stores (Qdrant, OpenSearch)."""

    PENDING = "pending"  # Indexing not yet attempted or in progress
    OK = "ok"  # Successfully indexed
    ERROR = "error"  # Indexing failed (see last_index_error)
    STALE = "stale"  # Document updated, needs re-indexing


class Document(Base, TimestampMixin, SoftDeleteMixin):
    """
    Represents a source document in the RAG pipeline.

    Stores metadata about ingested documents including source information,
    content hash for deduplication, and access control settings.
    """

    __tablename__ = "documents"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Source identification
    source_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="External identifier for the source (e.g., file path, URL)",
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of source: FILE, WEB, DB, API",
    )

    # Document metadata
    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of document content for deduplication",
    )
    doc_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional document metadata (author, keywords, etc.)",
    )

    # Multi-tenancy and access control
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(20),
        default="private",
        nullable=False,
        comment="Visibility: public, private, group",
    )
    allowed_groups: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
        comment="List of group UUIDs with access",
    )

    # Indexing status tracking
    qdrant_status: Mapped[IndexStatus] = mapped_column(
        SQLEnum(IndexStatus, name="index_status", create_constraint=True),
        default=IndexStatus.PENDING,
        nullable=False,
        index=True,
        comment="Qdrant vector store indexing status",
    )
    opensearch_status: Mapped[IndexStatus] = mapped_column(
        SQLEnum(IndexStatus, name="index_status", create_constraint=True),
        default=IndexStatus.PENDING,
        nullable=False,
        index=True,
        comment="OpenSearch keyword index status",
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last successful indexing to any store",
    )
    last_index_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last indexing error message for debugging",
    )
    index_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of indexing attempts (for exponential backoff)",
    )

    # Relationships
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Indexes
    __table_args__ = (
        Index("ix_documents_source_id", "source_id"),
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        Index(
            "ix_documents_sync_status",
            "tenant_id",
            "qdrant_status",
            "opensearch_status",
            postgresql_where="status = 'active'",
        ),
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title}', source_type={self.source_type})>"


class Chunk(Base, SoftDeleteMixin):
    """
    Represents a chunk of a document for vector search.

    Chunks are the atomic units for embedding and retrieval,
    linked to their parent document.
    """

    __tablename__ = "chunks"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Document relationship
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="chunks",
    )

    # Chunk content
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Order of this chunk within the document (0-indexed)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The actual text content of this chunk",
    )
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of tokens in this chunk",
    )

    # Embedding metadata
    embedding_model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Model used to generate embeddings",
    )
    embedding_version: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Version of the embedding model",
    )

    # Additional metadata
    chunk_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Chunk-specific metadata (section heading, page number, etc.)",
    )

    # Multi-tenancy (denormalized for query performance)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        nullable=False,
    )

    # Indexes
    __table_args__ = (
        Index("ix_chunks_document_chunk", "document_id", "chunk_index", unique=True),
        Index("ix_chunks_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Chunk(id={self.id}, document_id={self.document_id}, index={self.chunk_index})>"
