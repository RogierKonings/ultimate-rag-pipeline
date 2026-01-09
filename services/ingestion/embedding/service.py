"""Embedding generation service with batching, caching, and parallel processing."""

import asyncio
import hashlib
import math
import time
from typing import AsyncIterator, Optional
from uuid import UUID

from .cache import EmbeddingCache
from .client import LLMGatewayClient
from .models import (
    BatchEmbeddingResult,
    EmbeddingCacheConfig,
    EmbeddingResult,
    EmbeddingServiceConfig,
)


class EmbeddingService:
    """
    Service for generating embeddings with batching and caching.

    Uses the LLM Gateway which serves embedding models via OpenAI-compatible API.
    Supports Redis-based caching to avoid redundant computation and batching
    for efficient processing.
    """

    def __init__(
        self,
        config: EmbeddingServiceConfig = EmbeddingServiceConfig(),
        cache: Optional[EmbeddingCache] = None,
    ):
        """
        Initialize the embedding service.

        Args:
            config: Service configuration.
            cache: Optional embedding cache instance.
        """
        self.config = config
        self.cache = cache
        self._client = LLMGatewayClient(config)

    async def embed_texts(
        self,
        texts: list[str],
        chunk_ids: list[UUID],
        prefix: Optional[str] = "passage: ",  # BGE prefix for documents
    ) -> BatchEmbeddingResult:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.
            chunk_ids: Corresponding chunk IDs for each text.
            prefix: Prefix to add to texts (BGE models use "query: " or "passage: ").

        Returns:
            BatchEmbeddingResult with embeddings and metadata.
        """
        start_time = time.time()
        cache_hits = 0
        cache_misses = 0
        total_tokens = 0

        # Add prefix to texts
        prefixed_texts = [f"{prefix}{t}" if prefix else t for t in texts]

        # Check cache for existing embeddings
        texts_to_embed: list[str] = []
        chunk_ids_to_embed: list[tuple[int, UUID]] = []
        cached_results: dict[int, EmbeddingResult] = {}

        if self.cache and self.config.cache_enabled:
            for i, (text, chunk_id) in enumerate(zip(prefixed_texts, chunk_ids)):
                cache_key = self._get_cache_key(text)
                cached = await self.cache.get(cache_key)
                if cached is not None:
                    cache_hits += 1
                    cached_results[i] = EmbeddingResult(
                        chunk_id=chunk_id,
                        embedding=cached,
                        model=self.config.model,
                        dimensions=self.config.dimensions,
                        cached=True,
                    )
                else:
                    cache_misses += 1
                    texts_to_embed.append(text)
                    chunk_ids_to_embed.append((i, chunk_id))
        else:
            texts_to_embed = prefixed_texts
            chunk_ids_to_embed = list(enumerate(chunk_ids))
            cache_misses = len(texts)

        # Generate embeddings for uncached texts in batches
        if texts_to_embed:
            batches = self._create_batches(texts_to_embed, chunk_ids_to_embed)

            for batch_texts, batch_ids in batches:
                embeddings, tokens = await self._client.embed_batch(batch_texts)
                total_tokens += tokens

                for j, ((original_idx, chunk_id), embedding) in enumerate(
                    zip(batch_ids, embeddings)
                ):
                    # Normalize if configured
                    if self.config.normalize_embeddings:
                        embedding = self._normalize(embedding)

                    result = EmbeddingResult(
                        chunk_id=chunk_id,
                        embedding=embedding,
                        model=self.config.model,
                        dimensions=self.config.dimensions,
                        cached=False,
                    )
                    cached_results[original_idx] = result

                    # Store in cache
                    if self.cache and self.config.cache_enabled:
                        cache_key = self._get_cache_key(batch_texts[j])
                        await self.cache.set(
                            cache_key, embedding, ttl=self.config.cache_ttl_seconds
                        )

        # Reconstruct results in original order
        results = [cached_results[i] for i in range(len(texts))]

        processing_time = (time.time() - start_time) * 1000

        return BatchEmbeddingResult(
            results=results,
            total_tokens=total_tokens,
            processing_time_ms=processing_time,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )

    def _create_batches(
        self, texts: list[str], chunk_ids: list[tuple[int, UUID]]
    ) -> list[tuple[list[str], list[tuple[int, UUID]]]]:
        """
        Split texts into batches respecting size limits.

        Args:
            texts: List of texts to batch.
            chunk_ids: Corresponding chunk IDs with original indices.

        Returns:
            List of (batch_texts, batch_ids) tuples.
        """
        batches: list[tuple[list[str], list[tuple[int, UUID]]]] = []
        current_batch_texts: list[str] = []
        current_batch_ids: list[tuple[int, UUID]] = []
        current_tokens = 0

        for text, chunk_id in zip(texts, chunk_ids):
            # Estimate tokens (rough: 4 chars per token)
            text_tokens = len(text) // 4

            if (
                len(current_batch_texts) >= self.config.max_batch_size
                or current_tokens + text_tokens > self.config.max_tokens_per_batch
            ):
                if current_batch_texts:
                    batches.append((current_batch_texts, current_batch_ids))
                current_batch_texts = [text]
                current_batch_ids = [chunk_id]
                current_tokens = text_tokens
            else:
                current_batch_texts.append(text)
                current_batch_ids.append(chunk_id)
                current_tokens += text_tokens

        if current_batch_texts:
            batches.append((current_batch_texts, current_batch_ids))

        return batches

    def _normalize(self, embedding: list[float]) -> list[float]:
        """
        L2 normalize the embedding vector.

        Args:
            embedding: Vector to normalize.

        Returns:
            Unit-length vector.
        """
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            return [x / norm for x in embedding]
        return embedding

    def _get_cache_key(self, text: str) -> str:
        """
        Generate cache key from text content and model.

        Args:
            text: Text content (with prefix if applicable).

        Returns:
            SHA-256 hash of model and text.
        """
        content = f"{self.config.model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def embed_query(self, query: str) -> list[float]:
        """
        Embed a single query text.

        Uses "query: " prefix for BGE models.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        result = await self.embed_texts(
            texts=[query],
            chunk_ids=[UUID(int=0)],  # Dummy ID for queries
            prefix="query: ",
        )
        return result.results[0].embedding

    async def close(self) -> None:
        """Close HTTP client and cache connections."""
        await self._client.disconnect()
        if self.cache:
            await self.cache.disconnect()

    async def __aenter__(self) -> "EmbeddingService":
        """Async context manager entry."""
        await self._client.connect()
        if self.cache:
            await self.cache.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


