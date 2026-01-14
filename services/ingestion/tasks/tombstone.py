"""Tombstone task for propagating soft-delete to external stores (US-10.1.3).

This module implements immediate deletion propagation from PostgreSQL to
Qdrant (vector store) and OpenSearch (keyword store) when documents are
soft-deleted.

The tombstone task is triggered automatically by a SQLAlchemy event listener
when a document's status changes to 'deleted'. It ensures deleted content
never appears in search results.

Usage:
    # Manually trigger deletion propagation (rarely needed)
    from tasks.tombstone import propagate_deletion

    result = await propagate_deletion.delay(
        document_id="doc-123",
        tenant_id="tenant-456",
    )
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from celery.exceptions import Reject, SoftTimeLimitExceeded

from .celery_app import celery_app

logger = logging.getLogger(__name__)


@dataclass
class DeletionResult:
    """Result of a deletion propagation operation."""

    document_id: str
    tenant_id: str
    qdrant_deleted: int
    opensearch_deleted: int
    started_at: datetime
    completed_at: datetime
    success: bool
    errors: list[str]

    @property
    def duration_seconds(self) -> float:
        """Calculate duration of the deletion operation."""
        return (self.completed_at - self.started_at).total_seconds()


@celery_app.task(
    bind=True,
    name="tasks.tombstone.propagate_deletion",
    queue="ingestion",  # High priority queue for immediate execution
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,  # Max 1 min between retries
    acks_late=True,
    soft_time_limit=60,  # 1 minute soft limit
    time_limit=90,  # 1.5 minute hard limit
)
def propagate_deletion(
    self,
    document_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Propagate document deletion to all external stores.

    This task is idempotent - safe to retry on failure.
    Deletes are by document_id, so partial failures are recoverable.

    Args:
        document_id: UUID of the deleted document.
        tenant_id: Tenant ID for scoping.

    Returns:
        DeletionResult as dict with operation summary.
    """
    try:
        return asyncio.run(
            _propagate_deletion_async(
                document_id=document_id,
                tenant_id=tenant_id,
            )
        )
    except SoftTimeLimitExceeded:
        logger.error(
            "Deletion propagation timed out",
            extra={"document_id": document_id, "tenant_id": tenant_id},
        )
        raise Reject("Task timed out", requeue=False) from None


async def _propagate_deletion_async(
    document_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Async implementation of deletion propagation."""
    from config import get_settings
    from shared.search.opensearch_client import OpenSearchClient
    from shared.vectorstore.qdrant_client import QdrantVectorStore

    settings = get_settings()
    started_at = datetime.now(tz=UTC)

    result = DeletionResult(
        document_id=document_id,
        tenant_id=tenant_id,
        qdrant_deleted=0,
        opensearch_deleted=0,
        started_at=started_at,
        completed_at=started_at,
        success=True,
        errors=[],
    )

    logger.info(
        "deletion_propagation_started",
        extra={
            "document_id": document_id,
            "tenant_id": tenant_id,
        },
    )

    # Initialize clients
    qdrant = QdrantVectorStore(url=settings.qdrant_url)
    opensearch = OpenSearchClient(url=settings.opensearch_url)

    # Delete from Qdrant
    try:
        deleted_count = await qdrant.delete_by_document_id(
            document_id=document_id,
            tenant_id=tenant_id,
        )
        result.qdrant_deleted = deleted_count
        logger.info(
            "qdrant_deletion_complete",
            extra={
                "document_id": document_id,
                "deleted_count": deleted_count,
            },
        )
    except Exception as e:
        error_msg = f"Qdrant deletion failed: {e}"
        result.errors.append(error_msg)
        result.success = False
        logger.error(
            "qdrant_deletion_failed",
            extra={
                "document_id": document_id,
                "error": str(e),
            },
        )

    # Delete from OpenSearch
    try:
        deleted_count = await opensearch.delete_by_document_id(
            document_id=document_id,
            tenant_id=tenant_id,
        )
        result.opensearch_deleted = deleted_count
        logger.info(
            "opensearch_deletion_complete",
            extra={
                "document_id": document_id,
                "deleted_count": deleted_count,
            },
        )
    except Exception as e:
        error_msg = f"OpenSearch deletion failed: {e}"
        result.errors.append(error_msg)
        result.success = False
        logger.error(
            "opensearch_deletion_failed",
            extra={
                "document_id": document_id,
                "error": str(e),
            },
        )

    result.completed_at = datetime.now(tz=UTC)

    # Update metrics
    _update_deletion_metrics(result)

    if result.success:
        logger.info(
            "deletion_propagation_complete",
            extra={
                "document_id": document_id,
                "qdrant_deleted": result.qdrant_deleted,
                "opensearch_deleted": result.opensearch_deleted,
                "duration_seconds": result.duration_seconds,
            },
        )
    else:
        # Raise exception to trigger retry
        raise Exception("; ".join(result.errors))

    return asdict(result)


def _update_deletion_metrics(result: DeletionResult) -> None:
    """Update Prometheus metrics for deletion operations."""
    try:
        from telemetry import (
            DELETION_PROPAGATION_DURATION,
            DELETION_PROPAGATION_RUNS,
            DELETION_VECTORS_REMOVED,
        )

        if not DELETION_PROPAGATION_RUNS:
            return

        status = "success" if result.success else "failure"
        DELETION_PROPAGATION_RUNS.labels(status=status).inc()

        if DELETION_PROPAGATION_DURATION:
            DELETION_PROPAGATION_DURATION.observe(result.duration_seconds)

        if DELETION_VECTORS_REMOVED:
            DELETION_VECTORS_REMOVED.labels(store="qdrant").inc(result.qdrant_deleted)
            DELETION_VECTORS_REMOVED.labels(store="opensearch").inc(
                result.opensearch_deleted
            )

    except ImportError:
        # Metrics not configured
        pass
    except Exception as e:
        logger.warning(f"Failed to update deletion metrics: {e}")
