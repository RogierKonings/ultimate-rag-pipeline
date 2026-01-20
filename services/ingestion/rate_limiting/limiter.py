"""Per-tenant rate limiting for ingestion jobs.

Uses Redis for distributed coordination across workers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from rate_limiting.models import QueuedJob, TenantLimits

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = structlog.get_logger(__name__)


class IngestionRateLimiter:
    """Per-tenant rate limiting for ingestion jobs.

    Uses Redis for distributed coordination across workers.
    Tracks active jobs per tenant and enforces configurable limits.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        default_max_concurrent: int = 10,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            redis_client: Async Redis client for distributed coordination.
            default_max_concurrent: Default max concurrent jobs per tenant.
        """
        self.redis = redis_client
        self.default_max = default_max_concurrent
        self._key_prefix = "ingestion:rate_limit"

    def _active_jobs_key(self, tenant_id: str) -> str:
        """Redis key for tracking active jobs."""
        return f"{self._key_prefix}:active:{tenant_id}"

    def _limits_key(self, tenant_id: str) -> str:
        """Redis key for tenant limit configuration."""
        return f"{self._key_prefix}:limits:{tenant_id}"

    def _queue_key(self, tenant_id: str) -> str:
        """Redis key for queued jobs."""
        return f"{self._key_prefix}:queued:{tenant_id}"

    async def get_tenant_limits(self, tenant_id: str) -> TenantLimits:
        """Get rate limit configuration for tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            TenantLimits configuration (defaults if not set).
        """
        data = await self.redis.hgetall(self._limits_key(tenant_id))
        return TenantLimits.from_redis_hash(data, self.default_max)

    async def set_tenant_limits(
        self,
        tenant_id: str,
        limits: TenantLimits,
    ) -> None:
        """Set rate limit configuration for tenant.

        Args:
            tenant_id: The tenant ID.
            limits: The new limit configuration.
        """
        await self.redis.hset(
            self._limits_key(tenant_id),
            mapping=limits.to_redis_hash(),
        )
        logger.info(
            "tenant_limits_updated",
            tenant_id=tenant_id,
            max_concurrent=limits.max_concurrent_jobs,
            priority=limits.priority,
            hard_limit=limits.hard_limit,
        )

    async def delete_tenant_limits(self, tenant_id: str) -> None:
        """Delete custom limits for tenant (reverts to defaults).

        Args:
            tenant_id: The tenant ID.
        """
        await self.redis.delete(self._limits_key(tenant_id))
        logger.info("tenant_limits_deleted", tenant_id=tenant_id)

    async def try_acquire_slot(
        self,
        tenant_id: str,
        job_id: str,
    ) -> tuple[bool, str | None]:
        """Try to acquire a job slot for tenant.

        Uses Redis transactions (WATCH/MULTI/EXEC) to prevent race conditions.

        Args:
            tenant_id: The tenant ID.
            job_id: The Celery task ID.

        Returns:
            Tuple of (acquired, reason). If acquired is True, the slot was
            reserved. If False, reason explains why (max_concurrent_jobs_reached).
        """
        limits = await self.get_tenant_limits(tenant_id)
        key = self._active_jobs_key(tenant_id)

        # Use a transaction to atomically check and increment
        async with self.redis.pipeline(transaction=True) as pipe:
            try:
                # Watch the key for changes
                await pipe.watch(key)
                current = await self.redis.scard(key)

                if current >= limits.max_concurrent_jobs:
                    await pipe.unwatch()
                    logger.info(
                        "rate_limit_reached",
                        tenant_id=tenant_id,
                        job_id=job_id,
                        current=current,
                        limit=limits.max_concurrent_jobs,
                    )
                    return False, "max_concurrent_jobs_reached"

                # Add job to active set atomically
                pipe.multi()
                pipe.sadd(key, job_id)
                pipe.expire(key, 86400)  # 24h TTL for safety
                await pipe.execute()

                logger.debug(
                    "slot_acquired",
                    tenant_id=tenant_id,
                    job_id=job_id,
                    active_count=current + 1,
                    limit=limits.max_concurrent_jobs,
                )
                return True, None

            except Exception:
                # WatchError or other error - retry
                await pipe.unwatch()
                return await self.try_acquire_slot(tenant_id, job_id)

    async def release_slot(
        self,
        tenant_id: str,
        job_id: str,
    ) -> None:
        """Release a job slot for tenant.

        After releasing, checks if any queued jobs can now start.

        Args:
            tenant_id: The tenant ID.
            job_id: The Celery task ID.
        """
        key = self._active_jobs_key(tenant_id)
        removed = await self.redis.srem(key, job_id)

        if removed:
            logger.debug(
                "slot_released",
                tenant_id=tenant_id,
                job_id=job_id,
            )
            # Check if any queued jobs can start
            await self._process_queued_jobs(tenant_id)
        else:
            logger.warning(
                "slot_release_not_found",
                tenant_id=tenant_id,
                job_id=job_id,
            )

    async def get_active_count(self, tenant_id: str) -> int:
        """Get number of active jobs for tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            Number of currently active jobs.
        """
        return await self.redis.scard(self._active_jobs_key(tenant_id))

    async def get_active_jobs(self, tenant_id: str) -> set[str]:
        """Get set of active job IDs for tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            Set of active job IDs.
        """
        jobs = await self.redis.smembers(self._active_jobs_key(tenant_id))
        return {j.decode() if isinstance(j, bytes) else j for j in jobs}

    async def get_queued_count(self, tenant_id: str) -> int:
        """Get number of queued jobs for tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            Number of jobs waiting in queue.
        """
        return await self.redis.llen(self._queue_key(tenant_id))

    async def queue_job(
        self,
        tenant_id: str,
        job_id: str,
        task_data: dict,
    ) -> None:
        """Queue a job for later execution when slots become available.

        Args:
            tenant_id: The tenant ID.
            job_id: The Celery task ID.
            task_data: Arguments to pass when re-dispatching the task.
        """
        key = self._queue_key(tenant_id)
        queued_job = QueuedJob(
            job_id=job_id,
            task_data=task_data,
            queued_at=datetime.now(UTC).isoformat(),
        )
        await self.redis.rpush(
            key,
            json.dumps(
                {
                    "job_id": queued_job.job_id,
                    "task_data": queued_job.task_data,
                    "queued_at": queued_job.queued_at,
                }
            ),
        )
        logger.info(
            "job_queued",
            tenant_id=tenant_id,
            job_id=job_id,
        )

    async def clear_queue(self, tenant_id: str) -> int:
        """Clear all queued jobs for tenant.

        Args:
            tenant_id: The tenant ID.

        Returns:
            Number of jobs that were cleared.
        """
        queue_key = self._queue_key(tenant_id)
        count = await self.redis.llen(queue_key)
        await self.redis.delete(queue_key)
        logger.warning(
            "tenant_queue_cleared",
            tenant_id=tenant_id,
            cleared_count=count,
        )
        return count

    async def _process_queued_jobs(self, tenant_id: str) -> None:
        """Process any queued jobs that can now run.

        Called after a slot is released to dispatch waiting jobs.

        Args:
            tenant_id: The tenant ID.
        """
        # Import here to avoid circular dependency
        from tasks.ingest import process_document

        queue_key = self._queue_key(tenant_id)

        while True:
            # Peek at next job without removing
            job_data = await self.redis.lindex(queue_key, 0)
            if not job_data:
                break

            job = json.loads(job_data)
            job_id = job["job_id"]

            # Try to acquire a slot for this job
            acquired, _ = await self.try_acquire_slot(tenant_id, job_id)
            if not acquired:
                # No more slots available
                break

            # Remove from queue and dispatch
            await self.redis.lpop(queue_key)

            # Re-dispatch the task with a new task ID
            # (original task already returned "queued" status)
            process_document.apply_async(
                kwargs=job["task_data"],
            )

            logger.info(
                "queued_job_dispatched",
                tenant_id=tenant_id,
                original_job_id=job_id,
            )

    async def get_all_active_tenants(self) -> list[str]:
        """Get list of all tenants with active jobs.

        Returns:
            List of tenant IDs with at least one active job.
        """
        pattern = f"{self._key_prefix}:active:*"
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            tenant_id = key_str.split(":")[-1]
            keys.append(tenant_id)
        return keys
