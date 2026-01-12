"""Data models for index writers."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IndexedChunk(BaseModel):
    """Chunk ready for indexing with embedding.

    This model represents a document chunk that has been processed
    through chunking and embedding, ready to be written to the
    vector and keyword stores.
    """

    chunk_id: UUID
    document_id: UUID
    content: str
    embedding: list[float]
    chunk_index: int
    token_count: int

    # Parent-child for hierarchical retrieval
    parent_chunk_id: UUID | None = None

    # Source tracking
    source_page: int | None = None
    source_section: str | None = None

    # Versioning metadata (US-2.11)
    schema_version: str = "1.0"
    embedding_model: str | None = None
    embedding_version: str | None = None

    # Metadata for filtering
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ACL fields (architecture requirement)
    tenant_id: str
    visibility: str = "private"  # public, private, group
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)


class DocumentStatus(str, Enum):
    """Status of a document in the indexing pipeline."""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentRecord(BaseModel):
    """Document metadata for PostgreSQL.

    This model stores document-level metadata including source
    information, chunk statistics, versioning, and ACL settings.
    """

    document_id: UUID
    source_uri: str  # Renamed from source_id for US-2.11
    source_type: str
    filename: str | None = None
    mime_type: str | None = None
    title: str | None = None
    author: str | None = None

    chunk_count: int = 0
    total_tokens: int = 0

    # Deduplication and versioning (US-2.11)
    content_hash: str = ""  # SHA-256 hash of document content
    version: int = 1  # Document version, incremented on re-ingest

    # ACL
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    indexed_at: datetime | None = None

    # Status
    status: str = "pending"  # pending, indexed, failed, superseded
    error_message: str | None = None

    # Additional metadata
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteResult(BaseModel):
    """Result of a write operation.

    This model provides feedback on write operations including
    success/failure status, counts, and any errors encountered.
    """

    success: bool
    items_written: int
    items_failed: int
    errors: list[str] = Field(default_factory=list)
    duration_ms: float
