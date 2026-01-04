"""Query cache for storing search results."""

from typing import Any, Optional

from .redis_client import RedisCache
from .key_builder import KeyBuilder, ServicePrefix, KeyType


class QueryCache:
    """Cache for storing query results with 5-minute TTL.

    Uses the retrieval service namespace for query result caching.
    """

    TTL = 300  # 5 minutes

    def __init__(
        self,
        redis_cache: RedisCache,
        service: ServicePrefix = ServicePrefix.RETRIEVAL,
    ):
        """Initialize query cache.

        Args:
            redis_cache: Redis cache client.
            service: Service prefix for key namespacing.
        """
        self.cache = redis_cache
        self.key_builder = KeyBuilder(service)

    def _generate_identifier(
        self,
        query: str,
        top_k: int,
        **kwargs: Any,
    ) -> str:
        """Generate unique identifier for a query.

        Args:
            query: Search query text.
            top_k: Number of results requested.
            **kwargs: Additional parameters affecting results.

        Returns:
            Hash identifier for the query.
        """
        # Include all parameters that affect results
        params = [query, str(top_k)]
        for key in sorted(kwargs.keys()):
            params.append(f"{key}={kwargs[key]}")
        return KeyBuilder.hash_content(*params)

    async def get(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """Get cached query results.

        Args:
            query: Search query text.
            tenant_id: Tenant ID for isolation.
            top_k: Number of results requested.
            **kwargs: Additional parameters affecting results.

        Returns:
            Cached results or None if not found.
        """
        identifier = self._generate_identifier(query, top_k, **kwargs)
        key = self.key_builder.build(KeyType.QUERY, tenant_id, identifier)
        return await self.cache.get(key)

    async def set(
        self,
        query: str,
        tenant_id: str,
        results: dict[str, Any],
        top_k: int = 10,
        ttl: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Cache query results.

        Args:
            query: Search query text.
            tenant_id: Tenant ID for isolation.
            results: Results to cache.
            top_k: Number of results requested.
            ttl: Time to live in seconds. Defaults to 5 minutes.
            **kwargs: Additional parameters affecting results.
        """
        identifier = self._generate_identifier(query, top_k, **kwargs)
        key = self.key_builder.build(KeyType.QUERY, tenant_id, identifier)
        await self.cache.set(key, results, ttl=ttl or self.TTL)

    async def delete(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 10,
        **kwargs: Any,
    ) -> None:
        """Delete cached query results.

        Args:
            query: Search query text.
            tenant_id: Tenant ID for isolation.
            top_k: Number of results requested.
            **kwargs: Additional parameters affecting results.
        """
        identifier = self._generate_identifier(query, top_k, **kwargs)
        key = self.key_builder.build(KeyType.QUERY, tenant_id, identifier)
        await self.cache.delete(key)

    async def invalidate_tenant(self, tenant_id: str) -> int:
        """Invalidate all cached queries for a tenant.

        Args:
            tenant_id: Tenant ID to invalidate.

        Returns:
            Number of keys deleted.
        """
        pattern = self.key_builder.pattern(KeyType.QUERY, tenant_id)
        return await self.cache.delete_pattern(pattern)
