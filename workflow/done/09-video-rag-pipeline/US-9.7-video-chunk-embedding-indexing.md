# US-9.7: Video Chunk Embedding and Indexing

> **Story ID:** US-9.7
> **Epic:** Video RAG Pipeline
> **Priority:** Critical
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.6 (Content Fusion), US-2.4 (Embedding Service), US-2.5 (Index Writers)

## User Story

**As a** system
**I want** to embed and index video chunks
**So that** they are searchable via hybrid retrieval

## Context

After content fusion creates video chunks with `fused_text`, these chunks need to be embedded and indexed for retrieval. This follows the same patterns as document chunk indexing but uses a dedicated `video_chunks` collection in Qdrant and index in OpenSearch. The embedding captures the semantic meaning of the combined multi-modal content.

## Technical Requirements

### Video Chunk Embedder

```python
# processors/video/embedding.py
from dataclasses import dataclass, field
from uuid import UUID
import logging
from typing import Callable

logger = logging.getLogger(__name__)

@dataclass
class EmbeddingResult:
    success: bool
    embedded_count: int = 0
    failed_count: int = 0
    error: str | None = None

@dataclass
class ChunkEmbedding:
    chunk_id: UUID
    video_id: UUID
    chunk_index: int
    embedding: list[float]
    fused_text: str
    start_time_ms: int
    end_time_ms: int

class VideoChunkEmbedder:
    """Generates embeddings for video chunks using BGE-large."""

    def __init__(self, embedding_service):
        self.embedding_service = embedding_service

    async def embed_chunks(
        self,
        chunks: list["VideoChunk"],
        batch_size: int = 32,
        progress_callback: Callable[[int, int], None] | None = None
    ) -> tuple[list[ChunkEmbedding], EmbeddingResult]:
        """
        Generate embeddings for video chunks.

        Uses the same embedding model as document chunks (BGE-large-en-v1.5).
        Documents are embedded WITHOUT instruction prefix.
        """
        embeddings = []
        failed = 0
        completed = 0

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]

            # Get texts to embed
            texts = [chunk.fused_text for chunk in batch]

            try:
                # Call embedding service (batch)
                vectors = await self.embedding_service.embed_documents(texts)

                for chunk, vector in zip(batch, vectors):
                    embeddings.append(ChunkEmbedding(
                        chunk_id=chunk.id if hasattr(chunk, 'id') else None,
                        video_id=chunk.video_id,
                        chunk_index=chunk.chunk_index,
                        embedding=vector,
                        fused_text=chunk.fused_text,
                        start_time_ms=chunk.start_time_ms,
                        end_time_ms=chunk.end_time_ms
                    ))

            except Exception as e:
                logger.error(f"Embedding batch failed: {e}")
                failed += len(batch)
                continue

            completed += len(batch)
            if progress_callback:
                progress_callback(completed, len(chunks))

        logger.info(f"Embedded {len(embeddings)} chunks, {failed} failed")

        return embeddings, EmbeddingResult(
            success=failed == 0,
            embedded_count=len(embeddings),
            failed_count=failed
        )
```

### Qdrant Video Index

