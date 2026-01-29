"""Celery tasks for async document processing.

This module provides Celery-based background job processing for:
- Document ingestion (process_document, batch_ingest)
- Re-embedding (reembed_collection)
- Deletion propagation (propagate_deletion)
- Job status tracking

Note: Video processing has been migrated to the Rust rag-video crate.

Example:
    Start a worker:
    $ celery -A services.ingestion.tasks.celery_app worker --loglevel=info --queues=ingestion,embedding,reembed
"""

from .callbacks import send_to_dlq
from .celery_app import CeleryConfig, celery_app, create_celery_app
from .ingest import batch_ingest, process_document
from .models import (
    IngestJobRequest,
    IngestJobResult,
    JobProgress,
    JobStatus,
)
from .reembed import reembed_collection
from .status import JobStatusTracker
from .tombstone import propagate_deletion

# Note: process_video task removed - video processing now handled by Rust rag-video crate

__all__ = [
    # Celery app
    "celery_app",
    "create_celery_app",
    "CeleryConfig",
    # Models
    "JobStatus",
    "JobProgress",
    "IngestJobResult",
    "IngestJobRequest",
    # Tasks
    "process_document",
    "batch_ingest",
    "reembed_collection",
    "propagate_deletion",
    "send_to_dlq",
    # Status tracking
    "JobStatusTracker",
]
