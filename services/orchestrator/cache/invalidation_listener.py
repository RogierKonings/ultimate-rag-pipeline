"""Cache invalidation listener for the Orchestrator Service.

Subscribes to Redis pub/sub channel for cache invalidation events published
by the ingestion service when documents are deleted, reindexed, or otherwise
mutated. On receiving an event, it invalidates the relevant entries in the
answer cache.

Features:
- Document-scoped invalidation (single document changed)
- Batch invalidation (multiple documents deleted)
- Tenant-scoped invalidation (all documents for a tenant)
- Metrics: invalidation_events_received, invalidation_errors
- Automatic reconnection on Redis disconnection
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import structlog

try:
    import redis.asyncio as redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    redis = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)

# Must match the channel name in the Rust publisher
INVALIDATION_CHANNEL = "rag:cache_invalidation"


@dataclass
class InvalidationListenerConfig:
    """Configuration for the cache invalidation listener."""

    redis_url: str = "redis://localhost:6379"
    redis_password: str | None = None
    channel: str = INVALIDATION_CHANNEL
    reconnect_delay_seconds: float = 5.0
    max_reconnect_attempts: int = 0  # 0 = unlimited


@dataclass
class InvalidationListenerStats:
    """Statistics for cache invalidation listener."""

    events_received: int = 0
    events_processed: int = 0
    document_invalidations: int = 0
    tenant_invalidations: int = 0
    errors: int = 0
    last_event_at: float | None = None
    reconnect_count: int = 0


class CacheInvalidationListener:
    """Listens for cache invalidation events from the ingestion service.

    Subscribes to a Redis pub/sub channel and processes invalidation events
    by calling the appropriate methods on the AnswerCache instance.

    Usage:
        listener = CacheInvalidationListener(config, answer_cache)
        await listener.start()  # Starts background task
        ...
        await listener.stop()   # Graceful shutdown
    """

    def __init__(
        self,
        config: InvalidationListenerConfig,
        answer_cache: Any,
    ):
        """Initialize the cache invalidation listener.

        Args:
            config: Listener configuration.
            answer_cache: AnswerCache instance with invalidate_for_document
                and invalidate_for_tenant methods.
        """
        self.config = config
        self._answer_cache = answer_cache
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._stats = InvalidationListenerStats()

    @property
    def stats(self) -> InvalidationListenerStats:
        """Get listener statistics."""
        return self._stats

    @property
    def is_running(self) -> bool:
        """Check if the listener is running."""
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Start the listener background task.

        Returns:
            True if the listener started successfully.
        """
        if not HAS_REDIS:
            logger.warning("Redis library not available, cache invalidation listener disabled")
            return False

        if self._running:
            logger.warning("Cache invalidation listener already running")
            return True

        self._running = True
        self._task = asyncio.create_task(
            self._listen_loop(),
            name="cache-invalidation-listener",
        )
        logger.info(
            "cache_invalidation_listener_started",
            channel=self.config.channel,
        )
        return True

    async def stop(self) -> None:
        """Stop the listener and clean up resources."""
        self._running = False

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(self.config.channel)
                await self._pubsub.close()
            except Exception as e:
                logger.warning(f"Error closing pubsub: {e}")
            self._pubsub = None

        if self._redis:
            try:
                await self._redis.close()
            except Exception as e:
                logger.warning(f"Error closing Redis connection: {e}")
            self._redis = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("cache_invalidation_listener_stopped")

    async def _connect(self) -> bool:
        """Connect to Redis and subscribe to the invalidation channel.

        Returns:
            True if connected and subscribed successfully.
        """
        try:
            self._redis = redis.from_url(
                self.config.redis_url,
                password=self.config.redis_password,
                decode_responses=True,
            )
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self.config.channel)
            logger.info(
                "cache_invalidation_listener_connected",
                channel=self.config.channel,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to connect cache invalidation listener: {e}")
            self._stats.errors += 1
            return False

    async def _listen_loop(self) -> None:
        """Main listener loop with automatic reconnection."""
        reconnect_attempts = 0

        while self._running:
            # Connect / reconnect
            connected = await self._connect()
            if not connected:
                reconnect_attempts += 1
                if (
                    self.config.max_reconnect_attempts > 0
                    and reconnect_attempts > self.config.max_reconnect_attempts
                ):
                    logger.error(
                        "cache_invalidation_listener_max_reconnects",
                        max_attempts=self.config.max_reconnect_attempts,
                    )
                    self._running = False
                    return

                self._stats.reconnect_count += 1
                await asyncio.sleep(self.config.reconnect_delay_seconds)
                continue

            # Reset reconnect counter on successful connection
            reconnect_attempts = 0

            # Process messages
            try:
                while self._running and self._pubsub:
                    message = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if message is not None:
                        await self._handle_message(message)
                    else:
                        # No message received, yield control briefly
                        await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Cache invalidation listener error: {e}")
                self._stats.errors += 1

                # Clean up before reconnecting
                if self._pubsub:
                    try:
                        await self._pubsub.close()
                    except Exception:
                        logger.debug("Failed to close pubsub during cleanup", exc_info=True)
                    self._pubsub = None

                if self._redis:
                    try:
                        await self._redis.close()
                    except Exception:
                        logger.debug("Failed to close redis during cleanup", exc_info=True)
                    self._redis = None

                if self._running:
                    self._stats.reconnect_count += 1
                    await asyncio.sleep(self.config.reconnect_delay_seconds)

    async def _handle_message(self, message: dict) -> None:
        """Handle a single pub/sub message.

        Args:
            message: Redis pub/sub message dict.
        """
        if message.get("type") != "message":
            return

        self._stats.events_received += 1
        self._stats.last_event_at = time.time()

        try:
            data = message.get("data")
            if not data:
                return

            event = json.loads(data)
            event_type = event.get("event_type")
            tenant_id = event.get("tenant_id")
            document_ids = event.get("document_ids", [])

            if not tenant_id:
                logger.warning("cache_invalidation_missing_tenant_id", event=event)
                self._stats.errors += 1
                return

            logger.info(
                "cache_invalidation_event_received",
                event_type=event_type,
                tenant_id=tenant_id,
                document_count=len(document_ids),
            )

            if event_type == "tenant_invalidation":
                # Tenant-wide invalidation
                invalidated = await self._answer_cache.invalidate_for_tenant(tenant_id)
                self._stats.tenant_invalidations += 1
                logger.info(
                    "cache_invalidation_tenant_complete",
                    tenant_id=tenant_id,
                    entries_invalidated=invalidated,
                )
            elif event_type in ("document_deleted", "document_reindexed", "batch_deleted"):
                # Document-scoped invalidation
                total_invalidated = 0
                for doc_id in document_ids:
                    invalidated = await self._answer_cache.invalidate_for_document(
                        tenant_id, doc_id
                    )
                    total_invalidated += invalidated

                self._stats.document_invalidations += len(document_ids)
                logger.info(
                    "cache_invalidation_documents_complete",
                    tenant_id=tenant_id,
                    event_type=event_type,
                    documents_processed=len(document_ids),
                    entries_invalidated=total_invalidated,
                )
            else:
                logger.warning(
                    "cache_invalidation_unknown_event_type",
                    event_type=event_type,
                )
                self._stats.errors += 1
                return

            self._stats.events_processed += 1

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse invalidation event: {e}")
            self._stats.errors += 1
        except Exception as e:
            logger.warning(f"Error processing invalidation event: {e}")
            self._stats.errors += 1

    def get_metrics(self) -> dict[str, Any]:
        """Get listener metrics for Prometheus export.

        Returns:
            Dict with listener metrics.
        """
        return {
            "cache_invalidation_events_received": self._stats.events_received,
            "cache_invalidation_events_processed": self._stats.events_processed,
            "cache_invalidation_document_invalidations": self._stats.document_invalidations,
            "cache_invalidation_tenant_invalidations": self._stats.tenant_invalidations,
            "cache_invalidation_errors": self._stats.errors,
            "cache_invalidation_reconnect_count": self._stats.reconnect_count,
            "cache_invalidation_listener_running": 1 if self.is_running else 0,
            "cache_invalidation_last_event_at": self._stats.last_event_at or 0,
        }
