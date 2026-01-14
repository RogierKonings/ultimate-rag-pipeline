"""Qdrant indexer for video chunks.

This module provides the QdrantVideoIndexer class for indexing
video chunk embeddings in Qdrant for semantic search.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from processors.video.content_fusion import VideoChunk
from processors.video.embedding import ChunkEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[int, int, str], None]

# Collection configuration
VIDEO_CHUNKS_COLLECTION = "video_chunks"
VECTOR_SIZE = 1024
HNSW_M = 16
HNSW_EF_CONSTRUCT = 100


@dataclass
class QdrantIndexerConfig:
    """Configuration for Qdrant video indexer.

    Attributes:
        url: Qdrant server URL.
        collection_name: Collection name for video chunks.
        batch_size: Points per upsert batch.
        timeout: Request timeout in seconds.
    """

    url: str = ""
    collection_name: str = VIDEO_CHUNKS_COLLECTION
    batch_size: int = 100
    timeout: int = 60

    def __post_init__(self):
        if not self.url:
            self.url = os.getenv("QDRANT_URL", "http://localhost:6333")


@dataclass
class IndexResult:
    """Result of indexing operation.

    Attributes:
        indexed_count: Number of points indexed.
        collection_name: Target collection name.
        video_id: Video that was indexed.
    """

    indexed_count: int
    collection_name: str
    video_id: UUID


class QdrantVideoIndexer:
    """Indexes video chunk embeddings in Qdrant.

    Creates and manages the video_chunks collection with proper
    vector configuration and payload indexes for efficient filtering.

    Example:
        indexer = QdrantVideoIndexer()
        await indexer.ensure_collection()
        result = await indexer.index_chunks(
            chunks=video_chunks,
            embeddings=chunk_embeddings,
        )
    """

    def __init__(self, config: QdrantIndexerConfig | None = None):
        """Initialize Qdrant video indexer.

        Args:
            config: Indexer configuration.
        """
        self.config = config or QdrantIndexerConfig()
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._client is None:
            self._client = QdrantClient(
                url=self.config.url,
                timeout=self.config.timeout,
            )
        return self._client

    async def ensure_collection(self) -> bool:
        """Ensure video_chunks collection exists with proper configuration.

        Creates the collection if it doesn't exist with:
        - Vector size: 1024 (BGE-large dimensions)
        - Distance: Cosine
        - HNSW config: m=16, ef_construct=100
        - Payload indexes for filtering

        Returns:
            True if collection was created, False if already exists.
        """
        collection_name = self.config.collection_name

        # Check if collection exists
        collections = self.client.get_collections()
        existing = [c.name for c in collections.collections]

        if collection_name in existing:
            logger.info("Collection %s already exists", collection_name)
            return False

        # Create collection
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
            hnsw_config=HnswConfigDiff(
                m=HNSW_M,
                ef_construct=HNSW_EF_CONSTRUCT,
            ),
        )

        # Create payload indexes for efficient filtering
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="tenant_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="video_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="allowed_groups",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="visibility",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        logger.info(
            "Created collection %s with vector_size=%d, distance=Cosine",
            collection_name,
            VECTOR_SIZE,
        )
        return True

    async def index_chunks(
        self,
        chunks: list[VideoChunk],
        embeddings: list[ChunkEmbedding] | dict[UUID, list[float]],
        video_title: str = "",
        visibility: str = "private",
        allowed_groups: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> IndexResult:
        """Index video chunks with their embeddings in Qdrant.

        Args:
            chunks: List of VideoChunk objects.
            embeddings: ChunkEmbedding list or dict mapping chunk_id to vector.
            video_title: Title of the video for search display.
            visibility: Visibility level (private, group, public).
            allowed_groups: List of allowed groups for ACL filtering.
            progress_callback: Optional progress callback.

        Returns:
            IndexResult with count and metadata.
        """
        if not chunks:
            return IndexResult(
                indexed_count=0,
                collection_name=self.config.collection_name,
                video_id=UUID(int=0),
            )

        # Convert embeddings to dict if needed
        if isinstance(embeddings, list):
            embedding_map = {e.chunk_id: e.embedding for e in embeddings}
        else:
            embedding_map = embeddings

        total = len(chunks)
        video_id = chunks[0].video_id
        tenant_id = chunks[0].tenant_id

        logger.info(
            "Indexing %d chunks for video_id=%s in Qdrant",
            total,
            video_id,
        )

        # Build points
        points = []
        for chunk in chunks:
            embedding = embedding_map.get(chunk.id)
            if embedding is None:
                logger.warning("No embedding for chunk %s, skipping", chunk.id)
                continue

            # Truncate fused_text for payload (first 1000 chars)
            fused_text_preview = chunk.fused_text[:1000] if chunk.fused_text else ""

            payload = {
                "tenant_id": str(tenant_id),
                "video_id": str(video_id),
                "chunk_index": chunk.chunk_index,
                "start_time_ms": chunk.start_time_ms,
                "end_time_ms": chunk.end_time_ms,
                "fused_text": fused_text_preview,
                "video_title": video_title,
                "visibility": visibility,
                "allowed_groups": allowed_groups or [],
                "source_modalities": chunk.source_modalities,
                "keyframe_path": chunk.keyframe_path,
            }

            points.append(
                PointStruct(
                    id=str(chunk.id),
                    vector=embedding,
                    payload=payload,
                )
            )

        # Upsert in batches
        indexed = 0
        for i in range(0, len(points), self.config.batch_size):
            batch = points[i : i + self.config.batch_size]
            self.client.upsert(
                collection_name=self.config.collection_name,
                points=batch,
            )
            indexed += len(batch)

            if progress_callback:
                progress_callback(
                    indexed,
                    total,
                    f"Indexed {indexed}/{total} chunks in Qdrant",
                )

        logger.info(
            "Indexed %d chunks for video_id=%s in collection %s",
            indexed,
            video_id,
            self.config.collection_name,
        )

        return IndexResult(
            indexed_count=indexed,
            collection_name=self.config.collection_name,
            video_id=video_id,
        )

    async def delete_by_video_id(self, video_id: UUID) -> int:
        """Delete all chunks for a video from Qdrant.

        Args:
            video_id: Video UUID whose chunks should be deleted.

        Returns:
            Number of points deleted (estimated).
        """
        # Get count before deletion for logging
        count_before = self._count_by_video(video_id)

        self.client.delete(
            collection_name=self.config.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="video_id",
                        match=MatchValue(value=str(video_id)),
                    ),
                ],
            ),
        )

        logger.info(
            "Deleted ~%d chunks for video_id=%s from Qdrant",
            count_before,
            video_id,
        )

        return count_before

    def _count_by_video(self, video_id: UUID) -> int:
        """Count points for a video.

        Args:
            video_id: Video UUID.

        Returns:
            Point count.
        """
        try:
            result = self.client.count(
                collection_name=self.config.collection_name,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="video_id",
                            match=MatchValue(value=str(video_id)),
                        ),
                    ],
                ),
            )
            return result.count
        except Exception:
            return 0

    async def search(
        self,
        query_vector: list[float],
        tenant_id: UUID,
        top_k: int = 10,
        video_id: UUID | None = None,
        allowed_groups: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        """Search for similar video chunks.

        Args:
            query_vector: Query embedding vector.
            tenant_id: Tenant for filtering.
            top_k: Number of results.
            video_id: Optional filter to specific video.
            allowed_groups: User's groups for ACL filtering.
            score_threshold: Minimum similarity score.

        Returns:
            List of search results with id, score, and payload.
        """
        # Build filter conditions
        must_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=str(tenant_id)),
            ),
        ]

        if video_id:
            must_conditions.append(
                FieldCondition(
                    key="video_id",
                    match=MatchValue(value=str(video_id)),
                )
            )

        # ACL filtering - match visibility=public OR allowed_groups contains user group
        should_conditions = []
        if allowed_groups:
            for group in allowed_groups:
                should_conditions.append(
                    FieldCondition(
                        key="allowed_groups",
                        match=MatchValue(value=group),
                    )
                )
        should_conditions.append(
            FieldCondition(
                key="visibility",
                match=MatchValue(value="public"),
            )
        )

        query_filter = Filter(
            must=must_conditions,
            should=should_conditions if should_conditions else None,
        )

        response = self.client.query_points(
            collection_name=self.config.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in response.points
        ]

    def health_check(self) -> bool:
        """Check Qdrant connectivity.

        Returns:
            True if healthy.
        """
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def get_collection_info(self) -> dict | None:
        """Get collection information.

        Returns:
            Collection info dict or None.
        """
        try:
            info = self.client.get_collection(self.config.collection_name)
            return {
                "name": self.config.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status.value,
            }
        except Exception:
            return None

    def close(self) -> None:
        """Close client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
