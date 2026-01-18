"""Data models for rate limiting module."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class TenantLimits:
    """Rate limit configuration for a tenant.

    Attributes:
        max_concurrent_jobs: Maximum number of concurrent ingestion jobs allowed.
        priority: Queue priority level for this tenant's jobs.
        hard_limit: If True, reject jobs exceeding limit with error.
                   If False, queue them for later execution.
    """

    max_concurrent_jobs: int = 10
    priority: Literal["high", "normal", "low"] = "normal"
    hard_limit: bool = False

    def to_redis_hash(self) -> dict[str, str]:
        """Convert to Redis hash mapping."""
        return {
            "max_concurrent": str(self.max_concurrent_jobs),
            "priority": self.priority,
            "hard_limit": str(self.hard_limit).lower(),
        }

    @classmethod
    def from_redis_hash(
        cls,
        data: dict[bytes, bytes],
        default_max: int = 10,
    ) -> "TenantLimits":
        """Create from Redis hash data."""
        if not data:
            return cls(max_concurrent_jobs=default_max)

        return cls(
            max_concurrent_jobs=int(data.get(b"max_concurrent", default_max)),
            priority=data.get(b"priority", b"normal").decode(),
            hard_limit=data.get(b"hard_limit", b"false") == b"true",
        )


@dataclass
class QueuedJob:
    """A job waiting in the queue for a slot to become available.

    Attributes:
        job_id: Celery task ID.
        task_data: Arguments to pass when re-dispatching the task.
        queued_at: ISO format timestamp when job was queued.
    """

    job_id: str
    task_data: dict
    queued_at: str
