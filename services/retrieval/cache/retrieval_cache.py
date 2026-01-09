"""Retrieval cache implementation with Redis backend.

Implements US-3.9 requirements:
- Cache key derived from query + filters using SHA-256
- TTL configurable (default 3600s)
- Tenant/ACL scoping
- Cache hit/miss metrics
- Feature flag to disable cache
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None


@dataclass
class CacheConfig:
    """Configuration for retrieval cache."""

    enabled: bool = True
    redis_url: str = "redis://localhost:6379"
    redis_password: Optional[str] = None
    default_ttl_seconds: int = 3600  # 1 hour per US-3.9
    key_prefix: str = "rag:query"
    max_cached_results: int = 100  # Max results to cache per query


@dataclass
class CacheStats:
    """Statistics for cache operations."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    errors: int = 0
    total_hit_time_ms: float = 0.0
    total_miss_time_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def avg_hit_time_ms(self) -> float:
        """Average time for cache hits."""
        return self.total_hit_time_ms / self.hits if self.hits > 0 else 0.0

    @property
    def avg_miss_time_ms(self) -> float:
        """Average time for cache misses."""
        return self.total_miss_time_ms / self.misses if self.misses > 0 else 0.0


class RetrievalCache:
    """Redis-based cache for retrieval results.

    Key format: {prefix}:{tenant_id}:{hash}
    Hash is SHA-256 of: query + filters + options (stable JSON)
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        """Initialize retrieval cache.

        Args:
            config: Cache configuration. Uses defaults if not provided.
        """
        self.config = config or CacheConfig()
        self._redis: Optional[Any] = None
        self._stats = CacheStats()
        self._connected = False

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    @property
    def is_enabled(self) -> bool:
        """Check if cache is enabled."""
        return self.config.enabled and HAS_REDIS

    async def connect(self) -> bool:
        """Connect to Redis.

        Returns:
            True if connected successfully, False otherwise.
        """
        if not HAS_REDIS:
            return False

        if not self.config.enabled:
            return False

        try:
            self._redis = redis.from_url(
                self.config.redis_url,
                password=self.config.redis_password,
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            self._connected = True
            return True
        except Exception:
            self._connected = False
            self._stats.errors += 1
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False

    async def health_check(self) -> bool:
        """Check if cache is healthy.

        Returns:
            True if cache is connected and responding.
        """
        if not self._connected or not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    def _generate_cache_key(
        self,
        query: str,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        rerank: bool = True,
        min_score: Optional[float] = None,
    ) -> str:
        """Generate a unique cache key for a query.

        The key includes all parameters that affect the results:
        - Query text
        - Tenant ID (for isolation)
        - User ID hash (for ACL-scoped results)
        - Search mode
        - Top K
        - Filters (stable JSON)
        - Weights
        - Rerank flag
        - Min score threshold

        Args:
            query: The search query.
            tenant_id: Tenant UUID for isolation.
            user_id: Optional user UUID for ACL scoping.
            mode: Search mode (hybrid, semantic, keyword).
            top_k: Number of results.
            filters: Metadata filters.
            semantic_weight: Weight for semantic search.
            keyword_weight: Weight for keyword search.
            rerank: Whether reranking is applied.
            min_score: Minimum score threshold.

        Returns:
            Cache key in format: {prefix}:{tenant_id}:{hash}
        """
        # Build stable representation of all parameters
        params = {
            "query": query.strip().lower(),  # Normalize query
            "mode": mode,
            "top_k": top_k,
            "semantic_weight": round(semantic_weight, 2),
            "keyword_weight": round(keyword_weight, 2),
            "rerank": rerank,
            "min_score": min_score,
            "filters": filters or {},
        }

        # Add user ID hash if provided (for ACL-scoped caching)
        if user_id:
            params["user_id_hash"] = hashlib.sha256(
                str(user_id).encode()
            ).hexdigest()[:16]

        # Generate stable JSON (sorted keys for consistency)
        params_json = json.dumps(params, sort_keys=True, separators=(",", ":"))

        # Hash the parameters
        params_hash = hashlib.sha256(params_json.encode()).hexdigest()[:32]

        return f"{self.config.key_prefix}:{tenant_id}:{params_hash}"

    async def get(
        self,
        query: str,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        rerank: bool = True,
        min_score: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """Get cached retrieval results.

        Args:
            query: The search query.
            tenant_id: Tenant UUID for isolation.
            user_id: Optional user UUID for ACL scoping.
            mode: Search mode.
            top_k: Number of results.
            filters: Metadata filters.
            semantic_weight: Weight for semantic search.
            keyword_weight: Weight for keyword search.
            rerank: Whether reranking is applied.
            min_score: Minimum score threshold.

        Returns:
            Cached results dict or None if not found.
        """
        if not self.is_enabled or not self._connected:
            self._stats.misses += 1
            return None

        start_time = time.perf_counter()

        try:
            key = self._generate_cache_key(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                mode=mode,
                top_k=top_k,
                filters=filters,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                rerank=rerank,
                min_score=min_score,
            )

            result = await self._redis.get(key)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if result:
                self._stats.hits += 1
                self._stats.total_hit_time_ms += elapsed_ms
                return json.loads(result)
            else:
                self._stats.misses += 1
                self._stats.total_miss_time_ms += elapsed_ms
                return None

        except Exception:
            self._stats.misses += 1
            self._stats.errors += 1
            return None

    async def set(
        self,
        query: str,
        tenant_id: UUID,
        results: dict[str, Any],
        user_id: Optional[UUID] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        rerank: bool = True,
        min_score: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Cache retrieval results.

        Args:
            query: The search query.
            tenant_id: Tenant UUID for isolation.
            results: Results dict to cache.
            user_id: Optional user UUID for ACL scoping.
            mode: Search mode.
            top_k: Number of results.
            filters: Metadata filters.
            semantic_weight: Weight for semantic search.
            keyword_weight: Weight for keyword search.
            rerank: Whether reranking is applied.
            min_score: Minimum score threshold.
            ttl_seconds: Custom TTL. Uses default if not provided.

        Returns:
            True if cached successfully.
        """
        if not self.is_enabled or not self._connected:
            return False

        try:
            key = self._generate_cache_key(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                mode=mode,
                top_k=top_k,
                filters=filters,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                rerank=rerank,
                min_score=min_score,
            )

            # Add cache metadata
            cache_entry = {
                "cached_at": datetime.utcnow().isoformat(),
                "data": results,
            }

            ttl = ttl_seconds or self.config.default_ttl_seconds

            await self._redis.set(
                key,
                json.dumps(cache_entry, default=str),
                ex=ttl,
            )

            self._stats.sets += 1
            return True

        except Exception:
            self._stats.errors += 1
            return False

    async def delete(
        self,
        query: str,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        mode: str = "hybrid",
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        rerank: bool = True,
        min_score: Optional[float] = None,
    ) -> bool:
        """Delete cached results for a specific query.

        Args:
            query: The search query.
            tenant_id: Tenant UUID for isolation.
            user_id: Optional user UUID for ACL scoping.
            mode: Search mode.
            top_k: Number of results.
            filters: Metadata filters.
            semantic_weight: Weight for semantic search.
            keyword_weight: Weight for keyword search.
            rerank: Whether reranking is applied.
            min_score: Minimum score threshold.

        Returns:
            True if deleted successfully.
        """
        if not self.is_enabled or not self._connected:
            return False

        try:
            key = self._generate_cache_key(
                query=query,
                tenant_id=tenant_id,
                user_id=user_id,
                mode=mode,
                top_k=top_k,
                filters=filters,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                rerank=rerank,
                min_score=min_score,
            )

            await self._redis.delete(key)
            self._stats.deletes += 1
            return True

        except Exception:
            self._stats.errors += 1
            return False

    async def invalidate_tenant(self, tenant_id: UUID) -> int:
        """Invalidate all cached queries for a tenant.

        Use this when ACL-relevant changes occur.

        Args:
            tenant_id: Tenant UUID to invalidate.

        Returns:
            Number of keys deleted.
        """
        if not self.is_enabled or not self._connected:
            return 0

        try:
            pattern = f"{self.config.key_prefix}:{tenant_id}:*"
            keys = []

            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self._redis.delete(*keys)
                self._stats.deletes += deleted
                return deleted

            return 0

        except Exception:
            self._stats.errors += 1
            return 0

    async def invalidate_all(self) -> int:
        """Invalidate all cached queries.

        Use this when re-embedding jobs complete.

        Returns:
            Number of keys deleted.
        """
        if not self.is_enabled or not self._connected:
            return 0

        try:
            pattern = f"{self.config.key_prefix}:*"
            keys = []

            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self._redis.delete(*keys)
                self._stats.deletes += deleted
                return deleted

            return 0

        except Exception:
            self._stats.errors += 1
            return 0

    def get_metrics(self) -> dict[str, Any]:
        """Get cache metrics for Prometheus export.

        Returns:
            Dict with cache metrics.
        """
        return {
            "cache_hits_total": self._stats.hits,
            "cache_misses_total": self._stats.misses,
            "cache_sets_total": self._stats.sets,
            "cache_deletes_total": self._stats.deletes,
            "cache_errors_total": self._stats.errors,
            "cache_hit_rate": self._stats.hit_rate,
            "cache_avg_hit_time_ms": self._stats.avg_hit_time_ms,
            "cache_avg_miss_time_ms": self._stats.avg_miss_time_ms,
            "cache_enabled": 1 if self.is_enabled else 0,
            "cache_connected": 1 if self._connected else 0,
        }

    async def __aenter__(self) -> "RetrievalCache":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
