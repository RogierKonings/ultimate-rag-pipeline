"""Tests for UsageFlusher.

Reference: US-10.5.4 - Token Usage Accounting
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from usage.flush import UsageFlusher, UsageFlusherConfig


@pytest.fixture
def flusher_config():
    """Create test flusher configuration."""
    return UsageFlusherConfig(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_usage",
        flush_interval_seconds=60,
    )


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.delete = AsyncMock(return_value=1)
    redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([]))
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_session_factory():
    """Create a mock session factory."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    factory_mock = MagicMock()
    factory_mock.return_value.__aenter__ = AsyncMock(return_value=session)
    factory_mock.return_value.__aexit__ = AsyncMock(return_value=None)

    return factory_mock


class AsyncIteratorMock:
    """Mock for async iterators."""

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
def usage_flusher(flusher_config, mock_redis, mock_session_factory):
    """Create a UsageFlusher with mocked dependencies."""
    flusher = UsageFlusher(flusher_config, mock_session_factory)
    flusher._redis = mock_redis
    flusher._connected = True
    return flusher


class TestUsageFlusherConfig:
    """Tests for UsageFlusherConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = UsageFlusherConfig()

        assert config.redis_url == "redis://localhost:6379"
        assert config.key_prefix == "usage"
        assert config.flush_interval_seconds == 300

    def test_custom_config(self):
        """Test custom configuration values."""
        config = UsageFlusherConfig(
            redis_url="redis://custom:6379/1",
            redis_password="secret",
            key_prefix="custom_usage",
            flush_interval_seconds=120,
        )

        assert config.redis_url == "redis://custom:6379/1"
        assert config.redis_password == "secret"
        assert config.key_prefix == "custom_usage"
        assert config.flush_interval_seconds == 120


class TestFlush:
    """Tests for flush operation."""

    @pytest.mark.asyncio
    async def test_flush_no_keys(self, usage_flusher, mock_redis):
        """Test flush when no keys exist."""
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([]))

        flushed = await usage_flusher.flush()

        assert flushed == 0

    @pytest.mark.asyncio
    async def test_flush_single_key(self, usage_flusher, mock_redis, mock_session_factory):
        """Test flushing a single key."""
        # Set up mock data
        key = b"test_usage:tenant-123:2026-01-19:gpt-4"
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([key]))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"100",
                b"completion": b"50",
                b"embedding": b"0",
            }
        )

        flushed = await usage_flusher.flush()

        assert flushed == 1
        mock_redis.delete.assert_called_with(key)

    @pytest.mark.asyncio
    async def test_flush_multiple_keys(self, usage_flusher, mock_redis, mock_session_factory):
        """Test flushing multiple keys."""
        keys = [
            b"test_usage:tenant-123:2026-01-19:gpt-4",
            b"test_usage:tenant-123:2026-01-19:claude-3",
            b"test_usage:tenant-456:2026-01-18:gpt-4",
        ]
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock(keys))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"100",
                b"completion": b"50",
            }
        )

        flushed = await usage_flusher.flush()

        assert flushed == 3
        assert mock_redis.delete.call_count == 3

    @pytest.mark.asyncio
    async def test_flush_skips_empty_data(self, usage_flusher, mock_redis):
        """Test that flush skips keys with no data."""
        key = b"test_usage:tenant-123:2026-01-19:gpt-4"
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([key]))
        mock_redis.hgetall = AsyncMock(return_value={})

        flushed = await usage_flusher.flush()

        assert flushed == 0

    @pytest.mark.asyncio
    async def test_flush_skips_zero_usage(self, usage_flusher, mock_redis):
        """Test that flush skips keys with all zero values."""
        key = b"test_usage:tenant-123:2026-01-19:gpt-4"
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([key]))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"0",
                b"completion": b"0",
                b"embedding": b"0",
            }
        )

        flushed = await usage_flusher.flush()

        # Key should be deleted but not counted as flushed
        assert flushed == 0
        mock_redis.delete.assert_called_with(key)

    @pytest.mark.asyncio
    async def test_flush_not_connected(self, usage_flusher, mock_redis):
        """Test flush when not connected returns 0."""
        usage_flusher._connected = False

        flushed = await usage_flusher.flush()

        assert flushed == 0
        mock_redis.scan_iter.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_invalid_key_format(self, usage_flusher, mock_redis, mock_session_factory):
        """Test flush handles invalid key format gracefully."""
        keys = [
            b"test_usage:invalid",  # Missing parts
            b"test_usage:tenant-123:2026-01-19:gpt-4",  # Valid
        ]
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock(keys))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"100",
                b"completion": b"50",
            }
        )

        flushed = await usage_flusher.flush()

        # Only valid key should be flushed
        assert flushed == 1

    @pytest.mark.asyncio
    async def test_flush_invalid_date(self, usage_flusher, mock_redis):
        """Test flush handles invalid date in key gracefully."""
        key = b"test_usage:tenant-123:invalid-date:gpt-4"
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([key]))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"100",
            }
        )

        flushed = await usage_flusher.flush()

        assert flushed == 0

    @pytest.mark.asyncio
    async def test_flush_model_with_colons(self, usage_flusher, mock_redis, mock_session_factory):
        """Test flush handles model names with colons."""
        key = b"test_usage:tenant-123:2026-01-19:anthropic:claude-3:sonnet"
        mock_redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([key]))
        mock_redis.hgetall = AsyncMock(
            return_value={
                b"prompt": b"100",
                b"completion": b"50",
            }
        )

        flushed = await usage_flusher.flush()

        assert flushed == 1


class TestConnection:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(self, flusher_config, mock_session_factory):
        """Test successful connection."""
        with patch("usage.flush.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis_module.from_url.return_value = mock_client

            flusher = UsageFlusher(flusher_config, mock_session_factory)
            await flusher.connect()

            assert flusher._connected is True
            mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self, flusher_config, mock_session_factory):
        """Test connection failure."""
        with patch("usage.flush.redis") as mock_redis_module:
            mock_redis_module.from_url.side_effect = Exception("Connection refused")

            flusher = UsageFlusher(flusher_config, mock_session_factory)

            with pytest.raises(Exception, match="Connection refused"):
                await flusher.connect()

    @pytest.mark.asyncio
    async def test_disconnect(self, usage_flusher, mock_redis):
        """Test disconnection."""
        await usage_flusher.disconnect()

        mock_redis.close.assert_called_once()
        assert usage_flusher._connected is False


class TestContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, flusher_config, mock_session_factory):
        """Test async context manager usage."""
        with patch("usage.flush.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.close = AsyncMock()
            mock_redis_module.from_url.return_value = mock_client

            async with UsageFlusher(flusher_config, mock_session_factory) as flusher:
                assert flusher._connected is True

            mock_client.close.assert_called_once()