```python
# processors/video/qdrant_indexer.py
from dataclasses import dataclass
from uuid import UUID
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue,
    PayloadSchemaType
)
import logging

logger = logging.getLogger(__name__)

COLLECTION_NAME = "video_chunks"
VECTOR_SIZE = 1024  # BGE-large

@dataclass
class QdrantVideoIndexConfig:
    collection_name: str = COLLECTION_NAME
    vector_size: int = VECTOR_SIZE
    distance: str = "Cosine"
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100

class QdrantVideoIndexer:
    """Indexes video chunks in Qdrant vector store."""

    def __init__(self, client: QdrantClient, config: QdrantVideoIndexConfig = None):
        self.client = client
        self.config = config or QdrantVideoIndexConfig()

    async def ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = await self.client.get_collections()
        exists = any(c.name == self.config.collection_name for c in collections.collections)

        if not exists:
            await self.client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=Distance.COSINE
                ),
                hnsw_config={
                    "m": self.config.hnsw_m,
                    "ef_construct": self.config.hnsw_ef_construct
                }
            )

            # Create payload indexes for filtering
            await self.client.create_payload_index(
                collection_name=self.config.collection_name,
                field_name="tenant_id",
                field_schema=PayloadSchemaType.KEYWORD
            )
            await self.client.create_payload_index(
                collection_name=self.config.collection_name,
                field_name="video_id",
                field_schema=PayloadSchemaType.KEYWORD
            )
            await self.client.create_payload_index(
                collection_name=self.config.collection_name,
                field_name="allowed_groups",
                field_schema=PayloadSchemaType.KEYWORD
            )

            logger.info(f"Created Qdrant collection: {self.config.collection_name}")

    async def index_chunks(
        self,
        tenant_id: UUID,
        video_id: UUID,
        embeddings: list["ChunkEmbedding"],
        video_metadata: dict
    ) -> int:
        """
        Index video chunk embeddings in Qdrant.

        Payload includes:
        - tenant_id, video_id for filtering
        - chunk_index, timestamps for retrieval
        - allowed_groups for ACL
        """
        await self.ensure_collection()

        points = []
        for emb in embeddings:
            point_id = str(UUID(int=hash((str(video_id), emb.chunk_index)) % (2**128)))

            payload = {
                "tenant_id": str(tenant_id),
                "video_id": str(video_id),
                "chunk_index": emb.chunk_index,
                "start_time_ms": emb.start_time_ms,
                "end_time_ms": emb.end_time_ms,
                "fused_text": emb.fused_text[:1000],  # Truncate for payload
                "video_title": video_metadata.get("title", ""),
                "visibility": video_metadata.get("visibility", "private"),
                "allowed_groups": video_metadata.get("allowed_groups", []),
                "created_at": video_metadata.get("created_at", "")
            }

            points.append(PointStruct(
                id=point_id,
                vector=emb.embedding,
                payload=payload
            ))

        # Upsert in batches
        batch_size = 100
        indexed = 0
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            await self.client.upsert(
                collection_name=self.config.collection_name,
                points=batch
            )
            indexed += len(batch)

        logger.info(f"Indexed {indexed} video chunks in Qdrant")
        return indexed

    async def delete_video_chunks(self, video_id: UUID) -> int:
        """Delete all chunks for a video."""
        result = await self.client.delete(
            collection_name=self.config.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="video_id",
                        match=MatchValue(value=str(video_id))
                    )
                ]
            )
        )
        logger.info(f"Deleted chunks for video {video_id} from Qdrant")
        return result.status
```

### OpenSearch Video Index

```python
# processors/video/opensearch_indexer.py
from dataclasses import dataclass
from uuid import UUID
from opensearchpy import AsyncOpenSearch
import logging

logger = logging.getLogger(__name__)

INDEX_NAME = "video_chunks"

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard",
                    "stopwords": "_english_"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "video_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "start_time_ms": {"type": "integer"},
            "end_time_ms": {"type": "integer"},
            "fused_text": {"type": "text", "analyzer": "default"},
            "transcript_text": {"type": "text", "analyzer": "default"},
            "scene_description": {"type": "text", "analyzer": "default"},
            "ocr_text": {"type": "text", "analyzer": "default"},
            "video_title": {"type": "text"},
            "visibility": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "created_at": {"type": "date"}
        }
    }
}

class OpenSearchVideoIndexer:
    """Indexes video chunks in OpenSearch for keyword search."""

    def __init__(self, client: AsyncOpenSearch, index_name: str = INDEX_NAME):
        self.client = client
        self.index_name = index_name

    async def ensure_index(self):
        """Create index if it doesn't exist."""
        exists = await self.client.indices.exists(index=self.index_name)
        if not exists:
            await self.client.indices.create(
                index=self.index_name,
                body=INDEX_MAPPING
            )
            logger.info(f"Created OpenSearch index: {self.index_name}")

    async def index_chunks(
        self,
        tenant_id: UUID,
        video_id: UUID,
        chunks: list["VideoChunk"],
        video_metadata: dict
    ) -> int:
        """Index video chunks for keyword search."""
        await self.ensure_index()

        # Prepare bulk actions
        actions = []
        for chunk in chunks:
            doc_id = f"{video_id}_{chunk.chunk_index}"

            action = {"index": {"_index": self.index_name, "_id": doc_id}}
            doc = {
                "chunk_id": doc_id,
                "video_id": str(video_id),
                "tenant_id": str(tenant_id),
                "chunk_index": chunk.chunk_index,
                "start_time_ms": chunk.start_time_ms,
                "end_time_ms": chunk.end_time_ms,
                "fused_text": chunk.fused_text,
                "transcript_text": chunk.transcript_text,
                "scene_description": chunk.scene_description,
                "ocr_text": chunk.ocr_text,
                "video_title": video_metadata.get("title", ""),
                "visibility": video_metadata.get("visibility", "private"),
                "allowed_groups": video_metadata.get("allowed_groups", []),
                "created_at": video_metadata.get("created_at")
            }

            actions.append(action)
            actions.append(doc)

        # Execute bulk index
        if actions:
            response = await self.client.bulk(body=actions)
            if response.get("errors"):
                error_items = [
                    item for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                logger.error(f"Bulk index errors: {error_items[:3]}")

        logger.info(f"Indexed {len(chunks)} video chunks in OpenSearch")
        return len(chunks)

    async def delete_video_chunks(self, video_id: UUID) -> int:
        """Delete all chunks for a video."""
        response = await self.client.delete_by_query(
            index=self.index_name,
            body={
                "query": {
                    "term": {"video_id": str(video_id)}
                }
            }
        )
        deleted = response.get("deleted", 0)
        logger.info(f"Deleted {deleted} chunks for video {video_id} from OpenSearch")
        return deleted
```

