"""Pydantic schemas for document management API endpoints."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IndexStatusValue(str, Enum):
    """Indexing status values for stores."""

    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    STALE = "stale"


class DocumentResponse(BaseModel):
    """Document metadata response.

    Per architecture.md GET /api/v1/documents/{id} response contract.
    """

    document_id: UUID
    source_id: str
    source_type: str
    filename: str | None = None
    mime_type: str | None = None
    title: str | None = None
    author: str | None = None
    chunk_count: int
    total_tokens: int
    tenant_id: str
    visibility: str
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None
    status: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_id": "550e8400-e29b-41d4-a716-446655440000",
                    "source_id": "report-2025-q4.pdf",
                    "source_type": "filesystem",
                    "filename": "report-2025-q4.pdf",
                    "mime_type": "application/pdf",
                    "title": "Q4 2025 Financial Report",
                    "author": "John Doe",
                    "chunk_count": 45,
                    "total_tokens": 12500,
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
                    "visibility": "group",
                    "created_at": "2025-12-18T10:00:00Z",
                    "updated_at": "2025-12-18T10:05:00Z",
                    "indexed_at": "2025-12-18T10:05:30Z",
                    "status": "active",
                },
            ],
        },
    )


class DocumentListResponse(BaseModel):
    """Paginated document list response.

    Per architecture.md GET /api/v1/documents response contract.
    """

    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    pages: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "documents": [
                        {
                            "document_id": "550e8400-e29b-41d4-a716-446655440000",
                            "source_id": "report-2025-q4.pdf",
                            "source_type": "filesystem",
                            "filename": "report-2025-q4.pdf",
                            "mime_type": "application/pdf",
                            "title": "Q4 2025 Financial Report",
                            "chunk_count": 45,
                            "total_tokens": 12500,
                            "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
                            "visibility": "group",
                            "created_at": "2025-12-18T10:00:00Z",
                            "updated_at": "2025-12-18T10:05:00Z",
                            "status": "active",
                        },
                    ],
                    "total": 150,
                    "page": 1,
                    "page_size": 20,
                    "pages": 8,
                },
            ],
        },
    )


class DocumentDeleteResponse(BaseModel):
    """Response after deleting a document.

    Per architecture.md DELETE /api/v1/documents/{id} response contract.
    """

    document_id: UUID
    deleted: bool
    chunks_deleted: int
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_id": "550e8400-e29b-41d4-a716-446655440000",
                    "deleted": True,
                    "chunks_deleted": 45,
                    "message": "Document and 45 chunks deleted successfully",
                },
            ],
        },
    )


class ReindexRequest(BaseModel):
    """Request to reindex a document with new chunking settings."""

    chunking_strategy: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chunking_strategy": "recursive",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                },
            ],
        },
    )


class BatchDeleteRequest(BaseModel):
    """Request to delete multiple documents at once."""

    document_ids: list[UUID] = Field(..., min_length=1, max_length=100)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_ids": [
                        "550e8400-e29b-41d4-a716-446655440000",
                        "550e8400-e29b-41d4-a716-446655440001",
                    ],
                },
            ],
        },
    )


class BatchDeleteResponse(BaseModel):
    """Response after batch deleting documents."""

    deleted_count: int
    failed_count: int
    results: list[DocumentDeleteResponse]

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "deleted_count": 2,
                    "failed_count": 0,
                    "results": [
                        {
                            "document_id": "550e8400-e29b-41d4-a716-446655440000",
                            "deleted": True,
                            "chunks_deleted": 45,
                            "message": "Document deleted successfully",
                        },
                    ],
                },
            ],
        },
    )


# Sync Status Schemas (US-10.1.1)


class SyncStatusFilter(str, Enum):
    """Filter options for sync status queries."""

    ALL = "all"
    OK = "ok"
    ERROR = "error"
    PENDING = "pending"
    ANY_ERROR = "any_error"  # Any store not OK


class DocumentSyncStatus(BaseModel):
    """Individual document's sync status across all stores."""

    document_id: UUID
    source_id: str
    title: str | None = None
    qdrant_status: IndexStatusValue
    opensearch_status: IndexStatusValue
    last_indexed_at: datetime | None = None
    last_index_error: str | None = None
    index_attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "document_id": "550e8400-e29b-41d4-a716-446655440000",
                    "source_id": "report-2025-q4.pdf",
                    "title": "Q4 2025 Financial Report",
                    "qdrant_status": "ok",
                    "opensearch_status": "ok",
                    "last_indexed_at": "2025-12-18T10:05:30Z",
                    "last_index_error": None,
                    "index_attempts": 1,
                    "created_at": "2025-12-18T10:00:00Z",
                    "updated_at": "2025-12-18T10:05:30Z",
                },
            ],
        },
    )


class SyncStatusSummary(BaseModel):
    """Aggregated counts by status."""

    ok: int = Field(description="Documents where both stores are OK")
    pending: int = Field(description="Documents with at least one store pending")
    error: int = Field(description="Documents with at least one store in error")
    stale: int = Field(description="Documents with at least one store stale")


class SyncStatusResponse(BaseModel):
    """Response for sync status query."""

    summary: SyncStatusSummary
    documents: list[DocumentSyncStatus]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "summary": {"ok": 145, "pending": 2, "error": 3, "stale": 0},
                    "documents": [
                        {
                            "document_id": "550e8400-e29b-41d4-a716-446655440000",
                            "source_id": "report-2025-q4.pdf",
                            "title": "Q4 2025 Financial Report",
                            "qdrant_status": "error",
                            "opensearch_status": "ok",
                            "last_indexed_at": None,
                            "last_index_error": "Qdrant: Connection refused",
                            "index_attempts": 3,
                            "created_at": "2025-12-18T10:00:00Z",
                            "updated_at": "2025-12-18T10:05:30Z",
                        },
                    ],
                    "total": 3,
                    "limit": 100,
                    "offset": 0,
                },
            ],
        },
    )
