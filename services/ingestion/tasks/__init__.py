"""Celery tasks for async document processing.

This module provides Celery-based background job processing for:
- Document ingestion (process_document, batch_ingest)
- Video processing (process_video)
- Re-embedding (reembed_collection)
- Job status tracking

Example:
    Start a worker:
    $ celery -A services.ingestion.tasks.celery_app worker --loglevel=info --queues=ingestion,video,embedding,reembed
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
from .video_ingest import process_video

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
    "process_video",
    "reembed_collection",
    "send_to_dlq",
    # Status tracking
    "JobStatusTracker",
]
