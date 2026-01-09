"""Tests for the embedding cache."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from ..cache import EmbeddingCache
from ..models import EmbeddingCacheConfig


class TestEmbeddingCache:
    """Tests for EmbeddingCache."""

    @pytest.fixture
    def cache_config(self) -> EmbeddingCacheConfig:
        """Create test cache configuration."""
        return EmbeddingCacheConfig(
            redis_url="redis://localhost:6379",
            key_prefix="test_emb:",
            default_ttl=3600,
        )

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock()
        mock.delete = AsyncMock()
        mock.scan = AsyncMock(return_value=(0, []))
        mock.info = AsyncMock(return_value={"used_memory_human": "1M"})
        mock.close = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that get returns None when key not found."""
        cache = EmbeddingCache(cache_config)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await cache.get("nonexistent_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_embedding_when_found(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that get returns embedding when found."""
        cache = EmbeddingCache(cache_config)
        expected_embedding = [0.1, 0.2, 0.3]
        mock_redis.get.return_value = "[0.1, 0.2, 0.3]"

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            result = await cache.get("existing_key")
            assert result == expected_embedding

    @pytest.mark.asyncio
    async def test_set_stores_embedding(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that set stores embedding correctly."""
        cache = EmbeddingCache(cache_config)
        embedding = [0.1, 0.2, 0.3]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await cache.set("test_key", embedding, ttl=3600)

            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "test_emb:test_key"
            assert call_args[0][1] == 3600
            assert "[0.1, 0.2, 0.3]" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that set uses default TTL when not specified."""
        cache = EmbeddingCache(cache_config)
        embedding = [0.1, 0.2, 0.3]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await cache.set("test_key", embedding)

            call_args = mock_redis.setex.call_args
            assert call_args[0][1] == cache_config.default_ttl

    @pytest.mark.asyncio
    async def test_delete_removes_key(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that delete removes key."""
        cache = EmbeddingCache(cache_config)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await cache.delete("test_key")

            mock_redis.delete.assert_called_once_with("test_emb:test_key")

    @pytest.mark.asyncio
    async def test_clear_all_removes_all_keys(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that clear_all removes all keys with prefix."""
        cache = EmbeddingCache(cache_config)
        mock_redis.scan.side_effect = [
            (1, ["test_emb:key1", "test_emb:key2"]),
            (0, ["test_emb:key3"]),
        ]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await cache.clear_all()

            assert mock_redis.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_get_stats_returns_statistics(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that get_stats returns cache statistics."""
        cache = EmbeddingCache(cache_config)
        mock_redis.scan.side_effect = [
            (1, ["test_emb:key1", "test_emb:key2"]),
            (0, []),
        ]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            stats = await cache.get_stats()

            assert stats["cached_embeddings"] == 2
            assert stats["used_memory"] == "1M"
            assert stats["key_prefix"] == "test_emb:"

    @pytest.mark.asyncio
    async def test_context_manager(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test async context manager."""
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with EmbeddingCache(cache_config) as cache:
                assert cache._redis is not None

            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_key_prefix_applied(
        self, cache_config: EmbeddingCacheConfig, mock_redis
    ):
        """Test that key prefix is applied to all operations."""
        cache_config.key_prefix = "custom_prefix:"
        cache = EmbeddingCache(cache_config)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await cache.get("test_key")
            mock_redis.get.assert_called_with("custom_prefix:test_key")
