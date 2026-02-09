"""Answer-level caching for the Orchestrator Service.

Implements US-10.5.3: Cache complete RAG responses to serve instant answers
for repeated questions, reducing LLM costs.

Features:
- Cache key: (tenant_id, normalized_query, retrieval_config_hash, prompt_version)
- On cache hit: return stored response and citations (skip retrieval+LLM)
- Configurable TTL per tenant (default: 1 hour)
- Cache invalidation when source documents change
- Metrics: answer_cache_hit_total, answer_cache_miss_total
"""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field

try:
    import redis.asyncio as redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)


class CachedAnswer(BaseModel):
    """Cached RAG answer."""

    response: str = Field(..., description="The generated response text")
    citations: list[dict] = Field(
        default_factory=list,
        description="Citation/source documents",
    )
    model_used: str = Field(..., description="Model used for generation")
    cached_at: str = Field(
        default_factory=lambda: datetime.now(tz=UTC).isoformat(),
        description="Timestamp when the answer was cached",
    )
    retrieval_mode: str = Field(
        default="hybrid",
        description="Retrieval mode used",
    )
    strategy: str = Field(
        default="simple",
        description="Routing strategy used",
    )
    document_ids: list[str] = Field(
        default_factory=list,
        description="Document IDs used in this response (for invalidation)",
    )


@dataclass
class AnswerCacheConfig:
    """Configuration for answer cache."""

    enabled: bool = True
    redis_url: str = "redis://localhost:6379"
    redis_password: str | None = None
    default_ttl_seconds: int = 3600  # 1 hour per spec
    key_prefix: str = "rag:answer_cache"
    prompt_version: str = "v1"  # Bump when prompt templates change


