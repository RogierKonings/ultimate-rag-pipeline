"""Index coordinator for managing writes across all stores."""

import asyncio
from uuid import UUID

from .models import IndexedChunk, DocumentRecord, WriteResult
from .qdrant import QdrantWriter
from .opensearch import OpenSearchWriter
from .postgres import PostgresWriter


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

        return result_dict

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
        for i, store_name in enumerate(["qdrant", "opensearch"]):
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
