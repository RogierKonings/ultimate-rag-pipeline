"""Task callbacks and dead letter queue handling.

This module provides callbacks for task lifecycle events and
a dead letter queue for failed tasks.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.callbacks.send_to_dlq",
    queue="dlq",
)
def send_to_dlq(failure_info: dict[str, Any]) -> dict[str, Any]:
    """Store failed task info in dead letter queue for manual review.

    Args:
        failure_info: Dict containing task name, args, error info, etc.

    Returns:
        Dict with DLQ entry key and status.
    """
    from shared.cache.redis_client import get_redis_client

    task_name = failure_info.get("task_name", "unknown")
    timestamp = datetime.now(tz=UTC).isoformat()

    # Create unique DLQ key
    dlq_key = f"dlq:{task_name}:{timestamp}"

    # Add timestamp to failure info
    failure_info["failed_at"] = timestamp

    try:
        redis_client = get_redis_client()
        redis_client.setex(
            dlq_key,
            86400 * 7,  # Keep for 7 days
            json.dumps(failure_info, default=str),
        )

        logger.error(
            f"Task sent to DLQ: {task_name}",
            extra={
                "dlq_key": dlq_key,
                "error": failure_info.get("error"),
                "retries": failure_info.get("retries", 0),
            },
        )

        return {"dlq_key": dlq_key, "status": "stored"}

    except Exception as e:
        logger.error(f"Failed to store task in DLQ: {e}")
        return {"dlq_key": None, "status": "failed", "error": str(e)}


def on_task_failure(
    self,
    exc: Exception,
    task_id: str,
    args: tuple,
    kwargs: dict,
    einfo,
) -> None:
    """Signal handler for task failure events.

    This can be registered as a signal handler to automatically
    send failed tasks to the DLQ.

    Args:
        self: Task instance.
        exc: Exception that caused the failure.
        task_id: Celery task ID.
        args: Task positional arguments.
        kwargs: Task keyword arguments.
        einfo: Exception info object.
    """
    logger.error(f"Task {task_id} failed: {exc}")

    send_to_dlq.delay(
        {
            "task_name": self.name,
            "task_id": task_id,
            "args": list(args),
            "kwargs": kwargs,
            "error": str(exc),
            "traceback": str(einfo) if einfo else None,
        },
    )


def retry_dlq_entry(dlq_key: str) -> bool:
    """Retry a task from the dead letter queue.

    Args:
        dlq_key: Key of the DLQ entry to retry.

    Returns:
        True if task was resubmitted, False otherwise.
    """
    from shared.cache.redis_client import get_redis_client

    try:
        redis_client = get_redis_client()
        data = redis_client.get(dlq_key)

        if not data:
            logger.warning(f"DLQ entry not found: {dlq_key}")
            return False

        entry = json.loads(data)
        task_name = entry.get("task_name")
        args = entry.get("args", [])
        kwargs = entry.get("kwargs", {})

        # Get the task by name and retry
        task = celery_app.tasks.get(f"tasks.ingest.{task_name}")
        if task:
            task.apply_async(args=args, kwargs=kwargs)
            # Remove from DLQ after successful retry
            redis_client.delete(dlq_key)
            logger.info(f"Retried task from DLQ: {dlq_key}")
            return True
        logger.error(f"Task not found: {task_name}")
        return False

    except Exception as e:
        logger.error(f"Failed to retry DLQ entry: {e}")
        return False
