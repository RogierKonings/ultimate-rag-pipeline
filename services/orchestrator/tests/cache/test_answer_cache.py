"""Tests for the AnswerCache implementation.

Tests US-10.5.3: Answer-Level Caching
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cache.answer_cache import AnswerCache, AnswerCacheConfig, CachedAnswer


@pytest.fixture
def cache_config():
    """Create test cache configuration."""
    return AnswerCacheConfig(
        enabled=True,
        redis_url="redis://localhost:6379/1",
        default_ttl_seconds=3600,
        key_prefix="test:answer_cache",
        prompt_version="v1",
    )


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.sadd = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.smembers = AsyncMock(return_value=set())
    redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([]))
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


class AsyncIteratorMock:
    """Mock async iterator for scan_iter."""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


@pytest.fixture
def answer_cache(cache_config, mock_redis):
    """Create an AnswerCache with mocked Redis."""
    cache = AnswerCache(config=cache_config)
    cache._redis = mock_redis
    cache._connected = True
    return cache


@pytest.fixture
def sample_cached_answer():
    """Create a sample cached answer."""
    return CachedAnswer(
        response="Python is a programming language.",
        citations=[
            {
                "content": "Python is versatile...",
                "score": 0.95,
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "metadata": {"title": "Python Intro"},
                "source": "docs/python.md",
            }
        ],
        model_used="llama-3.1-8b",
        retrieval_mode="hybrid",
        strategy="simple",
        document_ids=["doc-1"],
    )


class TestAnswerCacheConfig:
    """Tests for AnswerCacheConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AnswerCacheConfig()
        assert config.enabled is True
        assert config.default_ttl_seconds == 3600
        assert config.key_prefix == "rag:answer_cache"
        assert config.prompt_version == "v1"

    def test_custom_config(self):
        """Test custom configuration."""
        config = AnswerCacheConfig(
            enabled=False,
            default_ttl_seconds=7200,
            key_prefix="custom:cache",
            prompt_version="v2",
        )
        assert config.enabled is False
        assert config.default_ttl_seconds == 7200
        assert config.key_prefix == "custom:cache"
        assert config.prompt_version == "v2"


class TestCachedAnswer:
    """Tests for CachedAnswer model."""

    def test_cached_answer_creation(self, sample_cached_answer):
        """Test CachedAnswer model creation."""
        assert sample_cached_answer.response == "Python is a programming language."
        assert len(sample_cached_answer.citations) == 1
        assert sample_cached_answer.model_used == "llama-3.1-8b"
        assert sample_cached_answer.retrieval_mode == "hybrid"
        assert sample_cached_answer.strategy == "simple"
        assert sample_cached_answer.document_ids == ["doc-1"]

    def test_cached_answer_serialization(self, sample_cached_answer):
        """Test CachedAnswer JSON serialization."""
        json_str = sample_cached_answer.model_dump_json()
        data = json.loads(json_str)
        assert data["response"] == "Python is a programming language."
        assert data["model_used"] == "llama-3.1-8b"

    def test_cached_answer_deserialization(self, sample_cached_answer):
        """Test CachedAnswer JSON deserialization."""
        json_str = sample_cached_answer.model_dump_json()
        restored = CachedAnswer(**json.loads(json_str))
        assert restored.response == sample_cached_answer.response
        assert restored.model_used == sample_cached_answer.model_used


class TestAnswerCacheQueryNormalization:
    """Tests for query normalization."""

    def test_normalize_query_lowercase(self, answer_cache):
        """Test query is lowercased."""
        normalized = answer_cache._normalize_query("What Is Python?")
        assert normalized == "what is python?"

    def test_normalize_query_strip_whitespace(self, answer_cache):
        """Test whitespace is stripped."""
        normalized = answer_cache._normalize_query("  What is Python?  ")
        assert normalized == "what is python?"

    def test_normalize_query_collapse_spaces(self, answer_cache):
        """Test multiple spaces are collapsed."""
        normalized = answer_cache._normalize_query("What    is   Python?")
        assert normalized == "what is python?"


