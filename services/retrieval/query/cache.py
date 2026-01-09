"""Query cache for the Retrieval Service.

This module provides Redis-based caching for processed queries,
avoiding redundant embedding generation for repeated queries.
"""

from typing import Optional

import redis.asyncio as redis

from .models import ProcessedQuery


class QueryCache:
    """Redis cache for processed queries.

    Caches the full ProcessedQuery including embeddings to avoid
    redundant embedding generation for repeated queries.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "query_cache:",
        default_ttl: int = 3600,
    ):
        """Initialize query cache.

        Args:
            redis_url: Redis connection URL.
            key_prefix: Prefix for all cache keys.
            default_ttl: Default TTL in seconds.
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self._redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def get(self, key: str) -> Optional[ProcessedQuery]:
        """Retrieve processed query from cache.

        Args:
            key: Cache key.

        Returns:
            ProcessedQuery if found, None otherwise.
        """
        if self._redis is None:
            await self.connect()

        full_key = f"{self.key_prefix}{key}"
        data = await self._redis.get(full_key)

        if data is None:
            return None

        return ProcessedQuery.model_validate_json(data)

    async def set(
        self,
        key: str,
        query: ProcessedQuery,
        ttl: Optional[int] = None,
    ) -> None:
        """Store processed query in cache.

        Args:
            key: Cache key.
            query: ProcessedQuery to cache.
            ttl: Optional TTL override in seconds.
        """
        if self._redis is None:
            await self.connect()

        full_key = f"{self.key_prefix}{key}"
        data = query.model_dump_json()

        await self._redis.setex(full_key, ttl or self.default_ttl, data)

    async def delete(self, key: str) -> None:
        """Delete query from cache.

        Args:
            key: Cache key to delete.
        """
        if self._redis is None:
            await self.connect()

        full_key = f"{self.key_prefix}{key}"
        await self._redis.delete(full_key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key to check.

        Returns:
            True if key exists, False otherwise.
        """
        if self._redis is None:
            await self.connect()

        full_key = f"{self.key_prefix}{key}"
        return await self._redis.exists(full_key) > 0

    async def clear_all(self) -> int:
        """Clear all cached queries.

        Returns:
            Number of keys deleted.
        """
        if self._redis is None:
            await self.connect()

        pattern = f"{self.key_prefix}*"
        keys = []
        async for key in self._redis.scan_iter(match=pattern):
            keys.append(key)

        if keys:
            return await self._redis.delete(*keys)
        return 0

    async def health_check(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis is reachable, False otherwise.
        """
        try:
            if self._redis is None:
                await self.connect()
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def __aenter__(self) -> "QueryCache":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
