"""Embedding cache for storing computed embeddings."""

import json
from typing import Optional

from .redis_client import RedisCache
from .key_builder import KeyBuilder, ServicePrefix, KeyType


class EmbeddingCache:
    """Cache for storing computed embeddings with 7-day TTL.

    Uses the ingestion service namespace by default, but can be
    configured for retrieval service caching.
    """

    TTL = 86400 * 7  # 7 days

    def __init__(
        self,
        redis_cache: RedisCache,
        service: ServicePrefix = ServicePrefix.INGESTION,
    ):
        """Initialize embedding cache.

        Args:
            redis_cache: Redis cache client.
            service: Service prefix for key namespacing.
        """
        self.cache = redis_cache
        self.key_builder = KeyBuilder(service)

    async def get(
        self,
        text_hash: str,
        tenant_id: str,
    ) -> Optional[list[float]]:
        """Get cached embedding for text.

        Args:
            text_hash: Hash of the text content.
            tenant_id: Tenant ID for isolation.

        Returns:
            Embedding vector or None if not cached.
        """
        key = self.key_builder.build(KeyType.EMBEDDING, tenant_id, text_hash)
        return await self.cache.get(key)

    async def set(
        self,
        text_hash: str,
        tenant_id: str,
        embedding: list[float],
        ttl: Optional[int] = None,
    ) -> None:
        """Cache embedding for text.

        Args:
            text_hash: Hash of the text content.
            tenant_id: Tenant ID for isolation.
            embedding: Embedding vector to cache.
            ttl: Time to live in seconds. Defaults to 7 days.
        """
        key = self.key_builder.build(KeyType.EMBEDDING, tenant_id, text_hash)
        await self.cache.set(key, embedding, ttl=ttl or self.TTL)

    async def get_many(
        self,
        text_hashes: list[str],
        tenant_id: str,
    ) -> dict[str, Optional[list[float]]]:
        """Get multiple cached embeddings.

        Args:
            text_hashes: List of text hashes.
            tenant_id: Tenant ID for isolation.

        Returns:
            Dict mapping text hashes to embeddings (None for misses).
        """
        if not text_hashes:
            return {}

        keys = [
            self.key_builder.build(KeyType.EMBEDDING, tenant_id, h)
            for h in text_hashes
        ]

        # Use pipeline for efficiency
        async with self.cache.redis.pipeline() as pipe:
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()

        return {
            text_hashes[i]: json.loads(r) if r else None
            for i, r in enumerate(results)
        }

    async def set_many(
        self,
        embeddings: dict[str, list[float]],
        tenant_id: str,
        ttl: Optional[int] = None,
    ) -> None:
        """Cache multiple embeddings.

        Args:
            embeddings: Dict mapping text hashes to embeddings.
            tenant_id: Tenant ID for isolation.
            ttl: Time to live in seconds.
        """
        if not embeddings:
            return

        items = {
            self.key_builder.build(KeyType.EMBEDDING, tenant_id, h): emb
            for h, emb in embeddings.items()
        }
        await self.cache.set_many(items, ttl=ttl or self.TTL)

    async def delete(self, text_hash: str, tenant_id: str) -> None:
        """Delete cached embedding.

        Args:
            text_hash: Hash of the text content.
            tenant_id: Tenant ID for isolation.
        """
        key = self.key_builder.build(KeyType.EMBEDDING, tenant_id, text_hash)
        await self.cache.delete(key)

    async def invalidate_tenant(self, tenant_id: str) -> int:
        """Invalidate all cached embeddings for a tenant.

        Args:
            tenant_id: Tenant ID to invalidate.

        Returns:
            Number of keys deleted.
        """
        pattern = self.key_builder.pattern(KeyType.EMBEDDING, tenant_id)
        return await self.cache.delete_pattern(pattern)
