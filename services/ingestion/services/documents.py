"""Document management service with cascade delete operations."""

import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class DeleteResult:
    """Result of a document delete operation."""

    success: bool
    chunks_deleted: int
    vectors_deleted: int
    keyword_entries_deleted: int
    error: str | None = None


class DocumentListResult(BaseModel):
    """Result of listing documents."""

    documents: list[Any]
    total: int


class DocumentService:
    """Service for managing documents with cascade operations."""

    def __init__(self):
        """Initialize the document service."""
        self._db = None
        self._qdrant = None
        self._opensearch = None
        self._storage = None

    async def connect(self) -> None:
        """Connect to all required services."""
        # Lazy import to avoid circular imports
        from config import get_settings

        settings = get_settings()

        # Database connection
        try:
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
            from sqlalchemy.orm import sessionmaker

            engine = create_async_engine(
                settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
                echo=settings.debug,
            )
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            self._db = async_session()
        except Exception as e:
            logger.warning(f"Database connection failed: {e}")

        # Qdrant connection
        try:
            from qdrant_client import AsyncQdrantClient

            self._qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        except Exception as e:
            logger.warning(f"Qdrant connection failed: {e}")

        # OpenSearch connection
        try:
            from opensearchpy import AsyncOpenSearch

            self._opensearch = AsyncOpenSearch(
                hosts=[settings.opensearch_url],
                use_ssl=False,
            )
        except Exception as e:
            logger.warning(f"OpenSearch connection failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from all services."""
        if self._db:
            await self._db.close()
        if self._qdrant:
            await self._qdrant.close()
        if self._opensearch:
            await self._opensearch.close()

    async def list_documents(
        self,
        tenant_id: str,
        page: int = 1,
        page_size: int = 20,
        source_type: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> DocumentListResult:
        """
        List documents with pagination and filtering.

        Args:
            tenant_id: Tenant to filter by.
            page: Page number (1-indexed).
            page_size: Items per page.
            source_type: Optional source type filter.
            status: Optional status filter.
            search: Optional search term.

        Returns:
            DocumentListResult with documents and total count.
        """
        if not self._db:
            return DocumentListResult(documents=[], total=0)

        try:
            from sqlalchemy import text

            from api.schemas import DocumentResponse

            # Build dynamic WHERE clause for indexed_documents table
            conditions = ["tenant_id = :tenant_id"]
            params = {"tenant_id": tenant_id}

            if source_type:
                conditions.append("source_type = :source_type")
                params["source_type"] = source_type

            if status:
                conditions.append("status = :status")
                params["status"] = status

            if search:
                conditions.append("(title ILIKE :search OR source_uri ILIKE :search OR filename ILIKE :search)")
                params["search"] = f"%{search}%"

            where_clause = " AND ".join(conditions)

            # Get total count
            count_query = text(f"SELECT COUNT(*) FROM indexed_documents WHERE {where_clause}")
            count_result = await self._db.execute(count_query, params)
            total = count_result.scalar() or 0

            # Get paginated results
            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset

            query = text(f"""
                SELECT document_id, source_uri, source_type, filename, mime_type,
                       title, author, chunk_count, total_tokens, content_hash, version,
                       tenant_id, visibility, allowed_groups, allowed_users, created_at,
                       updated_at, indexed_at, status, error_message
                FROM indexed_documents
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """)

            result = await self._db.execute(query, params)
            rows = result.fetchall()

            # Convert to response format
            doc_responses = []
            for row in rows:
                doc_responses.append(
                    DocumentResponse(
                        document_id=row.document_id,
                        source_id=row.source_uri,
                        source_type=row.source_type,
                        filename=row.filename,
                        mime_type=row.mime_type,
                        title=row.title,
                        author=row.author,
                        chunk_count=row.chunk_count or 0,
                        total_tokens=row.total_tokens or 0,
                        tenant_id=str(row.tenant_id),
                        visibility=row.visibility,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        indexed_at=row.indexed_at,
                        status=row.status,
                    ),
                )

            return DocumentListResult(documents=doc_responses, total=total)

        except Exception as e:
            logger.error(f"Failed to list documents: {e}")
            return DocumentListResult(documents=[], total=0)

    async def get_document(
        self,
        document_id: UUID,
        tenant_id: str,
    ) -> Any | None:
        """
        Get document by ID.

        Args:
            document_id: Document UUID.
            tenant_id: Tenant ID for access control.

        Returns:
            DocumentResponse or None if not found.
        """
        if not self._db:
            return None

        try:
            from sqlalchemy import func, select

            from services.shared.database.models.document import Chunk, Document

            query = select(Document).where(
                Document.id == document_id,
                Document.tenant_id == UUID(tenant_id),
            )
            result = await self._db.execute(query)
            doc = result.scalar_one_or_none()

            if not doc:
                return None

            # Get chunk count
            chunk_query = select(func.count()).where(Chunk.document_id == doc.id)
            chunk_result = await self._db.execute(chunk_query)
            chunk_count = chunk_result.scalar() or 0

            # Get total tokens
            token_query = select(func.sum(Chunk.token_count)).where(Chunk.document_id == doc.id)
            token_result = await self._db.execute(token_query)
            total_tokens = token_result.scalar() or 0

            from api.schemas import DocumentResponse

            return DocumentResponse(
                document_id=doc.id,
                source_id=doc.source_id,
                source_type=doc.source_type,
                filename=doc.doc_metadata.get("filename"),
                mime_type=doc.doc_metadata.get("mime_type"),
                title=doc.title,
                author=doc.doc_metadata.get("author"),
                chunk_count=chunk_count,
                total_tokens=total_tokens,
                tenant_id=str(doc.tenant_id),
                visibility=doc.visibility,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                indexed_at=doc.doc_metadata.get("indexed_at"),
                status=doc.status,
            )

        except Exception as e:
            logger.error(f"Failed to get document: {e}")
            return None

    async def delete_document(
        self,
        document_id: UUID,
        hard_delete: bool = True,
    ) -> DeleteResult:
        """
        Delete document with cascade to all data stores.

        Uses a transactional approach:
        1. If any step fails, attempt rollback where possible
        2. Log all operations for audit trail
        3. Return detailed result for observability

        Args:
            document_id: Document UUID to delete.
            hard_delete: If True, permanently removes data. If False, soft delete.

        Returns:
            DeleteResult with operation status.
        """
        chunks_deleted = 0
        vectors_deleted = 0
        keyword_entries_deleted = 0

        try:
            # Step 1: Mark document as deleting (prevents new queries)
            await self._mark_document_deleting(document_id)
            logger.info(f"Document {document_id} marked as deleting")

            # Step 2: Get all chunk IDs for this document
            chunk_ids = await self._get_chunk_ids(document_id)
            logger.info(f"Found {len(chunk_ids)} chunks for document {document_id}")

            # Step 3: Delete vectors from Qdrant
            try:
                vectors_deleted = await self._delete_vectors(document_id, chunk_ids)
                logger.info(f"Deleted {vectors_deleted} vectors from Qdrant")
            except Exception as e:
                logger.error(f"Failed to delete vectors: {e}")
                # Continue with other deletions - vectors can be orphaned

            # Step 4: Delete keyword entries from OpenSearch
            try:
                keyword_entries_deleted = await self._delete_keyword_entries(
                    document_id,
                    chunk_ids,
                )
                logger.info(f"Deleted {keyword_entries_deleted} entries from OpenSearch")
            except Exception as e:
                logger.error(f"Failed to delete keyword entries: {e}")
                # Continue with other deletions

            # Step 5: Delete chunks from PostgreSQL
            if hard_delete:
                chunks_deleted = await self._hard_delete_chunks(document_id)
            else:
                chunks_deleted = await self._soft_delete_chunks(document_id)
            logger.info(f"Deleted {chunks_deleted} chunks from PostgreSQL")

            # Step 6: Delete document record from PostgreSQL
            if hard_delete:
                await self._hard_delete_document(document_id)
            else:
                await self._soft_delete_document(document_id)
            logger.info(f"Deleted document record {document_id}")

            # Step 7: Delete raw file from object storage (if exists)
            try:
                await self._delete_raw_file(document_id)
            except Exception as e:
                logger.warning(f"Failed to delete raw file (may not exist): {e}")

            # Commit transaction
            if self._db:
                await self._db.commit()

            return DeleteResult(
                success=True,
                chunks_deleted=chunks_deleted,
                vectors_deleted=vectors_deleted,
                keyword_entries_deleted=keyword_entries_deleted,
            )

        except Exception as e:
            logger.error(f"Document deletion failed: {e}")
            if self._db:
                await self._db.rollback()

            # Attempt to restore document status
            with contextlib.suppress(Exception):
                await self._restore_document_status(document_id)

            return DeleteResult(
                success=False,
                chunks_deleted=0,
                vectors_deleted=0,
                keyword_entries_deleted=0,
                error=str(e),
            )

    async def reindex_document(
        self,
        document_id: UUID,
        processing_config: dict | None = None,
    ):
        """
        Trigger document reindexing.

        Args:
            document_id: Document UUID to reindex.
            processing_config: Optional override for processing options.

        Returns:
            Celery task result.
        """
        from tasks.ingest import process_document

        # Get document to find source info
        if self._db:
            from sqlalchemy import select

            from services.shared.database.models.document import Document

            query = select(Document).where(Document.id == document_id)
            result = await self._db.execute(query)
            doc = result.scalar_one_or_none()

            if doc:
                return process_document.delay(
                    document_source_id=doc.source_id,
                    source_type=doc.source_type,
                    source_config=doc.doc_metadata.get("source_config", {}),
                    processing_config=processing_config or {},
                    acl_context={
                        "tenant_id": str(doc.tenant_id),
                        "visibility": doc.visibility,
                        "allowed_groups": doc.allowed_groups or [],
                    },
                )

        raise ValueError(f"Document {document_id} not found")

    # Private helper methods

    async def _mark_document_deleting(self, document_id: UUID) -> None:
        """Mark document as deleting to prevent queries."""
        if not self._db:
            return

        from sqlalchemy import update

        from services.shared.database.models.document import Document

        await self._db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status="deleting", updated_at=datetime.now(tz=UTC)),
        )

    async def _get_chunk_ids(self, document_id: UUID) -> list[UUID]:
        """Get all chunk IDs for a document."""
        if not self._db:
            return []

        from sqlalchemy import select

        from services.shared.database.models.document import Chunk

        result = await self._db.execute(
            select(Chunk.id).where(Chunk.document_id == document_id),
        )
        return [row[0] for row in result.fetchall()]

    async def _delete_vectors(
        self,
        document_id: UUID,
        chunk_ids: list[UUID],
    ) -> int:
        """Delete vectors from Qdrant using document_id filter."""
        if not self._qdrant:
            return 0

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # Delete by document_id filter (more efficient than individual deletes)
        await self._qdrant.delete(
            collection_name="rag_chunks",
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id)),
                    ),
                ],
            ),
        )

        return len(chunk_ids)  # Qdrant doesn't return count

    async def _delete_keyword_entries(
        self,
        document_id: UUID,
        chunk_ids: list[UUID],
    ) -> int:
        """Delete entries from OpenSearch index."""
        if not self._opensearch:
            return 0

        # Delete by query matching document_id
        response = await self._opensearch.delete_by_query(
            index="rag_chunks",
            body={"query": {"term": {"document_id": str(document_id)}}},
        )

        return response.get("deleted", 0)

    async def _hard_delete_chunks(self, document_id: UUID) -> int:
        """Hard delete chunks from PostgreSQL."""
        if not self._db:
            return 0

        from sqlalchemy import delete

        from services.shared.database.models.document import Chunk

        result = await self._db.execute(
            delete(Chunk).where(Chunk.document_id == document_id),
        )
        return result.rowcount

    async def _soft_delete_chunks(self, document_id: UUID) -> int:
        """Soft delete chunks by marking them as deleted."""
        if not self._db:
            return 0

        from sqlalchemy import update

        from services.shared.database.models.document import Chunk

        result = await self._db.execute(
            update(Chunk)
            .where(Chunk.document_id == document_id)
            .values(status="deleted", deleted_at=datetime.now(tz=UTC)),
        )
        return result.rowcount

    async def _hard_delete_document(self, document_id: UUID) -> None:
        """Hard delete document from PostgreSQL."""
        if not self._db:
            return

        from sqlalchemy import delete

        from services.shared.database.models.document import Document

        await self._db.execute(delete(Document).where(Document.id == document_id))

    async def _soft_delete_document(self, document_id: UUID) -> None:
        """Soft delete document by marking it as deleted."""
        if not self._db:
            return

        from sqlalchemy import update

        from services.shared.database.models.document import Document

        await self._db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                status="deleted",
                deleted_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            ),
        )

    async def _delete_raw_file(self, document_id: UUID) -> None:
        """Delete original document from object storage."""
        if not self._db:
            return

        from sqlalchemy import select

        from services.shared.database.models.document import Document

        # Get document to find raw_storage_path
        result = await self._db.execute(
            select(Document.doc_metadata).where(Document.id == document_id),
        )
        metadata = result.scalar_one_or_none()

        if metadata and metadata.get("raw_storage_path") and self._storage:
            # Delete from storage (implementation depends on storage client)
            await self._storage.delete(metadata["raw_storage_path"])

    async def _restore_document_status(self, document_id: UUID) -> None:
        """Restore document status after failed deletion."""
        if not self._db:
            return

        from sqlalchemy import update

        from services.shared.database.models.document import Document

        await self._db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status="indexed", updated_at=datetime.now(tz=UTC)),
        )
        await self._db.commit()