### Pipeline Integration

```python
# In VideoProcessingPipeline

async def _run_embedding_indexing_stage(
    self,
    chunks: list["VideoChunk"]
) -> EmbeddingResult:
    """Embed and index video chunks."""
    await self._update_progress("embedding", 0)

    # Generate embeddings
    embedder = VideoChunkEmbedder(self.embedding_service)
    embeddings, embed_result = await embedder.embed_chunks(
        chunks,
        progress_callback=lambda done, total: self._update_progress(
            "embedding",
            int(done / total * 50)  # First 50% for embedding
        )
    )

    if not embed_result.success:
        logger.warning(f"Some embeddings failed: {embed_result.failed_count}")

    await self._update_progress("indexing", 50)

    # Get video metadata for index payloads
    video = await self.video_service.get_video(self.video_id, self.tenant_id)
    video_metadata = {
        "title": video.title,
        "visibility": video.visibility,
        "allowed_groups": video.allowed_groups or [],
        "created_at": video.created_at.isoformat() if video.created_at else None
    }

    # Index in Qdrant
    qdrant_indexer = QdrantVideoIndexer(self.qdrant_client)
    await qdrant_indexer.index_chunks(
        tenant_id=self.tenant_id,
        video_id=self.video_id,
        embeddings=embeddings,
        video_metadata=video_metadata
    )

    await self._update_progress("indexing", 75)

    # Index in OpenSearch
    opensearch_indexer = OpenSearchVideoIndexer(self.opensearch_client)
    await opensearch_indexer.index_chunks(
        tenant_id=self.tenant_id,
        video_id=self.video_id,
        chunks=chunks,
        video_metadata=video_metadata
    )

    # Update chunk records with embedding IDs
    for emb in embeddings:
        await self.chunk_storage.update_embedding_id(
            video_id=self.video_id,
            chunk_index=emb.chunk_index,
            embedding_id=f"{self.video_id}_{emb.chunk_index}"
        )

    await self._update_progress("indexing", 100)

    return embed_result
```

### Update Chunk Records

```python
# processors/video/chunk_storage.py (addition)

async def update_embedding_id(
    self,
    video_id: UUID,
    chunk_index: int,
    embedding_id: str
):
    """Update chunk with embedding ID after indexing."""
    from sqlalchemy import update

    await self.session.execute(
        update(VideoChunkModel)
        .where(VideoChunkModel.video_id == video_id)
        .where(VideoChunkModel.chunk_index == chunk_index)
        .values(embedding_id=embedding_id)
    )
    await self.session.commit()
```

## Qdrant Collection Schema

```yaml
Collection: video_chunks
Vector:
  size: 1024
  distance: Cosine

Payload Schema:
  tenant_id: keyword (indexed)
  video_id: keyword (indexed)
  chunk_index: integer
  start_time_ms: integer
  end_time_ms: integer
  fused_text: text (first 1000 chars)
  video_title: text
  visibility: keyword
  allowed_groups: keyword[] (indexed)
  created_at: datetime

HNSW Config:
  m: 16
  ef_construct: 100
```

## OpenSearch Index Schema

