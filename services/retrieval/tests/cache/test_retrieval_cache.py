"""Tests for RetrievalCache."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from cache.retrieval_cache import (
    CacheConfig,
    CacheStats,
    RetrievalCache,
)


class TestCacheConfig:
    """Tests for CacheConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CacheConfig()

        assert config.enabled is True
        assert config.redis_url == "redis://localhost:6379"
        assert config.redis_password is None
        assert config.default_ttl_seconds == 3600
        assert config.key_prefix == "rag:query"
        assert config.max_cached_results == 100

    def test_custom_config(self):
        """Test custom configuration."""
        config = CacheConfig(
            enabled=False,
            redis_url="redis://redis:6380",
            redis_password="secret",
            default_ttl_seconds=7200,
            key_prefix="custom:prefix",
            max_cached_results=50,
        )

        assert config.enabled is False
        assert config.redis_url == "redis://redis:6380"
        assert config.redis_password == "secret"
        assert config.default_ttl_seconds == 7200
        assert config.key_prefix == "custom:prefix"
        assert config.max_cached_results == 50


class TestCacheStats:
    """Tests for CacheStats."""

    def test_initial_stats(self):
        """Test initial statistics."""
        stats = CacheStats()

        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.sets == 0
        assert stats.deletes == 0
        assert stats.errors == 0

    def test_hit_rate_empty(self):
        """Test hit rate with no operations."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self):
        """Test hit rate with all hits."""
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

    def test_hit_rate_mixed(self):
        """Test hit rate with mixed results."""
        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate == 0.3

    def test_avg_hit_time_empty(self):
        """Test average hit time with no hits."""
        stats = CacheStats()
        assert stats.avg_hit_time_ms == 0.0

    def test_avg_hit_time_with_data(self):
        """Test average hit time with data."""
        stats = CacheStats(hits=4, total_hit_time_ms=20.0)
        assert stats.avg_hit_time_ms == 5.0

    def test_avg_miss_time_with_data(self):
        """Test average miss time with data."""
        stats = CacheStats(misses=5, total_miss_time_ms=25.0)
        assert stats.avg_miss_time_ms == 5.0


class TestRetrievalCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_key_includes_tenant_id(self):
        """Test that key includes tenant ID."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key = cache._generate_cache_key(
            query="test query",
            tenant_id=tenant_id,
        )

        assert str(tenant_id) in key
        assert key.startswith("rag:query:")

    def test_different_queries_different_keys(self):
        """Test that different queries produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(query="query one", tenant_id=tenant_id)
        key2 = cache._generate_cache_key(query="query two", tenant_id=tenant_id)

        assert key1 != key2

    def test_same_query_same_key(self):
        """Test that same query produces same key."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(query="test query", tenant_id=tenant_id)
        key2 = cache._generate_cache_key(query="test query", tenant_id=tenant_id)

        assert key1 == key2

    def test_query_normalization(self):
        """Test that query is normalized (lowercase, stripped)."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(query="Test Query", tenant_id=tenant_id)
        key2 = cache._generate_cache_key(query="test query", tenant_id=tenant_id)
        key3 = cache._generate_cache_key(query="  test query  ", tenant_id=tenant_id)

        assert key1 == key2 == key3

    def test_different_modes_different_keys(self):
        """Test that different modes produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            mode="hybrid",
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            mode="semantic",
        )
        key3 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            mode="keyword",
        )

        assert key1 != key2 != key3

    def test_different_top_k_different_keys(self):
        """Test that different top_k produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(query="test", tenant_id=tenant_id, top_k=10)
        key2 = cache._generate_cache_key(query="test", tenant_id=tenant_id, top_k=20)

        assert key1 != key2

    def test_different_filters_different_keys(self):
        """Test that different filters produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            filters={"type": "doc"},
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            filters={"type": "code"},
        )
        key3 = cache._generate_cache_key(query="test", tenant_id=tenant_id, filters=None)

        assert key1 != key2 != key3

    def test_different_weights_different_keys(self):
        """Test that different weights produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            semantic_weight=0.7,
            keyword_weight=0.3,
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            semantic_weight=0.5,
            keyword_weight=0.5,
        )

        assert key1 != key2

    def test_different_rerank_different_keys(self):
        """Test that different rerank settings produce different keys."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(query="test", tenant_id=tenant_id, rerank=True)
        key2 = cache._generate_cache_key(query="test", tenant_id=tenant_id, rerank=False)

        assert key1 != key2

    def test_user_id_affects_key(self):
        """Test that user ID affects key for ACL scoping."""
        cache = RetrievalCache()
        tenant_id = uuid4()
        user_id1 = uuid4()
        user_id2 = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            user_id=user_id1,
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            user_id=user_id2,
        )
        key3 = cache._generate_cache_key(query="test", tenant_id=tenant_id, user_id=None)

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_different_tenants_different_keys(self):
        """Test that different tenants produce different keys."""
        cache = RetrievalCache()
        tenant1 = uuid4()
        tenant2 = uuid4()

        key1 = cache._generate_cache_key(query="test", tenant_id=tenant1)
        key2 = cache._generate_cache_key(query="test", tenant_id=tenant2)

        assert key1 != key2

    def test_min_score_affects_key(self):
        """Test that min_score affects key."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            min_score=0.5,
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            min_score=0.7,
        )
        key3 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            min_score=None,
        )

        assert key1 != key2
        assert key1 != key3


class TestRetrievalCacheDisabled:
    """Tests for cache when disabled."""

    def test_cache_disabled_by_config(self):
        """Test that cache is disabled when config says so."""
        config = CacheConfig(enabled=False)
        cache = RetrievalCache(config)

        assert cache.is_enabled is False

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self):
        """Test that get returns None when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = RetrievalCache(config)

        result = await cache.get(query="test", tenant_id=uuid4())

        assert result is None
        assert cache.stats.misses == 1

    @pytest.mark.asyncio
    async def test_set_returns_false_when_disabled(self):
        """Test that set returns False when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = RetrievalCache(config)

        result = await cache.set(
            query="test",
            tenant_id=uuid4(),
            results={"data": "test"},
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_connect_returns_false_when_disabled(self):
        """Test that connect returns False when disabled."""
        config = CacheConfig(enabled=False)
        cache = RetrievalCache(config)

        result = await cache.connect()

        assert result is False


class TestRetrievalCacheOperations:
    """Tests for cache operations with mocked Redis."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=1)
        return mock

    @pytest.fixture
    def cache_with_mock(self, mock_redis):
        """Create cache with mocked Redis."""
        cache = RetrievalCache()
        cache._redis = mock_redis
        cache._connected = True
        return cache

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, cache_with_mock):
        """Test cache miss."""
        result = await cache_with_mock.get(query="test", tenant_id=uuid4())

        assert result is None
        assert cache_with_mock.stats.misses == 1

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, cache_with_mock, mock_redis):
        """Test cache hit."""
        cached_data = {
            "cached_at": "2024-01-01T00:00:00",
            "data": {"results": [{"id": "1"}]},
        }
        mock_redis.get.return_value = json.dumps(cached_data)

        result = await cache_with_mock.get(query="test", tenant_id=uuid4())

        assert result is not None
        assert "cached_at" in result
        assert "data" in result
        assert cache_with_mock.stats.hits == 1

    @pytest.mark.asyncio
    async def test_set_success(self, cache_with_mock, mock_redis):
        """Test successful cache set."""
        result = await cache_with_mock.set(
            query="test",
            tenant_id=uuid4(),
            results={"results": [{"id": "1"}]},
        )

        assert result is True
        assert cache_with_mock.stats.sets == 1
        mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, cache_with_mock, mock_redis):
        """Test cache set with custom TTL."""
        await cache_with_mock.set(
            query="test",
            tenant_id=uuid4(),
            results={"results": []},
            ttl_seconds=7200,
        )

        # Verify TTL was passed
        call_args = mock_redis.set.call_args
        assert call_args[1]["ex"] == 7200

    @pytest.mark.asyncio
    async def test_delete_success(self, cache_with_mock, mock_redis):
        """Test successful cache delete."""
        result = await cache_with_mock.delete(query="test", tenant_id=uuid4())

        assert result is True
        assert cache_with_mock.stats.deletes == 1

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, cache_with_mock, mock_redis):
        """Test health check when healthy."""
        result = await cache_with_mock.health_check()

        assert result is True
        mock_redis.ping.assert_called()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, cache_with_mock, mock_redis):
        """Test health check when unhealthy."""
        mock_redis.ping.side_effect = Exception("Connection failed")

        result = await cache_with_mock.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        """Test health check when not connected."""
        cache = RetrievalCache()

        result = await cache.health_check()

        assert result is False


