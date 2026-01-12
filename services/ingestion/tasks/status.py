"""Job status tracking for async tasks.

This module provides the JobStatusTracker class for querying
Celery task states and managing jobs.
"""

import json
import logging

import redis.asyncio as redis
from celery.result import AsyncResult

from .celery_app import celery_app
from .models import IngestJobResult, JobProgress, JobStatus

logger = logging.getLogger(__name__)


class JobStatusTracker:
    """Track and query job status.

    Provides methods for getting job status, cancelling jobs,
    and listing active jobs and DLQ entries.

    Example:
        async with JobStatusTracker() as tracker:
            status = await tracker.get_job_status("task-id-123")
            print(status.status)
    """

    def __init__(self, redis_url: str | None = None):
        """Initialize the job status tracker.

        Args:
            redis_url: Redis URL for DLQ queries. Defaults to env var or localhost.
        """
        import os

        self.redis_url = redis_url or os.getenv(
            "REDIS_URL",
            "redis://localhost:6379/2",
        )
        self._redis: redis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(
            self.redis_url,
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def __aenter__(self) -> "JobStatusTracker":
        """Enter async context manager."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        await self.disconnect()

    async def get_job_status(self, job_id: str) -> IngestJobResult:
        """Get current status of an ingestion job.

        Args:
            job_id: Celery task ID.

        Returns:
            IngestJobResult with current status and progress.
        """
        result = AsyncResult(job_id, app=celery_app)

        status_map = {
            "PENDING": JobStatus.PENDING,
            "STARTED": JobStatus.STARTED,
            "PROGRESS": JobStatus.PROGRESS,
            "SUCCESS": JobStatus.SUCCESS,
            "FAILURE": JobStatus.FAILURE,
            "RETRY": JobStatus.RETRY,
            "REVOKED": JobStatus.REVOKED,
        }

        status = status_map.get(result.status, JobStatus.PENDING)

        # Get task info
        info = result.info or {}

        # Handle case where info is an exception
        if isinstance(info, Exception):
            return IngestJobResult(
                job_id=job_id,
                status=JobStatus.FAILURE,
                error_message=str(info),
            )

        # Build progress if in progress state
        progress = None
        if status == JobStatus.PROGRESS and isinstance(info, dict):
            progress = JobProgress(
                current=info.get("processed", 0),
                total=info.get("total", 0),
                stage=info.get("stage", ""),
                message=info.get("message", ""),
            )

        # Extract result data if successful
        documents_processed = 0
        chunks_created = 0
        if status == JobStatus.SUCCESS and isinstance(info, dict):
            documents_processed = info.get("documents_processed", 1)
            chunks_created = info.get("chunks_created", info.get("total_chunks", 0))

        return IngestJobResult(
            job_id=job_id,
            status=status,
            progress=progress,
            documents_processed=documents_processed,
            chunks_created=chunks_created,
            errors=info.get("errors", []) if isinstance(info, dict) else [],
            started_at=info.get("started_at") if isinstance(info, dict) else None,
            completed_at=info.get("completed_at") if isinstance(info, dict) else None,
            duration_seconds=info.get("duration_seconds") if isinstance(info, dict) else None,
            error_message=info.get("error")
            if status == JobStatus.FAILURE and isinstance(info, dict)
            else None,
            traceback=info.get("traceback")
            if status == JobStatus.FAILURE and isinstance(info, dict)
            else None,
        )

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.

        Args:
            job_id: Celery task ID to cancel.

        Returns:
            True if revocation was sent.
        """
        try:
            result = AsyncResult(job_id, app=celery_app)
            result.revoke(terminate=True)
            logger.info(f"Cancelled job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False

    async def list_active_jobs(self) -> list[str]:
        """List all active job IDs.

        Returns:
            List of active task IDs.
        """
        try:
            inspect = celery_app.control.inspect()
            active = inspect.active() or {}

            job_ids = []
            for _worker, tasks in active.items():
                for task in tasks:
                    job_ids.append(task["id"])

            return job_ids
        except Exception as e:
            logger.error(f"Failed to list active jobs: {e}")
            return []

    async def list_dlq_entries(self, limit: int = 100) -> list[dict]:
        """List entries in dead letter queue.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of DLQ entry dicts.
        """
        if not self._redis:
            await self.connect()

        pattern = "dlq:*"
        entries = []

        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor,
                    match=pattern,
                    count=100,
                )
                for key in keys[: limit - len(entries)]:
                    data = await self._redis.get(key)
                    if data:
                        entry = json.loads(data)
                        entry["dlq_key"] = key
                        entries.append(entry)

                if cursor == 0 or len(entries) >= limit:
                    break

            return entries

        except Exception as e:
            logger.error(f"Failed to list DLQ entries: {e}")
            return []

    async def delete_dlq_entry(self, dlq_key: str) -> bool:
        """Delete a DLQ entry.

        Args:
            dlq_key: Key of the DLQ entry to delete.

        Returns:
            True if deleted, False otherwise.
        """
        if not self._redis:
            await self.connect()

        try:
            result = await self._redis.delete(dlq_key)
            return result > 0
        except Exception as e:
            logger.error(f"Failed to delete DLQ entry: {e}")
            return False

    async def get_queue_stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dict mapping queue names to message counts.
        """
        try:
            inspect = celery_app.control.inspect()
            reserved = inspect.reserved() or {}
            active = inspect.active() or {}
            scheduled = inspect.scheduled() or {}

            return {
                "reserved": sum(len(tasks) for tasks in reserved.values()),
                "active": sum(len(tasks) for tasks in active.values()),
                "scheduled": sum(len(tasks) for tasks in scheduled.values()),
            }

        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}
