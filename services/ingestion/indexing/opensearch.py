"""OpenSearch writer for keyword index."""

import time
from datetime import UTC, datetime
from uuid import UUID

from opensearchpy import AsyncOpenSearch
from pydantic import BaseModel, Field

from shared.config.urls import get_opensearch_url

from .base import BaseIndexWriter
from .models import IndexedChunk, WriteResult


class OpenSearchWriterConfig(BaseModel):
    """Configuration for OpenSearchWriter."""

    hosts: list[str] = Field(default_factory=lambda: [get_opensearch_url()])
    username: str | None = None
    password: str | None = None
    index_name: str = "documents"

    # Index settings
    number_of_shards: int = 1
    number_of_replicas: int = 1

    # Bulk settings
    batch_size: int = 500

    # Timeout
    timeout: int = 30


class OpenSearchWriter(BaseIndexWriter):
    """Write chunks to OpenSearch for keyword search.

    Uses bulk API for efficient indexing. Supports BM25 keyword
    search with appropriate text mappings.
    """

    def __init__(self, config: OpenSearchWriterConfig | None = None):
        """Initialize OpenSearchWriter.

        Args:
            config: Configuration for the writer. Uses defaults if not provided.
        """
        self.config = config or OpenSearchWriterConfig()
        self._client: AsyncOpenSearch | None = None

    async def connect(self) -> None:
        """Establish connection to OpenSearch."""
        auth = None
        if self.config.username and self.config.password:
            auth = (self.config.username, self.config.password)

        self._client = AsyncOpenSearch(
            hosts=self.config.hosts,
            http_auth=auth,
            timeout=self.config.timeout,
        )

    async def disconnect(self) -> None:
        """Close connection to OpenSearch."""
        if self._client:
            await self._client.close()
            self._client = None

    async def ensure_index(self) -> None:
        """Create index with appropriate mappings."""
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        exists = await self._client.indices.exists(index=self.config.index_name)

        if not exists:
            mappings = {
                "settings": {
                    "number_of_shards": self.config.number_of_shards,
                    "number_of_replicas": self.config.number_of_replicas,
                    "analysis": {
                        "analyzer": {
                            "default": {"type": "standard"},
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "content": {
                            "type": "text",
                            "analyzer": "standard",
                        },
                        "chunk_index": {"type": "integer"},
                        "token_count": {"type": "integer"},
                        "tenant_id": {"type": "keyword"},
                        "visibility": {"type": "keyword"},
                        "allowed_groups": {"type": "keyword"},
                        "allowed_users": {"type": "keyword"},
                        "status": {"type": "keyword"},  # US-10.1.3: Status for deletion filtering
                        "source": {"type": "keyword"},
                        "source_uri": {"type": "keyword"},
                        "source_type": {"type": "keyword"},
                        "source_page": {"type": "integer"},
                        "source_section": {"type": "keyword"},
                        "parent_chunk_id": {"type": "keyword"},
                        "created_at": {"type": "date"},
                    },
                },
            }

            await self._client.indices.create(
                index=self.config.index_name,
                body=mappings,
            )

    async def write(
        self,
        chunks: list[IndexedChunk],
        index_name: str | None = None,
    ) -> WriteResult:
        """Bulk index chunks to OpenSearch.

        Uses index action (upsert) for idempotency.

        Args:
            chunks: List of IndexedChunk objects to write.
            index_name: Optional index override (uses config default if None).

        Returns:
            WriteResult with success status and counts.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_index = index_name or self.config.index_name
        start = time.time()

        # Prepare bulk actions
        actions: list[dict] = []
        for chunk in chunks:
            action = {
                "index": {"_index": target_index, "_id": str(chunk.chunk_id)},
            }
            # Extract source_uri from metadata for aliasing
            source_uri = chunk.metadata.get("source_uri", "")

            doc = {
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "tenant_id": chunk.tenant_id,
                "visibility": chunk.visibility,
                "allowed_groups": chunk.allowed_groups,
                "allowed_users": chunk.allowed_users,
                "status": chunk.status,  # US-10.1.3: Status for deletion filtering
                "created_at": datetime.now(tz=UTC).isoformat(),
                # Add 'source' alias for retrieval service compatibility
                "source": source_uri,
                **chunk.metadata,
            }

            if chunk.parent_chunk_id:
                doc["parent_chunk_id"] = str(chunk.parent_chunk_id)
            if chunk.source_page is not None:
                doc["source_page"] = chunk.source_page
            if chunk.source_section:
                doc["source_section"] = chunk.source_section

            actions.append(action)
            actions.append(doc)

        # Execute bulk in batches
        errors: list[str] = []
        items_written = 0
        items_per_batch = self.config.batch_size * 2  # action + doc pairs

        for i in range(0, len(actions), items_per_batch):
            batch = actions[i : i + items_per_batch]
            try:
                response = await self._client.bulk(body=batch, refresh=True)

                if response.get("errors"):
                    for item in response["items"]:
                        if "error" in item.get("index", {}):
                            errors.append(str(item["index"]["error"]))
                        else:
                            items_written += 1
                else:
                    items_written += len(batch) // 2

            except Exception as e:
                errors.append(f"Batch {i // items_per_batch}: {str(e)}")

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
        index_name: str | None = None,
    ) -> WriteResult:
        """Delete chunks by ID using bulk delete.

        Args:
            chunk_ids: List of chunk UUIDs to delete.
            index_name: Optional index override (uses config default if None).

        Returns:
            WriteResult with success status.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_index = index_name or self.config.index_name
        start = time.time()

        actions = []
        for chunk_id in chunk_ids:
            actions.append(
                {"delete": {"_index": target_index, "_id": str(chunk_id)}},
            )

        try:
            response = await self._client.bulk(body=actions, refresh=True)

            errors: list[str] = []
            if response.get("errors"):
                for item in response["items"]:
                    if "error" in item.get("delete", {}):
                        errors.append(str(item["delete"]["error"]))

            return WriteResult(
                success=len(errors) == 0,
                items_written=0,
                items_failed=len(errors),
                errors=errors,
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
        index_name: str | None = None,
    ) -> WriteResult:
        """Delete all chunks for a document using delete by query.

        Args:
            document_id: UUID of the document whose chunks should be deleted.
            index_name: Optional index override (uses config default if None).

        Returns:
            WriteResult with success status.
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        target_index = index_name or self.config.index_name
        start = time.time()

        try:
            await self._client.delete_by_query(
                index=target_index,
                body={"query": {"term": {"document_id": str(document_id)}}},
                refresh=True,
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
