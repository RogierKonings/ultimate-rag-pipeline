"""Token usage tracker with Redis buffering.

This module provides the UsageTracker class that handles recording token usage
to Redis counters and checking tenant quotas.

Reference: US-10.5.4 - Token Usage Accounting
"""

from datetime import UTC, date, datetime

import redis.asyncio as redis
import structlog
from database.models.usage import TenantQuota, TokenUsage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from usage.metrics import llm_tokens_total, quota_checks_total
from usage.quota import QuotaExceededError

logger = structlog.get_logger(__name__)


class UsageTrackerConfig:
    """Configuration for UsageTracker."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_password: str | None = None,
        key_prefix: str = "usage",
        key_ttl_seconds: int = 86400 * 2,  # 2 days
    ):
        self.redis_url = redis_url
        self.redis_password = redis_password
        self.key_prefix = key_prefix
        self.key_ttl_seconds = key_ttl_seconds


class UsageTracker:
    """
    Tracks token usage per tenant with Redis buffering.

    Usage data is stored in Redis hashes for fast increments and periodically
    flushed to PostgreSQL for durable storage.

    Redis key format: {prefix}:{tenant_id}:{date}:{model}
    Hash fields: prompt, completion, embedding
    """

    def __init__(
        self,
        config: UsageTrackerConfig,
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
                decode_responses=False,  # We need bytes for hincrby
            )
            await self._redis.ping()
            self._connected = True
            logger.info("UsageTracker connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
            logger.info("UsageTracker disconnected from Redis")

    async def health_check(self) -> bool:
        """Check if Redis connection is healthy."""
        if not self._connected or not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    def _build_key(self, tenant_id: str, usage_date: date, model: str) -> str:
        """Build Redis key for usage counter."""
        return f"{self.config.key_prefix}:{tenant_id}:{usage_date.isoformat()}:{model}"

    async def record_llm_usage(
        self,
        tenant_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """
        Record LLM token usage to Redis counters and Prometheus.

        Args:
            tenant_id: The tenant identifier.
            model: The model identifier (e.g., "gpt-4", "claude-3").
            prompt_tokens: Number of prompt tokens consumed.
            completion_tokens: Number of completion tokens generated.
        """
        if not self._connected or not self._redis:
            logger.warning("UsageTracker not connected, skipping usage recording")
            return

        try:
            key = self._build_key(tenant_id, datetime.now(UTC).date(), model)

            # Increment Redis counters
            await self._redis.hincrby(key, "prompt", prompt_tokens)
            await self._redis.hincrby(key, "completion", completion_tokens)
            await self._redis.expire(key, self.config.key_ttl_seconds)

            # Update Prometheus counters
            llm_tokens_total.labels(
                tenant_id=tenant_id,
                model=model,
                type="prompt",
            ).inc(prompt_tokens)
            llm_tokens_total.labels(
                tenant_id=tenant_id,
                model=model,
                type="completion",
            ).inc(completion_tokens)

            logger.debug(
                f"Recorded usage for tenant={tenant_id} model={model}: "
                f"prompt={prompt_tokens} completion={completion_tokens}"
            )
        except Exception as e:
            logger.error(f"Failed to record usage: {e}")
            # Don't raise - usage tracking should not break the main flow

    async def record_embedding_usage(
        self,
        tenant_id: str,
        model: str,
        tokens: int,
    ) -> None:
        """
        Record embedding token usage.

        Args:
            tenant_id: The tenant identifier.
            model: The embedding model identifier.
            tokens: Number of tokens processed for embedding.
        """
        if not self._connected or not self._redis:
            logger.warning("UsageTracker not connected, skipping usage recording")
            return

        try:
            key = self._build_key(tenant_id, datetime.now(UTC).date(), model)

            await self._redis.hincrby(key, "embedding", tokens)
            await self._redis.expire(key, self.config.key_ttl_seconds)

            logger.debug(
                f"Recorded embedding usage for tenant={tenant_id} model={model}: tokens={tokens}"
            )
        except Exception as e:
            logger.error(f"Failed to record embedding usage: {e}")

    async def get_current_month_usage(self, tenant_id: str) -> int:
        """
        Get total tokens used this month.

        Combines unflushed Redis data with persisted PostgreSQL data.

        Args:
            tenant_id: The tenant identifier.

        Returns:
            Total tokens used this month.
        """
        today = datetime.now(UTC).date()
        first_of_month = today.replace(day=1)

        # Get PostgreSQL totals
        db_total = 0
        async with self.session_factory() as session:
            # nosemgrep: sqlalchemy-raw-sql-injection
            result = await session.execute(
                select(
                    func.coalesce(func.sum(TokenUsage.prompt_tokens), 0)
                    + func.coalesce(func.sum(TokenUsage.completion_tokens), 0)
                    + func.coalesce(func.sum(TokenUsage.embedding_tokens), 0)
                ).where(
                    TokenUsage.tenant_id == tenant_id,
                    TokenUsage.date >= first_of_month,
                )
            )
            db_total = result.scalar() or 0

        # Get Redis totals (unflushed data)
        redis_total = 0
        if self._connected and self._redis:
            try:
                pattern = f"{self.config.key_prefix}:{tenant_id}:*"
                async for key in self._redis.scan_iter(match=pattern):
                    # Parse date from key to check if it's current month
                    try:
                        key_str = key.decode() if isinstance(key, bytes) else key
                        parts = key_str.split(":")
                        if len(parts) >= 3:
                            key_date = date.fromisoformat(parts[2])
                            if key_date >= first_of_month:
                                data = await self._redis.hgetall(key)
                                redis_total += int(data.get(b"prompt", 0))
                                redis_total += int(data.get(b"completion", 0))
                                redis_total += int(data.get(b"embedding", 0))
                    except (ValueError, IndexError):
                        continue
            except Exception as e:
                logger.error(f"Failed to get Redis usage: {e}")

        return db_total + redis_total

    async def check_quota(self, tenant_id: str) -> tuple[bool, int]:
        """
        Check if tenant is within their token quota.

        Args:
            tenant_id: The tenant identifier.

        Returns:
            Tuple of (allowed, remaining).
            - allowed: True if request should proceed, False if quota exceeded.
            - remaining: Tokens remaining (-1 if unlimited).
        """
        # Get quota configuration
        async with self.session_factory() as session:
            result = await session.execute(
                select(TenantQuota).where(TenantQuota.tenant_id == tenant_id)
            )
            quota_config = result.scalar_one_or_none()

        # No config or quota disabled = unlimited
        if quota_config is None or not quota_config.quota_enabled:
            quota_checks_total.labels(tenant_id=tenant_id, result="allowed").inc()
            return True, -1

        # Unlimited if no limit set
        if quota_config.monthly_token_limit is None:
            quota_checks_total.labels(tenant_id=tenant_id, result="allowed").inc()
            return True, -1

        # Check current usage against limit
        current_usage = await self.get_current_month_usage(tenant_id)
        remaining = quota_config.monthly_token_limit - current_usage
        allowed = remaining > 0

        # Record metric
        result_label = "allowed" if allowed else "denied"
        quota_checks_total.labels(tenant_id=tenant_id, result=result_label).inc()

        if not allowed:
            logger.warning(
                f"Quota exceeded for tenant {tenant_id}: "
                f"{current_usage:,}/{quota_config.monthly_token_limit:,} tokens"
            )

        return allowed, remaining

    async def enforce_quota(self, tenant_id: str) -> None:
        """
        Check quota and raise QuotaExceededError if exceeded.

        Args:
            tenant_id: The tenant identifier.

        Raises:
            QuotaExceededError: If tenant has exceeded their quota.
        """
        allowed, remaining = await self.check_quota(tenant_id)
        if not allowed:
            # Get the limit for the error message
            async with self.session_factory() as session:
                result = await session.execute(
                    select(TenantQuota.monthly_token_limit).where(
                        TenantQuota.tenant_id == tenant_id
                    )
                )
                limit = result.scalar() or 0

            current_usage = await self.get_current_month_usage(tenant_id)
            raise QuotaExceededError(
                tenant_id=tenant_id,
                limit=limit,
                used=current_usage,
            )

    async def __aenter__(self) -> "UsageTracker":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
