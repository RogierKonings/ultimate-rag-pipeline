"""Qdrant writer for vector store indexing."""

import time
from uuid import UUID

from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient

from shared.config.urls import get_qdrant_url
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    OptimizersConfigDiff,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from .base import BaseIndexWriter
from .models import IndexedChunk, WriteResult


class QdrantWriterConfig(BaseModel):
    """Configuration for QdrantWriter."""

    url: str = Field(default_factory=get_qdrant_url)
    api_key: str | None = None
    collection_name: str = "documents"
    vector_size: int = 1024  # BGE-large dimensions
    distance: str = "Cosine"

    # HNSW parameters for quality/speed tradeoff
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100

    # Batch settings
    batch_size: int = 100

    # Timeout
    timeout: float = 60.0


class QdrantWriter(BaseIndexWriter):
    """Write vectors and metadata to Qdrant.

    Supports:
    - Upsert (idempotent writes)
    - Bulk operations
    - ACL filtering via payload
    - Payload indices for efficient filtering
    """

    def __init__(self, config: QdrantWriterConfig | None = None):
        """Initialize QdrantWriter.

        Args:
            config: Configuration for the writer. Uses defaults if not provided.
        """
        self.config = config or QdrantWriterConfig()
        self._client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        """Establish connection to Qdrant."""
        self._client = AsyncQdrantClient(
            url=self.config.url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    async def disconnect(self) -> None:
        """Close connection to Qdrant."""
        if self._client:
            await self._client.close()
            self._client = None

    async def ensure_index(self) -> None:
        """Create collection if it doesn't exist."""
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        collections = await self._client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if self.config.collection_name not in collection_names:
            await self._client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=Distance[self.config.distance.upper()],
                ),
                hnsw_config=HnswConfigDiff(
                    m=self.config.hnsw_m,
                    ef_construct=self.config.hnsw_ef_construct,
                ),
                optimizers_config=OptimizersConfigDiff(indexing_threshold=20000),
            )

            # Create payload indices for filtering
            await self._create_payload_indices()

    async def _create_payload_indices(self) -> None:
        """Create indices on filterable fields."""
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        filterable_fields = [
            "document_id",
            "tenant_id",
            "visibility",
            "allowed_groups",
            "allowed_users",
            "source_type",
            "status",  # US-10.1.3: Filter deleted documents
        ]

        for field in filterable_fields:
            await self._client.create_payload_index(
                collection_name=self.config.collection_name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

    async def write(
        self,
        chunks: list[IndexedChunk],
        collection_name: str | None = None,
    ) -> WriteResult:
        """Upsert chunks to Qdrant.

        Uses upsert for idempotency - same chunk_id will be updated.

        Args:
            chunks: List of IndexedChunk objects to write.
            collection_name: Optional collection override (uses config default if None).

        Returns:
            WriteResult with success status and counts.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_collection = collection_name or self.config.collection_name
        start = time.time()

        points = []
        for chunk in chunks:
            # Extract source_uri from metadata for aliasing
            source_uri = chunk.metadata.get("source_uri", "")

            payload = {
                "document_id": str(chunk.document_id),
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "tenant_id": chunk.tenant_id,
                "visibility": chunk.visibility,
                "allowed_groups": chunk.allowed_groups,
                "allowed_users": chunk.allowed_users,
                "status": chunk.status,  # US-10.1.3: Status for deletion filtering
                # Add 'source' alias for retrieval service compatibility
                "source": source_uri,
                **chunk.metadata,
            }

            if chunk.parent_chunk_id:
                payload["parent_chunk_id"] = str(chunk.parent_chunk_id)
            if chunk.source_page is not None:
                payload["source_page"] = chunk.source_page
            if chunk.source_section:
                payload["source_section"] = chunk.source_section

            points.append(
                PointStruct(
                    id=str(chunk.chunk_id),
                    vector=chunk.embedding,
                    payload=payload,
                ),
            )

        # Batch upsert
        errors: list[str] = []
        items_written = 0

        for i in range(0, len(points), self.config.batch_size):
            batch = points[i : i + self.config.batch_size]
            try:
                await self._client.upsert(
                    collection_name=target_collection,
                    points=batch,
                    wait=True,
                )
                items_written += len(batch)
            except Exception as e:
                errors.append(f"Batch {i // self.config.batch_size}: {str(e)}")

        duration = (time.time() - start) * 1000

        return WriteResult(
            success=len(errors) == 0,
            items_written=items_written,
            items_failed=len(chunks) - items_written,
            errors=errors,
            duration_ms=duration,
        )

    async def delete(
        self,
        chunk_ids: list[UUID],
        collection_name: str | None = None,
    ) -> WriteResult:
        """Delete chunks by ID.

        Args:
            chunk_ids: List of chunk UUIDs to delete.
            collection_name: Optional collection override (uses config default if None).

        Returns:
            WriteResult with success status.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_collection = collection_name or self.config.collection_name
        start = time.time()

        try:
            await self._client.delete(
                collection_name=target_collection,
                points_selector=[str(chunk_id) for chunk_id in chunk_ids],
                wait=True,
            )

            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=len(chunk_ids),
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000,
            )

    async def delete_by_document(
        self,
        document_id: UUID,
        collection_name: str | None = None,
    ) -> WriteResult:
        """Delete all chunks for a document.

        Args:
            document_id: UUID of the document whose chunks should be deleted.
            collection_name: Optional collection override (uses config default if None).

        Returns:
            WriteResult with success status.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_collection = collection_name or self.config.collection_name
        start = time.time()

        try:
            await self._client.delete(
                collection_name=target_collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=str(document_id)),
                        ),
                    ],
                ),
                wait=True,
            )

            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=1,
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000,
            )
