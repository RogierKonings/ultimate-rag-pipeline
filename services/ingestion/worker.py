#!/usr/bin/env python
"""Celery worker entry point with OpenTelemetry instrumentation (US-2.12).

This script starts a Celery worker for the ingestion service with full
observability including distributed tracing and metrics.

Usage:
    # Start worker for all queues
    celery -A services.ingestion.tasks.celery_app worker --loglevel=info --queues=ingestion,embedding,reembed

    # Start worker for specific queue
    celery -A services.ingestion.tasks.celery_app worker --loglevel=info --queues=ingestion --concurrency=4

    # Or run this script directly
    python worker.py

    # Start Celery beat for scheduled tasks (if needed)
    celery -A services.ingestion.tasks.celery_app beat --loglevel=info

    # Monitor with Flower (optional)
    celery -A services.ingestion.tasks.celery_app flower --port=5555
"""

import logging
import os
import sys
from pathlib import Path

import tasks.callbacks  # noqa: F401

# Import tasks to register them
import tasks.ingest  # noqa: F401
import tasks.reembed  # noqa: F401
from tasks.celery_app import celery_app

# Configure logging with trace context format (US-2.12)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [trace_id=%(trace_id)s span_id=%(span_id)s] - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)

# Add default trace fields for logs without context
old_factory = logging.getLogRecordFactory()


def trace_context_factory(*args, **kwargs):
    record = old_factory(*args, **kwargs)
    if not hasattr(record, "trace_id"):
        record.trace_id = "-"
    if not hasattr(record, "span_id"):
        record.span_id = "-"
    return record


logging.setLogRecordFactory(trace_context_factory)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    # Initialize telemetry before starting worker (US-2.12)
    from telemetry import instrument_celery, setup_telemetry

    logger.info("Initializing OpenTelemetry and Prometheus metrics...")
    setup_telemetry()
    instrument_celery()

    logger.info("Starting Celery worker for ingestion service...")

    # Default queues to listen on
    default_queues = "ingestion,embedding,reembed,dlq"
    queues = os.getenv("CELERY_QUEUES", default_queues)

    # Start the worker
    celery_app.worker_main(
        argv=[
            "worker",
            f"--queues={queues}",
            "--loglevel=info",
        ],
    )