class TestAnswerCacheConfigHash:
    """Tests for config hash computation."""

    def test_config_hash_deterministic(self, answer_cache):
        """Test config hash is deterministic."""
        hash1 = answer_cache._compute_config_hash(
            retrieval_mode="hybrid",
            top_k=10,
            rerank=True,
        )
        hash2 = answer_cache._compute_config_hash(
            retrieval_mode="hybrid",
            top_k=10,
            rerank=True,
        )
        assert hash1 == hash2

    def test_config_hash_different_for_different_config(self, answer_cache):
        """Test config hash differs for different configs."""
        hash1 = answer_cache._compute_config_hash(
            retrieval_mode="hybrid",
            top_k=10,
            rerank=True,
        )
        hash2 = answer_cache._compute_config_hash(
            retrieval_mode="semantic",
            top_k=10,
            rerank=True,
        )
        assert hash1 != hash2

    def test_config_hash_length(self, answer_cache):
        """Test config hash is truncated to 16 chars."""
        hash_val = answer_cache._compute_config_hash()
        assert len(hash_val) == 16


class TestAnswerCacheKeyBuilding:
    """Tests for cache key building."""

    def test_build_key_format(self, answer_cache):
        """Test cache key format."""
        key = answer_cache._build_key(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )
        assert key.startswith("test:answer_cache:tenant-123:")
        assert ":abc123" in key

    def test_build_key_consistent(self, answer_cache):
        """Test cache key is consistent for same inputs."""
        key1 = answer_cache._build_key("t1", "What is Python?", "cfg1")
        key2 = answer_cache._build_key("t1", "What is Python?", "cfg1")
        assert key1 == key2

    def test_build_key_normalized_query(self, answer_cache):
        """Test cache key uses normalized query."""
        key1 = answer_cache._build_key("t1", "What is Python?", "cfg1")
        key2 = answer_cache._build_key("t1", "WHAT IS PYTHON?", "cfg1")
        assert key1 == key2


class TestAnswerCacheTenantTTL:
    """Tests for tenant-specific TTL."""

    def test_default_ttl(self, answer_cache):
        """Test default TTL is returned."""
        ttl = answer_cache.get_tenant_ttl("tenant-123")
        assert ttl == 3600

    def test_custom_tenant_ttl(self, answer_cache):
        """Test custom tenant TTL."""
        answer_cache.set_tenant_ttl("tenant-123", 7200)
        ttl = answer_cache.get_tenant_ttl("tenant-123")
        assert ttl == 7200

    def test_multiple_tenant_ttls(self, answer_cache):
        """Test multiple tenants with different TTLs."""
        answer_cache.set_tenant_ttl("tenant-1", 1800)
        answer_cache.set_tenant_ttl("tenant-2", 7200)
        assert answer_cache.get_tenant_ttl("tenant-1") == 1800
        assert answer_cache.get_tenant_ttl("tenant-2") == 7200
        assert answer_cache.get_tenant_ttl("tenant-3") == 3600  # default


