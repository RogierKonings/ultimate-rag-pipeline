"""Index coordinator for managing writes across all stores."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from .models import DocumentRecord, IndexedChunk, WriteResult
from .opensearch import OpenSearchWriter
from .postgres import PostgresWriter
from .qdrant import QdrantWriter

logger = logging.getLogger(__name__)


class IndexCoordinator:
    """Coordinates writes to all index stores.

    Ensures consistency across Qdrant, OpenSearch, and PostgreSQL.
    Writes are performed in parallel for efficiency, and document
    status is updated based on the results.
    """

    def __init__(
        self,
        qdrant: QdrantWriter,
        opensearch: OpenSearchWriter,
        postgres: PostgresWriter,
    ):
        """Initialize IndexCoordinator.

        Args:
            qdrant: QdrantWriter instance for vector store.
            opensearch: OpenSearchWriter instance for keyword store.
            postgres: PostgresWriter instance for metadata store.
        """
        self.qdrant = qdrant
        self.opensearch = opensearch
        self.postgres = postgres

    async def ensure_indices(self) -> None:
        """Create all indices/tables.

        Creates indices in all three stores in parallel.
        """
        await asyncio.gather(
            self.qdrant.ensure_index(),
            self.opensearch.ensure_index(),
            self.postgres.ensure_index(),
        )

    async def index_document(
        self,
        document: DocumentRecord,
        chunks: list[IndexedChunk],
    ) -> dict[str, WriteResult]:
        """Index a document and its chunks to all stores.

        Writes to all stores in parallel, then updates document status.
        The document record is written to PostgreSQL, while chunks are
        written to both Qdrant (vectors) and OpenSearch (keywords).

        Args:
            document: DocumentRecord with document metadata.
            chunks: List of IndexedChunk objects to index.

        Returns:
            Dictionary mapping store names to their WriteResult.
        """
        # Set index status to PENDING before starting
        await self._set_pending_status(document.document_id)

        # Write to all stores in parallel
        results = await asyncio.gather(
            self.qdrant.write(chunks),
            self.opensearch.write(chunks),
            self.postgres.write([document]),
            return_exceptions=True,
        )

        qdrant_result, opensearch_result, postgres_result = results

        # Handle exceptions and convert to WriteResult
        result_dict: dict[str, WriteResult] = {
            "qdrant": (
                qdrant_result
                if not isinstance(qdrant_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=len(chunks),
                    errors=[str(qdrant_result)],
                    duration_ms=0,
                )
            ),
            "opensearch": (
                opensearch_result
                if not isinstance(opensearch_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=len(chunks),
                    errors=[str(opensearch_result)],
                    duration_ms=0,
                )
            ),
            "postgres": (
                postgres_result
                if not isinstance(postgres_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=1,
                    errors=[str(postgres_result)],
                    duration_ms=0,
                )
            ),
        }

        # Update document status based on results
        all_success = all(r.success for r in result_dict.values())
        status = "indexed" if all_success else "failed"
        error_msg = (
            None
            if all_success
            else "; ".join(
                f"{store}: {r.errors}" for store, r in result_dict.items() if not r.success
            )
        )

        await self.postgres.update_status(document.document_id, status, error_msg)

        # Update index status tracking in the main documents table
        await self._update_index_status(
            document_id=document.document_id,
            qdrant_success=result_dict["qdrant"].success,
            opensearch_success=result_dict["opensearch"].success,
            errors=error_msg,
        )

        return result_dict

    async def _update_index_status(
        self,
        document_id: UUID,
        qdrant_success: bool,
        opensearch_success: bool,
        errors: str | None = None,
    ) -> None:
        """Update index status in the main documents table.

        This method updates the qdrant_status and opensearch_status fields
        in the documents table (managed by SQLAlchemy) to track indexing
        state across all stores.

        Args:
            document_id: UUID of the document to update.
            qdrant_success: Whether Qdrant indexing succeeded.
            opensearch_success: Whether OpenSearch indexing succeeded.
            errors: Combined error message if any store failed.
        """
        from database.models.document import IndexStatus

        # Determine status for each store
        qdrant_status = IndexStatus.OK if qdrant_success else IndexStatus.ERROR
        opensearch_status = IndexStatus.OK if opensearch_success else IndexStatus.ERROR

        # Update timestamp only if both succeeded
        last_indexed_at = datetime.now(UTC) if (qdrant_success and opensearch_success) else None

        # Use the postgres writer's pool to update the documents table
        if not self.postgres._pool:
            logger.warning(
                "Cannot update index status: PostgreSQL pool not connected",
                extra={"document_id": str(document_id)},
            )
            return

        try:
            async with self.postgres._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE documents
                    SET qdrant_status = $1,
                        opensearch_status = $2,
                        last_indexed_at = COALESCE($3, last_indexed_at),
                        last_index_error = $4,
                        index_attempts = index_attempts + 1,
                        updated_at = NOW()
                    WHERE id = $5
                    """,
                    qdrant_status.value,
                    opensearch_status.value,
                    last_indexed_at,
                    errors,
                    document_id,
                )
                logger.info(
                    "index_status_updated",
                    extra={
                        "document_id": str(document_id),
                        "qdrant_status": qdrant_status.value,
                        "opensearch_status": opensearch_status.value,
                    },
                )
        except Exception as e:
            # Log but don't fail the operation - status tracking is secondary
            logger.error(
                "index_status_update_failed",
                extra={"document_id": str(document_id), "error": str(e)},
            )

    async def _set_pending_status(self, document_id: UUID) -> None:
        """Set index status to PENDING before indexing starts.

        Args:
            document_id: UUID of the document being indexed.
        """
        from database.models.document import IndexStatus

        if not self.postgres._pool:
            return

        try:
            async with self.postgres._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE documents
                    SET qdrant_status = $1,
                        opensearch_status = $1,
                        updated_at = NOW()
                    WHERE id = $2
                    """,
                    IndexStatus.PENDING.value,
                    document_id,
                )
        except Exception as e:
            logger.warning(
                "set_pending_status_failed",
                extra={"document_id": str(document_id), "error": str(e)},
            )

    async def delete_document(self, document_id: UUID) -> dict[str, WriteResult]:
        """Delete document from all stores.

        Removes the document metadata from PostgreSQL and all associated
        chunks from Qdrant and OpenSearch.

        Args:
            document_id: UUID of the document to delete.

        Returns:
            Dictionary mapping store names to their WriteResult.
        """
        results = await asyncio.gather(
            self.qdrant.delete_by_document(document_id),
            self.opensearch.delete_by_document(document_id),
            self.postgres.delete([document_id]),
            return_exceptions=True,
        )

        qdrant_result, opensearch_result, postgres_result = results

        return {
            "qdrant": (
                qdrant_result
                if not isinstance(qdrant_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=1,
                    errors=[str(qdrant_result)],
                    duration_ms=0,
                )
            ),
            "opensearch": (
                opensearch_result
                if not isinstance(opensearch_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=1,
                    errors=[str(opensearch_result)],
                    duration_ms=0,
                )
            ),
            "postgres": (
                postgres_result
                if not isinstance(postgres_result, Exception)
                else WriteResult(
                    success=False,
                    items_written=0,
                    items_failed=1,
                    errors=[str(postgres_result)],
                    duration_ms=0,
                )
            ),
        }

    async def reindex_document(
        self,
        document: DocumentRecord,
        chunks: list[IndexedChunk],
    ) -> dict[str, WriteResult]:
        """Re-index a document by deleting existing chunks and writing new ones.

        This is a two-step operation: first delete all existing chunks
        for the document, then write the new chunks. Useful when document
        content has changed or embedding model has been updated.

        Args:
            document: DocumentRecord with updated document metadata.
            chunks: List of new IndexedChunk objects to index.

        Returns:
            Dictionary mapping store names to their WriteResult.
        """
        # First delete existing chunks from vector and keyword stores
        delete_results = await asyncio.gather(
            self.qdrant.delete_by_document(document.document_id),
            self.opensearch.delete_by_document(document.document_id),
            return_exceptions=True,
        )

        # Log any delete errors but continue with indexing
        for i, _store_name in enumerate(["qdrant", "opensearch"]):
            if isinstance(delete_results[i], Exception):
                # Log warning but continue
                pass

        # Now index the new chunks
        return await self.index_document(document, chunks)

    async def connect_all(self) -> None:
        """Connect to all stores.

        Establishes connections to Qdrant, OpenSearch, and PostgreSQL
        in parallel.
        """
        await asyncio.gather(
            self.qdrant.connect(),
            self.opensearch.connect(),
            self.postgres.connect(),
        )

    async def disconnect_all(self) -> None:
        """Disconnect from all stores.

        Closes connections to all stores in parallel.
        """
        await asyncio.gather(
            self.qdrant.disconnect(),
            self.opensearch.disconnect(),
            self.postgres.disconnect(),
        )

    async def __aenter__(self) -> "IndexCoordinator":
        """Enter async context manager."""
        await self.connect_all()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        await self.disconnect_all()
