"""Video chunk embedding service.

This module provides the VideoChunkEmbedder class for generating
embeddings for video chunks using the existing embedding service.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from embedding.service import EmbeddingService, EmbeddingServiceConfig
from processors.video.content_fusion import VideoChunk

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class ChunkEmbedding:
    """Embedding result for a video chunk.

    Attributes:
        chunk_id: Chunk UUID.
        video_id: Parent video UUID.
        chunk_index: Index within video.
        embedding: Embedding vector (1024 dims).
        tokens_used: Number of tokens used.
    """

    chunk_id: UUID
    video_id: UUID
    chunk_index: int
    embedding: list[float]
    tokens_used: int = 0


@dataclass
class EmbeddingBatchResult:
    """Result of batch embedding operation.

    Attributes:
        embeddings: List of chunk embeddings.
        total_tokens: Total tokens used.
        cache_hits: Number of cache hits.
        cache_misses: Number of cache misses.
        processing_time_ms: Processing time in milliseconds.
    """

    embeddings: list[ChunkEmbedding]
    total_tokens: int
    cache_hits: int
    cache_misses: int
    processing_time_ms: float


@dataclass
class VideoChunkEmbedderConfig:
    """Configuration for video chunk embedder.

    Attributes:
        batch_size: Number of chunks per batch.
        embedding_service_config: Config for embedding service.
    """

    batch_size: int = 32
    embedding_service_config: EmbeddingServiceConfig | None = None


class VideoChunkEmbedder:
    """Embeds video chunks using the embedding service.

    Uses the existing EmbeddingService (BGE-large-en-v1.5) to generate
    embeddings for video chunk fused text. Documents are embedded
    WITHOUT instruction prefix as per BGE guidelines.

    Example:
        embedder = VideoChunkEmbedder()
        async with embedder:
            results = await embedder.embed_chunks(
                chunks=video_chunks,
                progress_callback=update_progress,
            )
    """

    def __init__(
        self,
        config: VideoChunkEmbedderConfig | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        """Initialize video chunk embedder.

        Args:
            config: Embedder configuration.
            embedding_service: Optional pre-configured embedding service.
        """
        self.config = config or VideoChunkEmbedderConfig()
        self._embedding_service = embedding_service
        self._owns_service = embedding_service is None

    async def __aenter__(self) -> "VideoChunkEmbedder":
        """Async context manager entry."""
        if self._embedding_service is None:
            service_config = self.config.embedding_service_config or EmbeddingServiceConfig()
            self._embedding_service = EmbeddingService(config=service_config)
            await self._embedding_service.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._owns_service and self._embedding_service is not None:
            await self._embedding_service.close()
            self._embedding_service = None

    async def embed_chunks(
        self,
        chunks: list[VideoChunk],
        progress_callback: ProgressCallback | None = None,
    ) -> EmbeddingBatchResult:
        """Generate embeddings for video chunks.

        Args:
            chunks: List of VideoChunk objects to embed.
            progress_callback: Optional progress callback (current, total, message).

        Returns:
            EmbeddingBatchResult with embeddings and metadata.
        """
        if not chunks:
            return EmbeddingBatchResult(
                embeddings=[],
                total_tokens=0,
                cache_hits=0,
                cache_misses=0,
                processing_time_ms=0,
            )

        if self._embedding_service is None:
            raise RuntimeError("Embedder not initialized. Use async context manager.")

        total = len(chunks)
        logger.info("Embedding %d video chunks", total)

        # Prepare texts and chunk IDs
        texts = [chunk.fused_text for chunk in chunks]
        chunk_ids = [chunk.id for chunk in chunks]

        # Embed using the service (passage prefix for documents)
        # BGE models: documents get "passage: " prefix
        result = await self._embedding_service.embed_texts(
            texts=texts,
            chunk_ids=chunk_ids,
            prefix="passage: ",
        )

        # Map results to ChunkEmbedding objects
        embeddings = []
        for i, (chunk, emb_result) in enumerate(zip(chunks, result.results, strict=True)):
            embeddings.append(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    video_id=chunk.video_id,
                    chunk_index=chunk.chunk_index,
                    embedding=emb_result.embedding,
                    tokens_used=0,  # Not tracked per chunk
                )
            )

            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(i + 1, total, f"Embedded {i + 1}/{total} chunks")

        if progress_callback:
            progress_callback(total, total, f"Embedded all {total} chunks")

        logger.info(
            "Embedded %d chunks: %d cache hits, %d misses, %.1fms",
            total,
            result.cache_hits,
            result.cache_misses,
            result.processing_time_ms,
        )

        return EmbeddingBatchResult(
            embeddings=embeddings,
            total_tokens=result.total_tokens,
            cache_hits=result.cache_hits,
            cache_misses=result.cache_misses,
            processing_time_ms=result.processing_time_ms,
        )

    async def embed_for_video(
        self,
        chunks: list[VideoChunk],
        video_id: UUID,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[UUID, list[float]]:
        """Embed chunks and return mapping of chunk_id to embedding.

        Args:
            chunks: List of video chunks.
            video_id: Video identifier for logging.
            progress_callback: Optional progress callback.

        Returns:
            Dict mapping chunk_id to embedding vector.
        """
        result = await self.embed_chunks(
            chunks=chunks,
            progress_callback=progress_callback,
        )

        embedding_map = {
            emb.chunk_id: emb.embedding
            for emb in result.embeddings
        }

        logger.info(
            "Generated embeddings for %d chunks of video_id=%s",
            len(embedding_map),
            video_id,
        )

        return embedding_map

    async def close(self) -> None:
        """Close embedding service if owned."""
        if self._owns_service and self._embedding_service is not None:
            await self._embedding_service.close()
            self._embedding_service = None
