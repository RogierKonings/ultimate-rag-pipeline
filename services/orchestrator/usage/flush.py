"""Usage data flusher for persisting Redis counters to PostgreSQL.

This module provides the UsageFlusher class that periodically flushes
accumulated usage data from Redis to PostgreSQL for durable storage.

Reference: US-10.5.4 - Token Usage Accounting
"""

from datetime import date
from uuid import uuid4

import redis.asyncio as redis
import structlog
from database.models.usage import TokenUsage
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)


class UsageFlusherConfig:
    """Configuration for UsageFlusher."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_password: str | None = None,
        key_prefix: str = "usage",
        flush_interval_seconds: int = 300,  # 5 minutes
    ):
        self.redis_url = redis_url
        self.redis_password = redis_password
        self.key_prefix = key_prefix
        self.flush_interval_seconds = flush_interval_seconds


class UsageFlusher:
    """
    Flushes Redis usage counters to PostgreSQL.

    This class scans for usage keys in Redis and persists them to the
    token_usage table using upsert operations.
    """

    def __init__(
        self,
        config: UsageFlusherConfig,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.config = config
        self.session_factory = session_factory
        self._redis: redis.Redis | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._connected:
            return

        try:
            self._redis = redis.from_url(
                self.config.redis_url,
                password=self.config.redis_password,
                decode_responses=False,
            )
            await self._redis.ping()
            self._connected = True
            logger.info("UsageFlusher connected to Redis")
        except Exception as e:
            logger.error(f"UsageFlusher failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
            logger.info("UsageFlusher disconnected from Redis")

    async def flush(self) -> int:
        """
        Flush all pending usage counters to PostgreSQL.

        Returns:
            Number of keys flushed.
        """
        if not self._connected or not self._redis:
            logger.warning("UsageFlusher not connected, skipping flush")
            return 0

        flushed = 0
        errors = 0
        pattern = f"{self.config.key_prefix}:*"

        try:
            async with self.session_factory() as session:
                keys_to_delete = []

                async for key in self._redis.scan_iter(match=pattern):
                    try:
                        data = await self._redis.hgetall(key)
                        if not data:
                            continue

                        # Parse key: {prefix}:{tenant_id}:{date}:{model}
                        key_str = key.decode() if isinstance(key, bytes) else key
                        parts = key_str.split(":")
                        if len(parts) < 4:
                            logger.warning(f"Invalid usage key format: {key_str}")
                            continue

                        tenant_id = parts[1]
                        date_str = parts[2]
                        model = ":".join(parts[3:])  # Model name might contain colons

                        try:
                            usage_date = date.fromisoformat(date_str)
                        except ValueError:
                            logger.warning(f"Invalid date in usage key: {date_str}")
                            continue

                        prompt_tokens = int(data.get(b"prompt", 0))
                        completion_tokens = int(data.get(b"completion", 0))
                        embedding_tokens = int(data.get(b"embedding", 0))

                        # Skip if all zeros
                        if prompt_tokens == 0 and completion_tokens == 0 and embedding_tokens == 0:
                            keys_to_delete.append(key)
                            continue

                        # Upsert to PostgreSQL
                        stmt = (
                            pg_insert(TokenUsage)
                            .values(
                                id=str(uuid4()),
                                tenant_id=tenant_id,
                                date=usage_date,
                                model=model,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                embedding_tokens=embedding_tokens,
                            )
                            .on_conflict_do_update(
                                constraint="uq_usage_tenant_date_model",
                                set_={
                                    "prompt_tokens": TokenUsage.prompt_tokens + prompt_tokens,
                                    "completion_tokens": TokenUsage.completion_tokens
                                    + completion_tokens,
                                    "embedding_tokens": TokenUsage.embedding_tokens
                                    + embedding_tokens,
                                },
                            )
                        )
                        await session.execute(stmt)
                        keys_to_delete.append(key)
                        flushed += 1

                    except Exception as e:
                        logger.error(f"Error processing key {key}: {e}")
                        errors += 1

                # Commit all upserts
                await session.commit()

                # Delete flushed keys from Redis
                for key in keys_to_delete:
                    try:
                        await self._redis.delete(key)
                    except Exception as e:
                        logger.error(f"Failed to delete key {key}: {e}")

            if flushed > 0 or errors > 0:
                logger.info(f"Usage flush completed: {flushed} flushed, {errors} errors")

        except Exception as e:
            logger.error(f"Usage flush failed: {e}")
            raise

        return flushed

    async def __aenter__(self) -> "UsageFlusher":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