@dataclass
class AnswerCacheStats:
    """Statistics for answer cache operations."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    invalidations: int = 0
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


class AnswerCache:
    """Cache for complete RAG answers.

    Key format: {prefix}:{tenant_id}:{query_hash}:{config_hash}

    The cache key includes:
    - tenant_id: Tenant isolation
    - query_hash: SHA-256 of normalized query
    - config_hash: Hash of retrieval config + prompt version
    """

    def __init__(self, config: AnswerCacheConfig | None = None):
        """Initialize answer cache.

        Args:
            config: Cache configuration. Uses defaults if not provided.
        """
        self.config = config or AnswerCacheConfig()
        self._redis: Any | None = None
        self._stats = AnswerCacheStats()
        self._connected = False
        self._tenant_ttls: dict[str, int] = {}

    @property
    def stats(self) -> AnswerCacheStats:
        """Get cache statistics."""
        return self._stats

    @property
    def is_enabled(self) -> bool:
        """Check if cache is enabled."""
        return self.config.enabled and HAS_REDIS

    def set_tenant_ttl(self, tenant_id: str, ttl_seconds: int) -> None:
        """Set a custom TTL for a specific tenant.

        Args:
            tenant_id: Tenant identifier.
            ttl_seconds: TTL in seconds for this tenant.
        """
        self._tenant_ttls[tenant_id] = ttl_seconds

    def get_tenant_ttl(self, tenant_id: str) -> int:
        """Get TTL for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            TTL in seconds (tenant-specific or default).
        """
        return self._tenant_ttls.get(tenant_id, self.config.default_ttl_seconds)

    async def connect(self) -> bool:
        """Connect to Redis.

        Returns:
            True if connected successfully, False otherwise.
        """
        if not HAS_REDIS:
            logger.warning("Redis library not available, answer cache disabled")
            return False

        if not self.config.enabled:
            return False

        try:
            self._redis = redis.from_url(
                self.config.redis_url,
                password=self.config.redis_password,
                decode_responses=True,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("Answer cache connected to Redis")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis for answer cache: {e}")
            self._connected = False
            self._stats.errors += 1
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
            logger.info("Answer cache disconnected from Redis")

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

    def _normalize_query(self, query: str) -> str:
        """Normalize query for cache key.

        Normalizes by:
        - Lowercasing
        - Stripping whitespace
        - Collapsing multiple spaces

        Args:
            query: Original query string.

        Returns:
            Normalized query string.
        """
        normalized = query.lower().strip()
        # Collapse multiple spaces
        return " ".join(normalized.split())

    def _compute_config_hash(
        self,
        retrieval_mode: str = "hybrid",
        top_k: int = 10,
        rerank: bool = False,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        extra_config: dict | None = None,
    ) -> str:
        """Compute hash of retrieval configuration.

        Args:
            retrieval_mode: Search mode (hybrid, semantic, keyword).
            top_k: Number of results.
            rerank: Whether reranking is enabled.
            semantic_weight: Weight for semantic search.
            keyword_weight: Weight for keyword search.
            extra_config: Additional configuration options.

        Returns:
            SHA-256 hash of configuration (first 16 chars).
        """
        config_dict = {
            "mode": retrieval_mode,
            "top_k": top_k,
            "rerank": rerank,
            "semantic_weight": round(semantic_weight, 2),
            "keyword_weight": round(keyword_weight, 2),
            "prompt_version": self.config.prompt_version,
        }

        if extra_config:
            config_dict.update(extra_config)

        config_json = json.dumps(config_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(config_json.encode()).hexdigest()[:16]

    def _build_key(
        self,
        tenant_id: str,
        query: str,
        config_hash: str,
    ) -> str:
        """Build cache key from components.

        Args:
            tenant_id: Tenant identifier.
            query: User query (will be normalized).
            config_hash: Hash of retrieval configuration.

        Returns:
            Cache key string.
        """
        normalized_query = self._normalize_query(query)
        query_hash = hashlib.sha256(normalized_query.encode()).hexdigest()[:16]
        return f"{self.config.key_prefix}:{tenant_id}:{query_hash}:{config_hash}"

    def _build_doc_index_key(self, tenant_id: str, document_id: str) -> str:
        """Build key for document-to-cache-key index.

        Args:
            tenant_id: Tenant identifier.
            document_id: Document identifier.

        Returns:
            Index key string.
        """
        return f"{self.config.key_prefix}:doc_index:{tenant_id}:{document_id}"

    async def get(
        self,
        tenant_id: str,
        query: str,
        config_hash: str,
    ) -> CachedAnswer | None:
        """Get cached answer if available.

        Args:
            tenant_id: Tenant identifier.
            query: User query.
            config_hash: Hash of retrieval configuration.

        Returns:
            CachedAnswer if found, None otherwise.
        """
        if not self.is_enabled or not self._connected:
            self._stats.misses += 1
            return None

        start_time = time.perf_counter()

        try:
            key = self._build_key(tenant_id, query, config_hash)
            data = await self._redis.get(key)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if data:
                self._stats.hits += 1
                self._stats.total_hit_time_ms += elapsed_ms
                logger.info(
                    "answer_cache_hit",
                    extra={
                        "tenant_id": tenant_id,
                        "query_preview": query[:50],
                        "elapsed_ms": elapsed_ms,
                    },
                )
                return CachedAnswer(**json.loads(data))

            self._stats.misses += 1
            self._stats.total_miss_time_ms += elapsed_ms
            return None

        except Exception as e:
            logger.warning(f"Error getting from answer cache: {e}")
            self._stats.misses += 1
            self._stats.errors += 1
            return None

    async def set(
        self,
        tenant_id: str,
        query: str,
        config_hash: str,
        answer: CachedAnswer,
        ttl: int | None = None,
    ) -> bool:
        """Cache an answer.

        Args:
            tenant_id: Tenant identifier.
            query: User query.
            config_hash: Hash of retrieval configuration.
            answer: The answer to cache.
            ttl: Optional custom TTL. Uses tenant TTL if not provided.

        Returns:
            True if cached successfully.
        """
        if not self.is_enabled or not self._connected:
            return False

        try:
            key = self._build_key(tenant_id, query, config_hash)
            effective_ttl = ttl or self.get_tenant_ttl(tenant_id)

            # Store the answer
            await self._redis.setex(
                key,
                effective_ttl,
                answer.model_dump_json(),
            )

            # Index by document IDs for invalidation
            for doc_id in answer.document_ids:
                doc_index_key = self._build_doc_index_key(tenant_id, doc_id)
                await self._redis.sadd(doc_index_key, key)
                await self._redis.expire(doc_index_key, effective_ttl)

            self._stats.sets += 1
            logger.info(
                "answer_cache_set",
                extra={
                    "tenant_id": tenant_id,
                    "query_preview": query[:50],
                    "ttl": effective_ttl,
                    "document_count": len(answer.document_ids),
                },
            )
            return True

        except Exception as e:
            logger.warning(f"Error setting answer cache: {e}")
            self._stats.errors += 1
            return False

    async def invalidate_for_document(
        self,
        tenant_id: str,
        document_id: str,
    ) -> int:
        """Invalidate cache entries that used a document.

        Called when a source document is updated or deleted.

        Args:
            tenant_id: Tenant identifier.
            document_id: Document identifier that changed.

        Returns:
            Number of cache entries invalidated.
        """
        if not self.is_enabled or not self._connected:
            return 0

        try:
            doc_index_key = self._build_doc_index_key(tenant_id, document_id)

            # Get all cache keys that reference this document
            cache_keys = await self._redis.smembers(doc_index_key)

            if not cache_keys:
                return 0

            # Delete all referencing cache entries
            deleted = await self._redis.delete(*cache_keys)

            # Clean up the index
            await self._redis.delete(doc_index_key)

            self._stats.invalidations += deleted
            logger.info(
                "answer_cache_invalidated",
                extra={
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "entries_invalidated": deleted,
                },
            )
            return deleted

        except Exception as e:
            logger.warning(f"Error invalidating answer cache: {e}")
            self._stats.errors += 1
            return 0

    async def invalidate_for_tenant(self, tenant_id: str) -> int:
        """Invalidate all cache entries for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Number of cache entries invalidated.
        """
        if not self.is_enabled or not self._connected:
            return 0

        try:
            pattern = f"{self.config.key_prefix}:{tenant_id}:*"
            keys: list[str] = []

            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            if not keys:
                return 0

            deleted = await self._redis.delete(*keys)
            self._stats.invalidations += deleted

            logger.info(
                "answer_cache_tenant_invalidated",
                extra={
                    "tenant_id": tenant_id,
                    "entries_invalidated": deleted,
                },
            )
            return deleted

        except Exception as e:
            logger.warning(f"Error invalidating tenant cache: {e}")
            self._stats.errors += 1
            return 0

    def get_metrics(self) -> dict[str, Any]:
        """Get cache metrics for Prometheus export.

        Returns:
            Dict with cache metrics.
        """
        return {
            "answer_cache_hit_total": self._stats.hits,
            "answer_cache_miss_total": self._stats.misses,
            "answer_cache_set_total": self._stats.sets,
            "answer_cache_invalidation_total": self._stats.invalidations,
            "answer_cache_error_total": self._stats.errors,
            "answer_cache_hit_rate": self._stats.hit_rate,
            "answer_cache_avg_hit_time_ms": self._stats.avg_hit_time_ms,
            "answer_cache_enabled": 1 if self.is_enabled else 0,
            "answer_cache_connected": 1 if self._connected else 0,
        }

    async def __aenter__(self) -> "AnswerCache":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()
