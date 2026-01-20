"""Tests for UsageTracker.

Reference: US-10.5.4 - Token Usage Accounting
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from usage.quota import QuotaExceededError
from usage.tracker import UsageTracker, UsageTrackerConfig


@pytest.fixture
def tracker_config():
    """Create test tracker configuration."""
    return UsageTrackerConfig(
        redis_url="redis://localhost:6379/1",
        key_prefix="test_usage",
        key_ttl_seconds=3600,
    )


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.hincrby = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.hgetall = AsyncMock(return_value={})
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

    async def factory():
        return session

    # Make it work as async context manager
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
def usage_tracker(tracker_config, mock_redis, mock_session_factory):
    """Create a UsageTracker with mocked dependencies."""
    tracker = UsageTracker(tracker_config, mock_session_factory)
    tracker._redis = mock_redis
    tracker._connected = True
    return tracker


class TestUsageTrackerConfig:
    """Tests for UsageTrackerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = UsageTrackerConfig()

        assert config.redis_url == "redis://localhost:6379"
        assert config.key_prefix == "usage"
        assert config.key_ttl_seconds == 86400 * 2

    def test_custom_config(self):
        """Test custom configuration values."""
        config = UsageTrackerConfig(
            redis_url="redis://custom:6379/1",
            redis_password="secret",
            key_prefix="custom_usage",
            key_ttl_seconds=7200,
        )

        assert config.redis_url == "redis://custom:6379/1"
        assert config.redis_password == "secret"
        assert config.key_prefix == "custom_usage"
        assert config.key_ttl_seconds == 7200


class TestUsageTrackerKeyBuilding:
    """Tests for key building methods."""

    def test_build_key(self, usage_tracker):
        """Test Redis key format."""
        key = usage_tracker._build_key("tenant-123", date(2026, 1, 19), "gpt-4")

        assert key == "test_usage:tenant-123:2026-01-19:gpt-4"

    def test_build_key_with_special_chars(self, usage_tracker):
        """Test key building with special characters in model name."""
        key = usage_tracker._build_key("tenant-abc", date(2026, 1, 1), "claude-3:sonnet")

        assert key == "test_usage:tenant-abc:2026-01-01:claude-3:sonnet"


class TestRecordLLMUsage:
    """Tests for recording LLM token usage."""

    @pytest.mark.asyncio
    async def test_record_llm_usage_success(self, usage_tracker, mock_redis):
        """Test successful usage recording."""
        await usage_tracker.record_llm_usage(
            tenant_id="tenant-123",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        # Verify Redis calls
        assert mock_redis.hincrby.call_count == 2
        mock_redis.expire.assert_called()

    @pytest.mark.asyncio
    async def test_record_llm_usage_not_connected(self, usage_tracker, mock_redis):
        """Test usage recording when not connected."""
        usage_tracker._connected = False

        # Should not raise, just log warning
        await usage_tracker.record_llm_usage(
            tenant_id="tenant-123",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        mock_redis.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_llm_usage_redis_error(self, usage_tracker, mock_redis):
        """Test graceful handling of Redis errors."""
        mock_redis.hincrby.side_effect = Exception("Redis error")

        # Should not raise
        await usage_tracker.record_llm_usage(
            tenant_id="tenant-123",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )


class TestRecordEmbeddingUsage:
    """Tests for recording embedding token usage."""

    @pytest.mark.asyncio
    async def test_record_embedding_usage_success(self, usage_tracker, mock_redis):
        """Test successful embedding usage recording."""
        await usage_tracker.record_embedding_usage(
            tenant_id="tenant-123",
            model="bge-large",
            tokens=500,
        )

        mock_redis.hincrby.assert_called()
        mock_redis.expire.assert_called()


class TestCheckQuota:
    """Tests for quota checking."""

    @pytest.mark.asyncio
    async def test_check_quota_no_config(self, usage_tracker, mock_session_factory):
        """Test quota check when no config exists."""
        # Mock no quota config found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=session)

        allowed, remaining = await usage_tracker.check_quota("tenant-123")

        assert allowed is True
        assert remaining == -1

    @pytest.mark.asyncio
    async def test_check_quota_disabled(self, usage_tracker, mock_session_factory):
        """Test quota check when quota is disabled."""
        # Mock quota config with disabled quota
        mock_quota = MagicMock()
        mock_quota.quota_enabled = False
        mock_quota.monthly_token_limit = 1000000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_quota

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=session)

        allowed, remaining = await usage_tracker.check_quota("tenant-123")

        assert allowed is True
        assert remaining == -1

    @pytest.mark.asyncio
    async def test_check_quota_unlimited(self, usage_tracker, mock_session_factory):
        """Test quota check when limit is None (unlimited)."""
        mock_quota = MagicMock()
        mock_quota.quota_enabled = True
        mock_quota.monthly_token_limit = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_quota

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=session)

        allowed, remaining = await usage_tracker.check_quota("tenant-123")

        assert allowed is True
        assert remaining == -1


class TestEnforceQuota:
    """Tests for quota enforcement."""

    @pytest.mark.asyncio
    async def test_enforce_quota_allowed(self, usage_tracker):
        """Test enforce_quota when within limits."""
        # Mock check_quota to return allowed
        usage_tracker.check_quota = AsyncMock(return_value=(True, 50000))

        # Should not raise
        await usage_tracker.enforce_quota("tenant-123")

    @pytest.mark.asyncio
    async def test_enforce_quota_exceeded(self, usage_tracker, mock_session_factory):
        """Test enforce_quota raises when exceeded."""
        # Mock check_quota to return denied
        usage_tracker.check_quota = AsyncMock(return_value=(False, 0))

        # Mock getting the limit and current usage
        usage_tracker.get_current_month_usage = AsyncMock(return_value=1100000)

        mock_result = MagicMock()
        mock_result.scalar.return_value = 1000000

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=session)

        with pytest.raises(QuotaExceededError) as exc_info:
            await usage_tracker.enforce_quota("tenant-123")

        assert exc_info.value.tenant_id == "tenant-123"
        assert exc_info.value.limit == 1000000
        assert exc_info.value.used == 1100000


class TestHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, usage_tracker, mock_redis):
        """Test health check when connected."""
        result = await usage_tracker.health_check()

        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self, usage_tracker):
        """Test health check when not connected."""
        usage_tracker._connected = False

        result = await usage_tracker.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_ping_fails(self, usage_tracker, mock_redis):
        """Test health check when ping fails."""
        mock_redis.ping.side_effect = Exception("Connection lost")

        result = await usage_tracker.health_check()

        assert result is False


class TestContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, tracker_config, mock_session_factory):
        """Test async context manager usage."""
        with patch("usage.tracker.redis") as mock_redis_module:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.close = AsyncMock()
            mock_redis_module.from_url.return_value = mock_client

            async with UsageTracker(tracker_config, mock_session_factory) as tracker:
                assert tracker._connected is True

            mock_client.close.assert_called_once()
