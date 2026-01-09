"""Pydantic schemas for document management API endpoints."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """Document metadata response.

    Per architecture.md GET /api/v1/documents/{id} response contract.
    """

    document_id: UUID
    source_id: str
    source_type: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    chunk_count: int
    total_tokens: int
    tenant_id: str
    visibility: str
    created_at: datetime
    updated_at: datetime
    indexed_at: Optional[datetime] = None
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
                }
            ]
        }
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
                        }
                    ],
                    "total": 150,
                    "page": 1,
                    "page_size": 20,
                    "pages": 8,
                }
            ]
        }
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
                }
            ]
        }
    )


class ReindexRequest(BaseModel):
    """Request to reindex a document with new chunking settings."""

    chunking_strategy: Optional[str] = None
    chunk_size: Optional[int] = Field(default=None, ge=100, le=4096)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=500)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "chunking_strategy": "recursive",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                }
            ]
        }
    )
