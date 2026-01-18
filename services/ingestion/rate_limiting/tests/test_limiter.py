"""Unit tests for IngestionRateLimiter."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rate_limiting.limiter import IngestionRateLimiter
from rate_limiting.models import TenantLimits


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.hset = AsyncMock()
    redis.scard = AsyncMock(return_value=0)
    redis.sadd = AsyncMock()
    redis.srem = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    redis.llen = AsyncMock(return_value=0)
    redis.rpush = AsyncMock()
    redis.lpop = AsyncMock()
    redis.lindex = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.expire = AsyncMock()

    # Mock pipeline
    pipeline = AsyncMock()
    pipeline.watch = AsyncMock()
    pipeline.unwatch = AsyncMock()
    pipeline.multi = MagicMock()
    pipeline.sadd = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.execute = AsyncMock()

    redis.pipeline = MagicMock(return_value=pipeline)
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock()

    return redis


@pytest.fixture
def rate_limiter(mock_redis):
    """Create a rate limiter with mock Redis."""
    return IngestionRateLimiter(mock_redis, default_max_concurrent=5)


class TestTenantLimits:
    """Tests for TenantLimits model."""

    def test_default_values(self):
        """Test default limit values."""
        limits = TenantLimits()
        assert limits.max_concurrent_jobs == 10
        assert limits.priority == "normal"
        assert limits.hard_limit is False

    def test_to_redis_hash(self):
        """Test conversion to Redis hash."""
        limits = TenantLimits(
            max_concurrent_jobs=20,
            priority="high",
            hard_limit=True,
        )
        hash_data = limits.to_redis_hash()

        assert hash_data["max_concurrent"] == "20"
        assert hash_data["priority"] == "high"
        assert hash_data["hard_limit"] == "true"

    def test_from_redis_hash(self):
        """Test creation from Redis hash data."""
        data = {
            b"max_concurrent": b"15",
            b"priority": b"low",
            b"hard_limit": b"true",
        }
        limits = TenantLimits.from_redis_hash(data)

        assert limits.max_concurrent_jobs == 15
        assert limits.priority == "low"
        assert limits.hard_limit is True

    def test_from_redis_hash_empty(self):
        """Test creation from empty Redis hash uses defaults."""
        limits = TenantLimits.from_redis_hash({}, default_max=7)

        assert limits.max_concurrent_jobs == 7
        assert limits.priority == "normal"
        assert limits.hard_limit is False


class TestIngestionRateLimiter:
    """Tests for IngestionRateLimiter."""

    @pytest.mark.asyncio
    async def test_get_tenant_limits_default(self, rate_limiter, mock_redis):
        """Test getting limits for tenant with no custom config."""
        mock_redis.hgetall.return_value = {}

        limits = await rate_limiter.get_tenant_limits("tenant-1")

        assert limits.max_concurrent_jobs == 5  # default_max from limiter
        assert limits.priority == "normal"
        mock_redis.hgetall.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tenant_limits_custom(self, rate_limiter, mock_redis):
        """Test getting custom limits for tenant."""
        mock_redis.hgetall.return_value = {
            b"max_concurrent": b"20",
            b"priority": b"high",
            b"hard_limit": b"false",
        }

        limits = await rate_limiter.get_tenant_limits("tenant-1")

        assert limits.max_concurrent_jobs == 20
        assert limits.priority == "high"
        assert limits.hard_limit is False

    @pytest.mark.asyncio
    async def test_set_tenant_limits(self, rate_limiter, mock_redis):
        """Test setting tenant limits."""
        limits = TenantLimits(
            max_concurrent_jobs=15,
            priority="low",
            hard_limit=True,
        )

        await rate_limiter.set_tenant_limits("tenant-1", limits)

        mock_redis.hset.assert_called_once()
        call_args = mock_redis.hset.call_args
        assert "ingestion:rate_limit:limits:tenant-1" in str(call_args)

    @pytest.mark.asyncio
    async def test_try_acquire_slot_success(self, rate_limiter, mock_redis):
        """Test successful slot acquisition."""
        mock_redis.scard.return_value = 2  # Under limit of 5

        acquired, reason = await rate_limiter.try_acquire_slot("tenant-1", "job-1")

        assert acquired is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_try_acquire_slot_at_limit(self, rate_limiter, mock_redis):
        """Test slot acquisition fails at limit."""
        mock_redis.scard.return_value = 5  # At limit

        acquired, reason = await rate_limiter.try_acquire_slot("tenant-1", "job-6")

        assert acquired is False
        assert reason == "max_concurrent_jobs_reached"

    @pytest.mark.asyncio
    async def test_release_slot(self, rate_limiter, mock_redis):
        """Test releasing a slot."""
        mock_redis.srem.return_value = 1
        mock_redis.lindex.return_value = None  # No queued jobs

        await rate_limiter.release_slot("tenant-1", "job-1")

        mock_redis.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_slot_not_found(self, rate_limiter, mock_redis):
        """Test releasing a slot that doesn't exist."""
        mock_redis.srem.return_value = 0  # Not found

        # Should not raise
        await rate_limiter.release_slot("tenant-1", "job-unknown")

    @pytest.mark.asyncio
    async def test_get_active_count(self, rate_limiter, mock_redis):
        """Test getting active job count."""
        mock_redis.scard.return_value = 3

        count = await rate_limiter.get_active_count("tenant-1")

        assert count == 3
        mock_redis.scard.assert_called_with("ingestion:rate_limit:active:tenant-1")

    @pytest.mark.asyncio
    async def test_get_queued_count(self, rate_limiter, mock_redis):
        """Test getting queued job count."""
        mock_redis.llen.return_value = 5

        count = await rate_limiter.get_queued_count("tenant-1")

        assert count == 5
        mock_redis.llen.assert_called_with("ingestion:rate_limit:queued:tenant-1")

    @pytest.mark.asyncio
    async def test_queue_job(self, rate_limiter, mock_redis):
        """Test queueing a job."""
        task_data = {"document_id": "doc-1", "tenant_id": "tenant-1"}

        await rate_limiter.queue_job("tenant-1", "job-1", task_data)

        mock_redis.rpush.assert_called_once()
        call_args = mock_redis.rpush.call_args
        assert "ingestion:rate_limit:queued:tenant-1" in str(call_args)

        # Verify the queued data structure
        queued_data = json.loads(call_args[0][1])
        assert queued_data["job_id"] == "job-1"
        assert queued_data["task_data"] == task_data
        assert "queued_at" in queued_data

    @pytest.mark.asyncio
    async def test_clear_queue(self, rate_limiter, mock_redis):
        """Test clearing tenant queue."""
        mock_redis.llen.return_value = 10

        count = await rate_limiter.clear_queue("tenant-1")

        assert count == 10
        mock_redis.delete.assert_called_with("ingestion:rate_limit:queued:tenant-1")

    @pytest.mark.asyncio
    async def test_get_active_jobs(self, rate_limiter, mock_redis):
        """Test getting active job IDs."""
        mock_redis.smembers.return_value = {b"job-1", b"job-2", b"job-3"}

        jobs = await rate_limiter.get_active_jobs("tenant-1")

        assert jobs == {"job-1", "job-2", "job-3"}

    @pytest.mark.asyncio
    async def test_delete_tenant_limits(self, rate_limiter, mock_redis):
        """Test deleting tenant limits."""
        await rate_limiter.delete_tenant_limits("tenant-1")

        mock_redis.delete.assert_called_with("ingestion:rate_limit:limits:tenant-1")


