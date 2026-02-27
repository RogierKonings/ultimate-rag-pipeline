"""Tests for CacheInvalidationListener reconnection, error handling, and message processing.

Covers TEST-002: Cache invalidation listener reconnection/message-loss tests.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cache.invalidation_listener import (
    CacheInvalidationListener,
    InvalidationListenerConfig,
)


@pytest.fixture
def listener_config():
    """Create a test listener config with fast reconnect for tests."""
    return InvalidationListenerConfig(
        redis_url="redis://localhost:6379/1",
        channel="test:cache_invalidation",
        reconnect_delay_seconds=0.01,  # fast for tests
        max_reconnect_attempts=3,
    )


@pytest.fixture
def mock_answer_cache():
    """Create a mock AnswerCache with invalidation methods."""
    cache = AsyncMock()
    cache.invalidate_for_document = AsyncMock(return_value=1)
    cache.invalidate_for_tenant = AsyncMock(return_value=5)
    return cache


@pytest.fixture
def listener(listener_config, mock_answer_cache):
    """Create a CacheInvalidationListener with mocked dependencies."""
    return CacheInvalidationListener(listener_config, mock_answer_cache)


# =============================================================================
# Message Handling Tests
# =============================================================================


class TestHandleMessage:
    """Tests for _handle_message processing."""

    @pytest.mark.asyncio
    async def test_ignores_non_message_type(self, listener):
        """Non-message types (subscribe confirmations) are ignored."""
        await listener._handle_message({"type": "subscribe", "data": 1})
        assert listener.stats.events_received == 0

    @pytest.mark.asyncio
    async def test_ignores_empty_data(self, listener):
        """Messages with empty/None data are skipped."""
        await listener._handle_message({"type": "message", "data": None})
        assert listener.stats.events_received == 1
        assert listener.stats.events_processed == 0

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self, listener):
        """Malformed JSON increments error counter but does not crash."""
        await listener._handle_message({"type": "message", "data": "not-json{{"})
        assert listener.stats.events_received == 1
        assert listener.stats.errors == 1
        assert listener.stats.events_processed == 0

    @pytest.mark.asyncio
    async def test_handles_missing_tenant_id(self, listener):
        """Event without tenant_id is rejected with an error."""
        event = json.dumps({"event_type": "document_deleted", "document_ids": ["d1"]})
        await listener._handle_message({"type": "message", "data": event})
        assert listener.stats.errors == 1
        assert listener.stats.events_processed == 0

    @pytest.mark.asyncio
    async def test_handles_unknown_event_type(self, listener):
        """Unknown event_type is logged as error, not processed."""
        event = json.dumps({
            "event_type": "unknown_event",
            "tenant_id": "t1",
        })
        await listener._handle_message({"type": "message", "data": event})
        assert listener.stats.errors == 1
        assert listener.stats.events_processed == 0

    @pytest.mark.asyncio
    async def test_processes_tenant_invalidation(self, listener, mock_answer_cache):
        """tenant_invalidation event calls invalidate_for_tenant."""
        event = json.dumps({
            "event_type": "tenant_invalidation",
            "tenant_id": "tenant-1",
        })
        await listener._handle_message({"type": "message", "data": event})

        mock_answer_cache.invalidate_for_tenant.assert_awaited_once_with("tenant-1")
        assert listener.stats.tenant_invalidations == 1
        assert listener.stats.events_processed == 1

    @pytest.mark.asyncio
    async def test_processes_document_deleted(self, listener, mock_answer_cache):
        """document_deleted event calls invalidate_for_document per doc."""
        event = json.dumps({
            "event_type": "document_deleted",
            "tenant_id": "tenant-1",
            "document_ids": ["doc-1", "doc-2"],
        })
        await listener._handle_message({"type": "message", "data": event})

        assert mock_answer_cache.invalidate_for_document.await_count == 2
        assert listener.stats.document_invalidations == 2
        assert listener.stats.events_processed == 1

    @pytest.mark.asyncio
    async def test_processes_document_reindexed(self, listener, mock_answer_cache):
        """document_reindexed event calls invalidate_for_document."""
        event = json.dumps({
            "event_type": "document_reindexed",
            "tenant_id": "tenant-1",
            "document_ids": ["doc-1"],
        })
        await listener._handle_message({"type": "message", "data": event})

        mock_answer_cache.invalidate_for_document.assert_awaited_once_with("tenant-1", "doc-1")
        assert listener.stats.events_processed == 1

    @pytest.mark.asyncio
    async def test_processes_batch_deleted(self, listener, mock_answer_cache):
        """batch_deleted event calls invalidate_for_document for each doc."""
        event = json.dumps({
            "event_type": "batch_deleted",
            "tenant_id": "tenant-1",
            "document_ids": ["d1", "d2", "d3"],
        })
        await listener._handle_message({"type": "message", "data": event})

        assert mock_answer_cache.invalidate_for_document.await_count == 3
        assert listener.stats.document_invalidations == 3

    @pytest.mark.asyncio
    async def test_cache_error_during_invalidation(self, listener, mock_answer_cache):
        """Exception from answer_cache is caught and counted as error."""
        mock_answer_cache.invalidate_for_tenant.side_effect = Exception("Redis down")

        event = json.dumps({
            "event_type": "tenant_invalidation",
            "tenant_id": "tenant-1",
        })
        await listener._handle_message({"type": "message", "data": event})

        assert listener.stats.errors == 1
        assert listener.stats.events_processed == 0

    @pytest.mark.asyncio
    async def test_empty_document_ids_list(self, listener, mock_answer_cache):
        """document_deleted with empty document_ids still counts as processed."""
        event = json.dumps({
            "event_type": "document_deleted",
            "tenant_id": "tenant-1",
            "document_ids": [],
        })
        await listener._handle_message({"type": "message", "data": event})

        mock_answer_cache.invalidate_for_document.assert_not_awaited()
        assert listener.stats.document_invalidations == 0
        assert listener.stats.events_processed == 1


# =============================================================================
# Connection and Reconnection Tests
# =============================================================================


class TestConnectionAndReconnection:
    """Tests for connection lifecycle and reconnection behavior."""

    @pytest.mark.asyncio
    async def test_connect_success(self, listener):
        """Successful connection sets up pubsub."""
        with patch("cache.invalidation_listener.redis") as mock_redis_mod:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_pubsub = AsyncMock()
            # pubsub() is a sync call on the real redis client, so use MagicMock
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock_redis_mod.from_url.return_value = mock_client

            result = await listener._connect()

            assert result is True
            mock_pubsub.subscribe.assert_awaited_once_with(listener.config.channel)

    @pytest.mark.asyncio
    async def test_connect_failure_increments_errors(self, listener):
        """Failed connection increments error counter."""
        with patch("cache.invalidation_listener.redis") as mock_redis_mod:
            mock_redis_mod.from_url.side_effect = Exception("Connection refused")

            result = await listener._connect()

            assert result is False
            assert listener.stats.errors == 1

    @pytest.mark.asyncio
    async def test_listen_loop_reconnects_on_failure(self, listener_config, mock_answer_cache):
        """Listen loop retries connection on failure, up to max_reconnect_attempts."""
        config = InvalidationListenerConfig(
            redis_url="redis://localhost:6379/1",
            channel="test:ch",
            reconnect_delay_seconds=0.001,
            max_reconnect_attempts=2,
        )
        listener = CacheInvalidationListener(config, mock_answer_cache)
        listener._running = True

        with patch.object(listener, "_connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = False

            await listener._listen_loop()

            # Should have tried initial + 2 reconnects = 3 total calls
            assert mock_connect.await_count == 3
            assert not listener._running  # Should stop after max attempts

    @pytest.mark.asyncio
    async def test_listen_loop_resets_counter_on_success(self, listener):
        """Successful connection resets the reconnect attempt counter."""
        call_count = 0

        async def mock_connect():
            nonlocal call_count
            call_count += 1
            return call_count != 1

        listener._running = True

        async def stop_after_connect():
            """Mock pubsub that stops the listener after one iteration."""
            await asyncio.sleep(0.01)
            listener._running = False

        with patch.object(listener, "_connect", side_effect=mock_connect):
            listener._pubsub = AsyncMock()
            listener._pubsub.get_message = AsyncMock(return_value=None)

            # Make it stop after connecting
            task = asyncio.create_task(listener._listen_loop())
            await asyncio.sleep(0.05)
            listener._running = False
            await asyncio.sleep(0.05)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Should have reconnected at least once
            assert listener.stats.reconnect_count >= 1

    @pytest.mark.asyncio
    async def test_listen_loop_reconnects_after_message_error(self, listener):
        """Exception during message processing triggers reconnection."""
        connect_count = 0

        async def mock_connect():
            nonlocal connect_count
            connect_count += 1
            if connect_count >= 2:
                listener._running = False
                return False
            return True

        listener._running = True
        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(side_effect=ConnectionError("Lost connection"))
        mock_pubsub.close = AsyncMock()

        with patch.object(listener, "_connect", side_effect=mock_connect):
            listener._pubsub = mock_pubsub
            await listener._listen_loop()

        assert listener.stats.errors >= 1
        assert listener.stats.reconnect_count >= 1


# =============================================================================
# Start / Stop Lifecycle Tests
# =============================================================================


class TestLifecycle:
    """Tests for start() and stop() lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_without_redis_returns_false(self, listener):
        """Start returns False when redis library not available."""
        with patch("cache.invalidation_listener.HAS_REDIS", False):
            result = await listener.start()
            assert result is False

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, listener):
        """Start returns True without creating duplicate tasks."""
        listener._running = True
        result = await listener.start()
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, listener):
        """Stop cleans up pubsub, redis, and task."""
        mock_pubsub = AsyncMock()
        mock_redis = AsyncMock()
        mock_task = MagicMock()
        mock_task.done.return_value = True

        listener._pubsub = mock_pubsub
        listener._redis = mock_redis
        listener._task = mock_task
        listener._running = True

        await listener.stop()

        assert not listener._running
        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.close.assert_awaited_once()
        mock_redis.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_running_property(self, listener):
        """is_running reflects actual task state."""
        assert not listener.is_running

        listener._running = True
        assert not listener.is_running  # No task

        mock_task = MagicMock()
        mock_task.done.return_value = False
        listener._task = mock_task
        assert listener.is_running

        mock_task.done.return_value = True
        assert not listener.is_running


# =============================================================================
# Metrics Tests
# =============================================================================


class TestMetrics:
    """Tests for metrics export."""

    def test_get_metrics_default(self, listener):
        """Default metrics are all zeros."""
        metrics = listener.get_metrics()
        assert metrics["cache_invalidation_events_received"] == 0
        assert metrics["cache_invalidation_events_processed"] == 0
        assert metrics["cache_invalidation_errors"] == 0
        assert metrics["cache_invalidation_listener_running"] == 0

    @pytest.mark.asyncio
    async def test_get_metrics_after_events(self, listener, mock_answer_cache):
        """Metrics reflect processed events."""
        event = json.dumps({
            "event_type": "tenant_invalidation",
            "tenant_id": "t1",
        })
        await listener._handle_message({"type": "message", "data": event})

        metrics = listener.get_metrics()
        assert metrics["cache_invalidation_events_received"] == 1
        assert metrics["cache_invalidation_events_processed"] == 1
        assert metrics["cache_invalidation_tenant_invalidations"] == 1
        assert metrics["cache_invalidation_last_event_at"] > 0