class TestAnswerCacheGet:
    """Tests for cache get operations."""

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, answer_cache, mock_redis):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        result = await answer_cache.get(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )

        assert result is None
        assert answer_cache.stats.misses == 1

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, answer_cache, mock_redis, sample_cached_answer):
        """Test cache hit returns cached answer."""
        mock_redis.get.return_value = sample_cached_answer.model_dump_json()

        result = await answer_cache.get(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )

        assert result is not None
        assert result.response == sample_cached_answer.response
        assert answer_cache.stats.hits == 1

    @pytest.mark.asyncio
    async def test_get_disabled_cache(self, cache_config, mock_redis):
        """Test get returns None when cache disabled."""
        cache_config.enabled = False
        cache = AnswerCache(config=cache_config)
        cache._redis = mock_redis
        cache._connected = True

        result = await cache.get(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_not_connected(self, answer_cache, mock_redis):
        """Test get returns None when not connected."""
        answer_cache._connected = False

        result = await answer_cache.get(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_error_handling(self, answer_cache, mock_redis):
        """Test get handles Redis errors gracefully."""
        mock_redis.get.side_effect = Exception("Redis error")

        result = await answer_cache.get(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
        )

        assert result is None
        assert answer_cache.stats.errors == 1


class TestAnswerCacheSet:
    """Tests for cache set operations."""

    @pytest.mark.asyncio
    async def test_set_success(self, answer_cache, mock_redis, sample_cached_answer):
        """Test successful cache set."""
        result = await answer_cache.set(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
            answer=sample_cached_answer,
        )

        assert result is True
        assert answer_cache.stats.sets == 1
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, answer_cache, mock_redis, sample_cached_answer):
        """Test cache set with custom TTL."""
        await answer_cache.set(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
            answer=sample_cached_answer,
            ttl=1800,
        )

        # Verify TTL was passed to setex
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 1800

    @pytest.mark.asyncio
    async def test_set_indexes_document_ids(
        self, answer_cache, mock_redis, sample_cached_answer
    ):
        """Test cache set indexes by document IDs."""
        await answer_cache.set(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
            answer=sample_cached_answer,
        )

        # Should add cache key to document index
        mock_redis.sadd.assert_called()

    @pytest.mark.asyncio
    async def test_set_disabled_cache(self, cache_config, mock_redis, sample_cached_answer):
        """Test set returns False when cache disabled."""
        cache_config.enabled = False
        cache = AnswerCache(config=cache_config)
        cache._redis = mock_redis
        cache._connected = True

        result = await cache.set(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
            answer=sample_cached_answer,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_set_error_handling(self, answer_cache, mock_redis, sample_cached_answer):
        """Test set handles Redis errors gracefully."""
        mock_redis.setex.side_effect = Exception("Redis error")

        result = await answer_cache.set(
            tenant_id="tenant-123",
            query="What is Python?",
            config_hash="abc123",
            answer=sample_cached_answer,
        )

        assert result is False
        assert answer_cache.stats.errors == 1


class TestAnswerCacheInvalidation:
    """Tests for cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_for_document(self, answer_cache, mock_redis):
        """Test invalidation by document ID."""
        cache_keys = {"cache:key1", "cache:key2"}
        mock_redis.smembers.return_value = cache_keys

        deleted = await answer_cache.invalidate_for_document(
            tenant_id="tenant-123",
            document_id="doc-1",
        )

        assert deleted == 1  # mock_redis.delete returns 1
        assert answer_cache.stats.invalidations == 1

    @pytest.mark.asyncio
    async def test_invalidate_for_document_no_keys(self, answer_cache, mock_redis):
        """Test invalidation when no cached entries exist."""
        mock_redis.smembers.return_value = set()

        deleted = await answer_cache.invalidate_for_document(
            tenant_id="tenant-123",
            document_id="doc-1",
        )

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_invalidate_for_tenant(self, answer_cache, mock_redis):
        """Test invalidation by tenant ID."""
        mock_redis.scan_iter = MagicMock(
            return_value=AsyncIteratorMock(["key1", "key2", "key3"])
        )

        deleted = await answer_cache.invalidate_for_tenant(tenant_id="tenant-123")

        assert deleted == 1  # mock returns 1 from delete


class TestAnswerCacheMetrics:
    """Tests for cache metrics."""

    def test_get_metrics(self, answer_cache):
        """Test metrics retrieval."""
        answer_cache._stats.hits = 10
        answer_cache._stats.misses = 5
        answer_cache._stats.sets = 8

        metrics = answer_cache.get_metrics()

        assert metrics["answer_cache_hit_total"] == 10
        assert metrics["answer_cache_miss_total"] == 5
        assert metrics["answer_cache_set_total"] == 8
        assert metrics["answer_cache_enabled"] == 1
        assert metrics["answer_cache_connected"] == 1

    def test_hit_rate_calculation(self, answer_cache):
        """Test hit rate calculation."""
        answer_cache._stats.hits = 75
        answer_cache._stats.misses = 25

        assert answer_cache.stats.hit_rate == 0.75


class TestAnswerCacheConnection:
    """Tests for cache connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(self, cache_config):
        """Test successful connection."""
        with patch("cache.answer_cache.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis_module.from_url.return_value = mock_client

            cache = AnswerCache(config=cache_config)
            result = await cache.connect()

            assert result is True
            assert cache._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, cache_config):
        """Test connection failure."""
        with patch("cache.answer_cache.redis") as mock_redis_module:
            mock_redis_module.from_url.side_effect = Exception("Connection failed")

            cache = AnswerCache(config=cache_config)
            result = await cache.connect()

            assert result is False
            assert cache._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, answer_cache, mock_redis):
        """Test disconnection."""
        await answer_cache.disconnect()

        mock_redis.close.assert_called_once()
        assert answer_cache._connected is False

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, answer_cache, mock_redis):
        """Test health check when healthy."""
        result = await answer_cache.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, answer_cache, mock_redis):
        """Test health check when unhealthy."""
        mock_redis.ping.side_effect = Exception("Connection lost")

        result = await answer_cache.health_check()
        assert result is False


class TestAnswerCacheContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, cache_config):
        """Test async context manager."""
        with patch("cache.answer_cache.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.close = AsyncMock()
            mock_redis_module.from_url.return_value = mock_client

            async with AnswerCache(config=cache_config) as cache:
                assert cache._connected is True

            mock_client.close.assert_called_once()
