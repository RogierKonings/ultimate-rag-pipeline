"""Celery tasks for async document processing.

This module provides Celery-based background job processing for:
- Document ingestion (process_document, batch_ingest)
- Re-embedding (reembed_collection)
- Job status tracking

Example:
    Start a worker:
    $ celery -A services.ingestion.tasks.celery_app worker --loglevel=info --queues=ingestion,embedding,reembed
"""

from .celery_app import celery_app, create_celery_app, CeleryConfig
from .models import (
    JobStatus,
    JobProgress,
    IngestJobResult,
    IngestJobRequest,
)
from .ingest import process_document, batch_ingest
from .reembed import reembed_collection
from .callbacks import send_to_dlq
from .status import JobStatusTracker

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
    "send_to_dlq",
    # Status tracking
    "JobStatusTracker",
]