class TestProcessQueuedJobs:
    """Tests for queued job processing."""

    @pytest.mark.asyncio
    async def test_process_queued_jobs_dispatches(self, rate_limiter, mock_redis):
        """Test that queued jobs are dispatched when slots available."""
        # Setup: one queued job, slot available
        queued_job = json.dumps({
            "job_id": "job-queued",
            "task_data": {
                "document_source_id": "doc-1",
                "source_type": "filesystem",
                "source_config": {},
                "processing_config": {},
                "acl_context": {"tenant_id": "tenant-1"},
            },
            "queued_at": datetime.now(UTC).isoformat(),
        })

        # First call returns queued job, second call returns None (queue empty)
        mock_redis.lindex.side_effect = [queued_job, None]
        mock_redis.scard.return_value = 0  # Slot available
        mock_redis.lpop.return_value = queued_job

        with patch("rate_limiting.limiter.IngestionRateLimiter.try_acquire_slot") as mock_acquire:
            mock_acquire.return_value = (True, None)

            with patch("tasks.ingest.process_document") as mock_task:
                mock_task.apply_async = MagicMock()

                await rate_limiter._process_queued_jobs("tenant-1")

                # Should have tried to dispatch the queued job
                mock_redis.lpop.assert_called()

    @pytest.mark.asyncio
    async def test_process_queued_jobs_stops_when_full(self, rate_limiter, mock_redis):
        """Test that processing stops when no more slots available."""
        queued_job = json.dumps({
            "job_id": "job-queued",
            "task_data": {},
            "queued_at": datetime.now(UTC).isoformat(),
        })

        mock_redis.lindex.return_value = queued_job

        with patch.object(rate_limiter, "try_acquire_slot") as mock_acquire:
            mock_acquire.return_value = (False, "max_concurrent_jobs_reached")

            await rate_limiter._process_queued_jobs("tenant-1")

            # Should not have popped from queue since slot not acquired
            mock_redis.lpop.assert_not_called()