class ParallelEmbedder:
    """
    Process embeddings in parallel with controlled concurrency.

    Useful for high-throughput ingestion scenarios where multiple
    batches can be processed concurrently.
    """

    def __init__(self, service: EmbeddingService, max_concurrent: int = 4):
        """
        Initialize the parallel embedder.

        Args:
            service: EmbeddingService instance to use.
            max_concurrent: Maximum concurrent embedding requests.
        """
        self.service = service
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def embed_chunks_parallel(
        self, chunks: list
    ) -> AsyncIterator[EmbeddingResult]:
        """
        Embed chunks in parallel with concurrency control.

        Args:
            chunks: List of Chunk objects with content and chunk_id attributes.

        Yields:
            EmbeddingResult for each chunk.
        """

        async def embed_batch(batch_chunks):
            async with self.semaphore:
                texts = [c.content for c in batch_chunks]
                ids = [c.chunk_id for c in batch_chunks]
                result = await self.service.embed_texts(texts, ids)
                return result.results

        # Split into batches
        batch_size = self.service.config.max_batch_size
        batches = [
            chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)
        ]

        # Process batches in parallel
        tasks = [embed_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks)

        for batch_results in results:
            for result in batch_results:
                yield result


async def create_embedding_service(
    config: Optional[EmbeddingServiceConfig] = None,
    cache_config: Optional[EmbeddingCacheConfig] = None,
    enable_cache: bool = True,
) -> EmbeddingService:
    """
    Factory function to create a configured EmbeddingService.

    Args:
        config: Service configuration (uses defaults if not provided).
        cache_config: Cache configuration (uses defaults if not provided).
        enable_cache: Whether to enable caching.

    Returns:
        Configured EmbeddingService instance.
    """
    config = config or EmbeddingServiceConfig()

    cache = None
    if enable_cache and config.cache_enabled:
        cache_config = cache_config or EmbeddingCacheConfig()
        cache = EmbeddingCache(cache_config)
        await cache.connect()

    service = EmbeddingService(config=config, cache=cache)
    await service._client.connect()

    return service