```yaml
Index: video_chunks
Mappings:
  chunk_id: keyword
  video_id: keyword
  tenant_id: keyword
  chunk_index: integer
  start_time_ms: integer
  end_time_ms: integer
  fused_text: text (searchable)
  transcript_text: text (searchable)
  scene_description: text (searchable)
  ocr_text: text (searchable)
  video_title: text
  visibility: keyword
  allowed_groups: keyword[]
  created_at: date
```

## Acceptance Criteria

- [ ] Generate embeddings from `fused_text` using BGE-large
- [ ] Index in Qdrant `video_chunks` collection
- [ ] Index in OpenSearch `video_chunks` index
- [ ] Store chunk metadata in PostgreSQL `video_chunks` table
- [ ] Include tenant_id, video_id, timestamps in payload/fields
- [ ] Support ACL filtering (allowed_groups)

## Testing Requirements

```python
class TestVideoChunkEmbedder:
    @pytest.mark.asyncio
    async def test_embeds_chunks(self, sample_chunks, mock_embedding_service):
        embedder = VideoChunkEmbedder(mock_embedding_service)
        embeddings, result = await embedder.embed_chunks(sample_chunks)

        assert result.success
        assert len(embeddings) == len(sample_chunks)
        assert all(len(e.embedding) == 1024 for e in embeddings)

    @pytest.mark.asyncio
    async def test_handles_embedding_failures(self, sample_chunks, failing_embedding_service):
        embedder = VideoChunkEmbedder(failing_embedding_service)
        embeddings, result = await embedder.embed_chunks(sample_chunks)

        assert result.failed_count > 0

class TestQdrantVideoIndexer:
    @pytest.mark.asyncio
    async def test_creates_collection(self, qdrant_client):
        indexer = QdrantVideoIndexer(qdrant_client)
        await indexer.ensure_collection()

        collections = await qdrant_client.get_collections()
        assert "video_chunks" in [c.name for c in collections.collections]

    @pytest.mark.asyncio
    async def test_indexes_chunks(self, qdrant_client, sample_embeddings):
        indexer = QdrantVideoIndexer(qdrant_client)
        video_id = uuid4()

        count = await indexer.index_chunks(
            tenant_id=uuid4(),
            video_id=video_id,
            embeddings=sample_embeddings,
            video_metadata={"title": "Test", "visibility": "private"}
        )

        assert count == len(sample_embeddings)

    @pytest.mark.asyncio
    async def test_deletes_video_chunks(self, qdrant_client, indexed_video):
        indexer = QdrantVideoIndexer(qdrant_client)
        await indexer.delete_video_chunks(indexed_video.id)

        # Verify deleted
        results = await qdrant_client.scroll(
            collection_name="video_chunks",
            scroll_filter=Filter(must=[
                FieldCondition(key="video_id", match=MatchValue(value=str(indexed_video.id)))
            ])
        )
        assert len(results[0]) == 0

class TestOpenSearchVideoIndexer:
    @pytest.mark.asyncio
    async def test_creates_index(self, opensearch_client):
        indexer = OpenSearchVideoIndexer(opensearch_client)
        await indexer.ensure_index()

        exists = await opensearch_client.indices.exists(index="video_chunks")
        assert exists

    @pytest.mark.asyncio
    async def test_indexes_chunks_for_search(self, opensearch_client, sample_chunks):
        indexer = OpenSearchVideoIndexer(opensearch_client)
        video_id = uuid4()

        await indexer.index_chunks(
            tenant_id=uuid4(),
            video_id=video_id,
            chunks=sample_chunks,
            video_metadata={"title": "Test"}
        )

        # Search for content
        await opensearch_client.indices.refresh(index="video_chunks")
        results = await opensearch_client.search(
            index="video_chunks",
            body={"query": {"match": {"fused_text": sample_chunks[0].fused_text.split()[0]}}}
        )

        assert results["hits"]["total"]["value"] > 0
```

## Dependencies

```
qdrant-client>=1.7.0
opensearch-py>=2.4.0
```

## Definition of Done

- [ ] BGE-large embeddings generated for all chunks
- [ ] Qdrant collection created with correct schema
- [ ] OpenSearch index created with correct mappings
- [ ] Chunks indexed in both stores
- [ ] ACL fields included in payloads
- [ ] Embedding IDs stored in PostgreSQL
- [ ] Delete cascades work correctly
- [ ] >90% test coverage
