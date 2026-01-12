"""Tests for query cache."""

from unittest.mock import AsyncMock, patch

import pytest
from query.cache import QueryCache
from query.models import ProcessedQuery, QueryType


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.setex = AsyncMock()
    mock.delete = AsyncMock()
    mock.exists = AsyncMock(return_value=0)
    mock.ping = AsyncMock()
    mock.close = AsyncMock()

    async def mock_scan_iter(*args, **kwargs):
        return
        yield  # Make this an async generator

    mock.scan_iter = mock_scan_iter
    return mock


@pytest.fixture
def sample_query():
    """Create sample processed query."""
    return ProcessedQuery(
        original_query="test query",
        normalized_query="test query",
        embedding=[0.1] * 1024,
        query_type=QueryType.SIMPLE,
        tokens=5,
        processing_time_ms=10.0,
    )


class TestQueryCache:
    """Tests for QueryCache."""

    def test_init_defaults(self):
        """Test default initialization."""
        cache = QueryCache()

        assert cache.redis_url == "redis://localhost:6379"
        assert cache.key_prefix == "query_cache:"
        assert cache.default_ttl == 3600

    def test_init_custom(self):
        """Test custom initialization."""
        cache = QueryCache(
            redis_url="redis://custom:6380",
            key_prefix="custom:",
            default_ttl=7200,
        )

        assert cache.redis_url == "redis://custom:6380"
        assert cache.key_prefix == "custom:"
        assert cache.default_ttl == 7200

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, mock_redis):
        """Test cache miss returns None."""
        cache = QueryCache()
        cache._redis = mock_redis

        mock_redis.get.return_value = None

        result = await cache.get("test_key")

        assert result is None
        mock_redis.get.assert_called_once_with("query_cache:test_key")

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, mock_redis, sample_query):
        """Test cache hit returns ProcessedQuery."""
        cache = QueryCache()
        cache._redis = mock_redis

        mock_redis.get.return_value = sample_query.model_dump_json()

        result = await cache.get("test_key")

        assert result is not None
        assert result.original_query == "test query"
        assert result.normalized_query == "test query"

    @pytest.mark.asyncio
    async def test_set_uses_ttl(self, mock_redis, sample_query):
        """Test set uses default TTL."""
        cache = QueryCache()
        cache._redis = mock_redis

        await cache.set("test_key", sample_query)

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[0] == "query_cache:test_key"
        assert args[1] == 3600  # default TTL

    @pytest.mark.asyncio
    async def test_set_custom_ttl(self, mock_redis, sample_query):
        """Test set with custom TTL."""
        cache = QueryCache()
        cache._redis = mock_redis

        await cache.set("test_key", sample_query, ttl=600)

        args = mock_redis.setex.call_args[0]
        assert args[1] == 600

    @pytest.mark.asyncio
    async def test_delete(self, mock_redis):
        """Test delete removes key."""
        cache = QueryCache()
        cache._redis = mock_redis

        await cache.delete("test_key")

        mock_redis.delete.assert_called_once_with("query_cache:test_key")

    @pytest.mark.asyncio
    async def test_exists_true(self, mock_redis):
        """Test exists returns True when key exists."""
        cache = QueryCache()
        cache._redis = mock_redis
        mock_redis.exists.return_value = 1

        result = await cache.exists("test_key")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, mock_redis):
        """Test exists returns False when key doesn't exist."""
        cache = QueryCache()
        cache._redis = mock_redis
        mock_redis.exists.return_value = 0

        result = await cache.exists("test_key")

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_redis):
        """Test health check returns True on success."""
        cache = QueryCache()
        cache._redis = mock_redis

        result = await cache.health_check()

        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_redis):
        """Test health check returns False on failure."""
        cache = QueryCache()
        cache._redis = mock_redis
        mock_redis.ping.side_effect = Exception("Connection failed")

        result = await cache.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_from_url.return_value = mock_redis

            async with QueryCache() as cache:
                assert cache._redis is not None

            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_lazy(self, mock_redis):
        """Test that connect is called lazily."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_from_url.return_value = mock_redis

            cache = QueryCache()
            assert cache._redis is None

            # First operation should trigger connect
            await cache.get("test")

            mock_from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_redis):
        """Test disconnect closes connection."""
        cache = QueryCache()
        cache._redis = mock_redis

        await cache.disconnect()

        mock_redis.close.assert_called_once()
        assert cache._redis is None


class TestQueryCacheIntegration:
    """Integration-style tests for QueryCache."""

    @pytest.mark.asyncio
    async def test_roundtrip(self, mock_redis, sample_query):
        """Test storing and retrieving a query."""
        cache = QueryCache()
        cache._redis = mock_redis

        # Store query
        await cache.set("test_key", sample_query)

        # Mock the get to return what was set
        mock_redis.get.return_value = sample_query.model_dump_json()

        # Retrieve query
        retrieved = await cache.get("test_key")

        assert retrieved is not None
        assert retrieved.original_query == sample_query.original_query
        assert retrieved.embedding == sample_query.embedding
        assert retrieved.query_type == sample_query.query_type
