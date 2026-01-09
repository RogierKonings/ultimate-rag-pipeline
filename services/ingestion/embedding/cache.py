"""Redis-based cache for embeddings."""

import json
from typing import Optional

import redis.asyncio as redis

from .models import EmbeddingCacheConfig


class EmbeddingCache:
    """
    Redis-based cache for embeddings.

    Stores embeddings as JSON to enable retrieval and inspection.
    Uses configurable TTL to manage cache lifetime.
    """

    def __init__(self, config: EmbeddingCacheConfig = EmbeddingCacheConfig()):
        """
        Initialize the embedding cache.

        Args:
            config: Cache configuration with Redis URL and TTL settings.
        """
        self.config = config
        self._redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        self._redis = redis.from_url(
            self.config.redis_url, encoding="utf-8", decode_responses=True
        )

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def _ensure_connected(self) -> None:
        """Ensure Redis connection is established."""
        if not self._redis:
            await self.connect()

    async def get(self, key: str) -> Optional[list[float]]:
        """
        Retrieve embedding from cache.

        Args:
            key: Cache key (typically a hash of the text content).

        Returns:
            Embedding vector if found, None otherwise.
        """
        await self._ensure_connected()

        full_key = f"{self.config.key_prefix}{key}"
        data = await self._redis.get(full_key)

        if data is None:
            return None

        return json.loads(data)

    async def set(
        self, key: str, embedding: list[float], ttl: Optional[int] = None
    ) -> None:
        """
        Store embedding in cache.

        Args:
            key: Cache key (typically a hash of the text content).
            embedding: Embedding vector to store.
            ttl: Time-to-live in seconds (uses default if not specified).
        """
        await self._ensure_connected()

        full_key = f"{self.config.key_prefix}{key}"
        data = json.dumps(embedding)

        await self._redis.setex(full_key, ttl or self.config.default_ttl, data)

    async def delete(self, key: str) -> None:
        """
        Delete embedding from cache.

        Args:
            key: Cache key to delete.
        """
        await self._ensure_connected()

        full_key = f"{self.config.key_prefix}{key}"
        await self._redis.delete(full_key)

    async def clear_all(self) -> None:
        """Clear all embeddings from cache (use with caution)."""
        await self._ensure_connected()

        cursor = 0
        pattern = f"{self.config.key_prefix}*"

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break

    async def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics including count and memory usage.
        """
        await self._ensure_connected()

        info = await self._redis.info("memory")
        pattern = f"{self.config.key_prefix}*"

        # Count keys (may be expensive for very large caches)
        cursor = 0
        count = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            count += len(keys)
            if cursor == 0:
                break

        return {
            "cached_embeddings": count,
            "used_memory": info.get("used_memory_human"),
            "key_prefix": self.config.key_prefix,
        }

    async def __aenter__(self) -> "EmbeddingCache":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
