"""Document management API routes."""

import logging
from uuid import UUID

from api.dependencies import get_current_user, get_document_service
from api.schemas import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
    IngestResponse,
    ReindexRequest,
)
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="List all indexed documents with pagination and filtering.",
)
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    document_service=Depends(get_document_service),
    current_user: dict = Depends(get_current_user),
) -> DocumentListResponse:
    """
    List indexed documents.

    **Filters:**
    - `source_type`: Filter by source (filesystem, database, web, api)
    - `status`: Filter by status (pending, indexed, failed)
    - `search`: Search in title, filename, or source_id

    **Pagination:**
    - `page`: Page number (1-indexed)
    - `page_size`: Items per page (max 100)
    """
    tenant_id = current_user.get("tenant_id")

    result = await document_service.list_documents(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        source_type=source_type,
        status=status,
        search=search,
    )

    total_pages = (result.total + page_size - 1) // page_size if result.total > 0 else 1

    return DocumentListResponse(
        documents=result.documents,
        total=result.total,
        page=page,
        page_size=page_size,
        pages=total_pages,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document",
    description="Get metadata for a specific document.",
)
async def get_document(
    document_id: UUID,
    document_service=Depends(get_document_service),
    current_user: dict = Depends(get_current_user),
) -> DocumentResponse:
    """
    Get document metadata by ID.

    Returns document properties, chunk count, and indexing status.
    """
    tenant_id = current_user.get("tenant_id")

    document = await document_service.get_document(document_id, tenant_id)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    return document


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete document",
    description="Delete a document and all its chunks from the index.",
)
async def delete_document(
    document_id: UUID,
    hard_delete: bool = Query(
        default=True,
        description="If False, marks as deleted instead of removing",
    ),
    document_service=Depends(get_document_service),
    current_user: dict = Depends(get_current_user),
) -> DocumentDeleteResponse:
    """
    Delete a document and all associated chunks (cascade delete).

    This removes the document from:
    - PostgreSQL (metadata and chunk records)
    - Qdrant (vector embeddings)
    - OpenSearch (keyword index)
    - MinIO/S3 (original document file, if stored)

    **Deletion Strategy:**
    - `hard_delete=True`: Permanently removes all data (default)
    - `hard_delete=False`: Soft delete - marks as deleted but retains data

    **Cascade Order:**
    1. Mark document as "deleting" in PostgreSQL (prevents queries)
    2. Delete vectors from Qdrant by document_id filter
    3. Delete keyword index entries from OpenSearch
    4. Delete chunk records from PostgreSQL
    5. Delete document record from PostgreSQL
    6. Delete raw file from object storage (if applicable)

    This operation cannot be undone for hard deletes.
    """
    tenant_id = current_user.get("tenant_id")

    # Verify document exists and belongs to tenant
    document = await document_service.get_document(document_id, tenant_id)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    # Execute cascade delete
    result = await document_service.delete_document(document_id, hard_delete=hard_delete)

    message = (
        "Document deleted successfully" if result.success else f"Deletion failed: {result.error}"
    )

    return DocumentDeleteResponse(
        document_id=document_id,
        deleted=result.success,
        chunks_deleted=result.chunks_deleted,
        message=message,
    )


@router.post(
    "/{document_id}/reindex",
    response_model=IngestResponse,
    status_code=202,
    summary="Reindex document",
    description="Re-process and reindex an existing document.",
)
async def reindex_document(
    document_id: UUID,
    request: ReindexRequest | None = None,
    document_service=Depends(get_document_service),
    current_user: dict = Depends(get_current_user),
) -> IngestResponse:
    """
    Reindex an existing document.

    Useful when:
    - Chunking strategy changed
    - Embedding model updated
    - Document content was updated at source

    The document is re-fetched, re-processed, and re-indexed.
    """
    tenant_id = current_user.get("tenant_id")

    document = await document_service.get_document(document_id, tenant_id)

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    # Build processing config from request
    processing_config = None
    if request:
        processing_config = {k: v for k, v in request.model_dump().items() if v is not None}

    # Start reindex job
    task = await document_service.reindex_document(document_id, processing_config)

    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Reindexing started",
    )