class TestRetrievalCacheInvalidation:
    """Tests for cache invalidation."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client with scan_iter."""
        mock = AsyncMock()

        async def mock_scan_iter(match=None):
            if match:
                # Yield some matching keys
                for key in [f"{match[:-1]}key1", f"{match[:-1]}key2"]:
                    yield key

        mock.scan_iter = mock_scan_iter
        mock.delete = AsyncMock(return_value=2)
        return mock

    @pytest.fixture
    def cache_with_mock(self, mock_redis):
        """Create cache with mocked Redis."""
        cache = RetrievalCache()
        cache._redis = mock_redis
        cache._connected = True
        return cache

    @pytest.mark.asyncio
    async def test_invalidate_tenant(self, cache_with_mock, mock_redis):
        """Test invalidating all cache for a tenant."""
        tenant_id = uuid4()

        deleted = await cache_with_mock.invalidate_tenant(tenant_id)

        assert deleted == 2
        assert cache_with_mock.stats.deletes == 2

    @pytest.mark.asyncio
    async def test_invalidate_all(self, cache_with_mock, mock_redis):
        """Test invalidating all cache."""
        deleted = await cache_with_mock.invalidate_all()

        assert deleted == 2
        assert cache_with_mock.stats.deletes == 2


class TestRetrievalCacheMetrics:
    """Tests for cache metrics."""

    def test_get_metrics(self):
        """Test getting metrics."""
        cache = RetrievalCache()
        cache._stats = CacheStats(
            hits=10,
            misses=5,
            sets=15,
            deletes=3,
            errors=1,
            total_hit_time_ms=50.0,
            total_miss_time_ms=25.0,
        )
        cache._connected = True

        metrics = cache.get_metrics()

        assert metrics["cache_hits_total"] == 10
        assert metrics["cache_misses_total"] == 5
        assert metrics["cache_sets_total"] == 15
        assert metrics["cache_deletes_total"] == 3
        assert metrics["cache_errors_total"] == 1
        assert metrics["cache_hit_rate"] == pytest.approx(0.666, rel=0.01)
        assert metrics["cache_avg_hit_time_ms"] == 5.0
        assert metrics["cache_avg_miss_time_ms"] == 5.0
        assert metrics["cache_enabled"] == 1
        assert metrics["cache_connected"] == 1

    def test_get_metrics_disabled(self):
        """Test metrics when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = RetrievalCache(config)

        metrics = cache.get_metrics()

        assert metrics["cache_enabled"] == 0
        assert metrics["cache_connected"] == 0


class TestRetrievalCacheContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_disabled(self):
        """Test context manager when disabled."""
        config = CacheConfig(enabled=False)

        async with RetrievalCache(config) as cache:
            assert cache.is_enabled is False

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_disconnects(self):
        """Test that context manager connects and disconnects."""
        with patch("cache.retrieval_cache.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.close = AsyncMock()
            mock_redis_module.from_url.return_value = mock_client

            config = CacheConfig(enabled=True)
            cache = RetrievalCache(config)

            async with cache:
                assert cache._connected is True

            mock_client.close.assert_called_once()


class TestCacheKeyStability:
    """Tests for cache key stability across calls."""

    def test_key_is_deterministic(self):
        """Test that cache key generation is deterministic."""
        cache = RetrievalCache()
        tenant_id = uuid4()
        user_id = uuid4()
        filters = {"type": "doc", "source": "wiki"}

        keys = [
            cache._generate_cache_key(
                query="test query",
                tenant_id=tenant_id,
                user_id=user_id,
                mode="hybrid",
                top_k=10,
                filters=filters,
                semantic_weight=0.7,
                keyword_weight=0.3,
                rerank=True,
                min_score=0.5,
            )
            for _ in range(10)
        ]

        # All keys should be identical
        assert len(set(keys)) == 1

    def test_filter_order_does_not_affect_key(self):
        """Test that filter key order doesn't affect cache key."""
        cache = RetrievalCache()
        tenant_id = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            filters={"a": 1, "b": 2, "c": 3},
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            filters={"c": 3, "a": 1, "b": 2},
        )

        assert key1 == key2
