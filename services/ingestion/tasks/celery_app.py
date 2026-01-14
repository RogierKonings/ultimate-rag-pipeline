"""Celery application configuration for the ingestion service.

This module configures Celery with Redis as the message broker for async task
processing. It defines queues for different task types and routing rules.

Queue configuration:
- ingestion: Document ingestion tasks
- video: Video processing tasks
- embedding: Embedding generation tasks
- reembed: Re-embedding tasks for model migration
- maintenance: Background maintenance tasks (reconciliation, cleanup)
- dlq: Dead letter queue for failed tasks
"""

import os

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue
from pydantic import BaseModel


class CeleryConfig(BaseModel):
    """Configuration for Celery application."""

    # Broker settings
    broker_url: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # Task settings
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = ["json"]
    task_track_started: bool = True
    task_time_limit: int = 3600  # 1 hour max
    task_soft_time_limit: int = 3300  # Soft limit 55 min

    # Worker settings
    worker_prefetch_multiplier: int = 1  # Disable prefetch for long tasks
    worker_concurrency: int = int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))

    # Retry settings
    task_default_retry_delay: int = 60  # 1 minute
    task_max_retries: int = 3

    # Result expiration
    result_expires: int = 86400  # 24 hours

    # Queue configuration
    task_default_queue: str = "ingestion"

    model_config = {"frozen": True}


def create_celery_app(config: CeleryConfig | None = None) -> Celery:
    """Create and configure Celery application.

    Args:
        config: Optional Celery configuration. Uses defaults if not provided.

    Returns:
        Configured Celery application instance.
    """
    if config is None:
        config = CeleryConfig()

    app = Celery("ingestion")

    app.conf.update(
        broker_url=config.broker_url,
        result_backend=config.result_backend,
        task_serializer=config.task_serializer,
        result_serializer=config.result_serializer,
        accept_content=config.accept_content,
        task_track_started=config.task_track_started,
        task_time_limit=config.task_time_limit,
        task_soft_time_limit=config.task_soft_time_limit,
        worker_prefetch_multiplier=config.worker_prefetch_multiplier,
        worker_concurrency=config.worker_concurrency,
        result_expires=config.result_expires,
        task_default_queue=config.task_default_queue,
    )

    # Define exchanges
    ingestion_exchange = Exchange("ingestion", type="direct")
    video_exchange = Exchange("video", type="direct")
    embedding_exchange = Exchange("embedding", type="direct")
    reembed_exchange = Exchange("reembed", type="direct")
    maintenance_exchange = Exchange("maintenance", type="direct")
    dlq_exchange = Exchange("dlq", type="direct")

    # Define queues
    app.conf.task_queues = (
        Queue("ingestion", ingestion_exchange, routing_key="ingestion"),
        Queue("video", video_exchange, routing_key="video"),
        Queue("embedding", embedding_exchange, routing_key="embedding"),
        Queue("reembed", reembed_exchange, routing_key="reembed"),
        Queue("maintenance", maintenance_exchange, routing_key="maintenance"),
        Queue("dlq", dlq_exchange, routing_key="dlq"),
    )

    # Route tasks to queues
    app.conf.task_routes = {
        "tasks.ingest.*": {"queue": "ingestion"},
        "tasks.video_ingest.*": {"queue": "video"},
        "tasks.reembed.*": {"queue": "reembed"},
        "tasks.reconcile.*": {"queue": "maintenance"},
        "tasks.callbacks.*": {"queue": "dlq"},
    }

    # Configure dead letter queue behavior
    app.conf.task_reject_on_worker_lost = True

    # Configure Celery Beat schedule for periodic tasks
    app.conf.beat_schedule = {
        "nightly-reconciliation": {
            "task": "tasks.reconcile.reconcile_all_tenants",
            "schedule": crontab(hour=3, minute=0),  # 3 AM daily
            "kwargs": {"dry_run": False},
            "options": {"queue": "maintenance"},
        },
    }

    return app


# Singleton app instance
celery_app = create_celery_app()
