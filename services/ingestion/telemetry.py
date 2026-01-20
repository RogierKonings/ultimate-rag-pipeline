"""Observability module with OpenTelemetry tracing and Prometheus metrics (US-2.12).

This module provides:
- OpenTelemetry tracing with automatic context propagation
- Prometheus metrics for ingestion service
- Structured logging with trace context
- Helper functions for creating spans and recording metrics

Usage:
    from telemetry import setup_telemetry, get_tracer, get_meter, log_ingest_event

    # At application startup
    setup_telemetry()

    # Create spans
    tracer = get_tracer()
    with tracer.start_as_current_span("process_document") as span:
        span.set_attribute("document_id", str(document_id))

    # Record metrics
    meter = get_meter()
    ingest_counter = meter.create_counter("ingest_documents_total")
    ingest_counter.add(1, {"status": "success"})
"""

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any
from uuid import UUID

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from config import get_settings

logger = logging.getLogger(__name__)

# Global tracer and meter instances
_tracer: trace.Tracer | None = None
_meter: metrics.Meter | None = None
_initialized: bool = False

# Prometheus metrics (will be created on setup)
INGEST_DOCUMENTS_TOTAL: Counter | None = None
INGEST_CHUNKS_TOTAL: Counter | None = None
INGEST_LATENCY_SECONDS: Histogram | None = None
EMBEDDING_LATENCY_SECONDS: Histogram | None = None
INDEXING_LATENCY_SECONDS: Histogram | None = None
DOCUMENTS_BY_INDEX_STATUS: Gauge | None = None

# Reconciliation metrics (US-10.1.2)
RECONCILIATION_RUNS: Counter | None = None
RECONCILIATION_DURATION: Histogram | None = None
RECONCILIATION_ORPHANS_CLEANED: Counter | None = None
RECONCILIATION_MISSING_REINDEXED: Counter | None = None


def setup_telemetry() -> None:
    """Initialize OpenTelemetry tracing and Prometheus metrics.

    This should be called once at application startup.
    """
    global _tracer, _meter, _initialized
    global INGEST_DOCUMENTS_TOTAL, INGEST_CHUNKS_TOTAL, INGEST_LATENCY_SECONDS
    global EMBEDDING_LATENCY_SECONDS, INDEXING_LATENCY_SECONDS, DOCUMENTS_BY_INDEX_STATUS
    global RECONCILIATION_RUNS, RECONCILIATION_DURATION
    global RECONCILIATION_ORPHANS_CLEANED, RECONCILIATION_MISSING_REINDEXED

    if _initialized:
        return

    settings = get_settings()

    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled, using no-op tracer")
        _tracer = trace.get_tracer(__name__)
        _meter = metrics.get_meter(__name__)
        _initialized = True
        return

    # Create resource with service name
    resource = Resource(attributes={SERVICE_NAME: settings.otel_service_name})

    # Setup tracing
    tracer_provider = TracerProvider(resource=resource)

    # Add OTLP exporter for traces
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=True,
        )
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    except Exception as e:
        logger.warning(f"Failed to setup OTLP trace exporter: {e}")

    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer(__name__)

    # Setup metrics with Prometheus exporter
    try:
        prometheus_reader = PrometheusMetricReader()
        meter_provider = MeterProvider(resource=resource, metric_readers=[prometheus_reader])
        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter(__name__)
    except Exception as e:
        logger.warning(f"Failed to setup Prometheus metrics: {e}")
        _meter = metrics.get_meter(__name__)

    # Create Prometheus metrics
    INGEST_DOCUMENTS_TOTAL = Counter(
        "ingest_documents_total",
        "Total number of documents ingested",
        ["status", "source_type", "tenant_id"],
    )
    INGEST_CHUNKS_TOTAL = Counter(
        "ingest_chunks_total",
        "Total number of chunks created",
        ["tenant_id"],
    )
    INGEST_LATENCY_SECONDS = Histogram(
        "ingest_latency_seconds",
        "Document ingestion latency in seconds",
        ["stage"],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
    )
    EMBEDDING_LATENCY_SECONDS = Histogram(
        "embedding_latency_seconds",
        "Embedding generation latency in seconds",
        ["model"],
        buckets=[0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
    )
    INDEXING_LATENCY_SECONDS = Histogram(
        "indexing_latency_seconds",
        "Indexing latency in seconds",
        ["store"],
        buckets=[0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
    )
    DOCUMENTS_BY_INDEX_STATUS = Gauge(
        "documents_by_index_status",
        "Number of documents by indexing status (US-10.1.1)",
        ["store", "status", "tenant_id"],
    )

    # Reconciliation metrics (US-10.1.2)
    RECONCILIATION_RUNS = Counter(
        "index_reconciliation_runs_total",
        "Total reconciliation runs",
        ["tenant_id", "status"],  # status: success, failure, partial
    )
    RECONCILIATION_DURATION = Histogram(
        "index_reconciliation_duration_seconds",
        "Duration of reconciliation runs",
        ["tenant_id"],
        buckets=[60, 300, 600, 1800, 3600],  # 1min, 5min, 10min, 30min, 1hr
    )
    RECONCILIATION_ORPHANS_CLEANED = Counter(
        "index_orphans_cleaned_total",
        "Total orphaned entries cleaned",
        ["store"],  # qdrant, opensearch
    )
    RECONCILIATION_MISSING_REINDEXED = Counter(
        "index_missing_reindexed_total",
        "Total missing entries re-indexed",
        ["store"],
    )

    # Start Prometheus metrics server
    if settings.metrics_enabled:
        try:
            start_http_server(settings.metrics_port)
            logger.info(f"Prometheus metrics server started on port {settings.metrics_port}")
        except Exception as e:
            logger.warning(f"Failed to start Prometheus server: {e}")

    _initialized = True
    logger.info("Telemetry initialized successfully")


def instrument_fastapi(app) -> None:
    """Instrument FastAPI application for automatic tracing.

    Args:
        app: FastAPI application instance.
    """
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")


def instrument_celery() -> None:
    """Instrument Celery for automatic tracing of tasks."""
    try:
        CeleryInstrumentor().instrument()
        logger.info("Celery instrumentation enabled")
    except Exception as e:
        logger.warning(f"Failed to instrument Celery: {e}")


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance.

    Returns:
        OpenTelemetry tracer.
    """
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(__name__)
    return _tracer


def get_meter() -> metrics.Meter:
    """Get the global meter instance.

    Returns:
        OpenTelemetry meter.
    """
    global _meter
    if _meter is None:
        _meter = metrics.get_meter(__name__)
    return _meter


def get_current_trace_context() -> dict[str, str]:
    """Get current trace context for logging and propagation.

    Returns:
        Dictionary with trace_id and span_id if available.
    """
    span = trace.get_current_span()
    if span is None:
        return {}

    span_context = span.get_span_context()
    if not span_context.is_valid:
        return {}

    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


class StructuredLogger:
    """Structured logger with automatic trace context injection."""

    def __init__(self, name: str):
        """Initialize structured logger.

        Args:
            name: Logger name.
        """
        self._logger = logging.getLogger(name)

    def _add_trace_context(self, extra: dict) -> dict:
        """Add trace context to log extra fields."""
        context = get_current_trace_context()
        return {**extra, **context}

    def info(self, message: str, **extra: Any) -> None:
        """Log info message with trace context."""
        self._logger.info(message, extra=self._add_trace_context(extra))

    def warning(self, message: str, **extra: Any) -> None:
        """Log warning message with trace context."""
        self._logger.warning(message, extra=self._add_trace_context(extra))

    def error(self, message: str, **extra: Any) -> None:
        """Log error message with trace context."""
        self._logger.error(message, extra=self._add_trace_context(extra))

    def debug(self, message: str, **extra: Any) -> None:
        """Log debug message with trace context."""
        self._logger.debug(message, extra=self._add_trace_context(extra))


def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger with trace context support.

    Args:
        name: Logger name.

    Returns:
        StructuredLogger instance.
    """
    return StructuredLogger(name)


@contextmanager
def timed_span(name: str, attributes: dict | None = None):
    """Context manager for creating a timed span.

    Args:
        name: Span name.
        attributes: Optional span attributes.

    Yields:
        The span instance.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value) if isinstance(value, UUID) else value)

        start_time = time.perf_counter()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            duration = time.perf_counter() - start_time
            span.set_attribute("duration_seconds", duration)


def traced(name: str | None = None, record_args: bool = False):
    """Decorator for tracing function calls.

    Args:
        name: Optional span name (defaults to function name).
        record_args: Whether to record function arguments as attributes.

    Returns:
        Decorated function.
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with timed_span(span_name) as span:
                if record_args and kwargs:
                    for key, value in kwargs.items():
                        if isinstance(value, (str, int, float, bool)):
                            span.set_attribute(f"arg.{key}", value)
                        elif isinstance(value, UUID):
                            span.set_attribute(f"arg.{key}", str(value))
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with timed_span(span_name) as span:
                if record_args and kwargs:
                    for key, value in kwargs.items():
                        if isinstance(value, (str, int, float, bool)):
                            span.set_attribute(f"arg.{key}", value)
                        elif isinstance(value, UUID):
                            span.set_attribute(f"arg.{key}", str(value))
                return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def log_ingest_event(
    event_type: str,
    tenant_id: UUID,
    document_id: UUID | None = None,
    job_id: UUID | None = None,
    status: str = "success",
    latency_ms: int | None = None,
    chunks_created: int = 0,
    source_type: str | None = None,
    **extra_metadata: Any,
) -> None:
    """Log an ingestion event with full context.

    This creates a structured log entry with trace context, and updates
    Prometheus metrics.

    Args:
        event_type: Type of event (e.g., "document_ingested", "chunk_created").
        tenant_id: Tenant identifier.
        document_id: Optional document identifier.
        job_id: Optional job identifier.
        status: Event status ("success", "failure", "skipped").
        latency_ms: Optional latency in milliseconds.
        chunks_created: Number of chunks created (for document ingestion).
        source_type: Optional source type (file, web, api, database).
        **extra_metadata: Additional metadata to include.
    """
    slogger = get_structured_logger("ingestion.events")
    trace_context = get_current_trace_context()

    # Build structured log entry
    log_data = {
        "event_type": event_type,
        "tenant_id": str(tenant_id),
        "status": status,
        **trace_context,
        **extra_metadata,
    }

    if document_id:
        log_data["document_id"] = str(document_id)
    if job_id:
        log_data["job_id"] = str(job_id)
    if latency_ms:
        log_data["latency_ms"] = latency_ms
    if chunks_created:
        log_data["chunks_created"] = chunks_created
    if source_type:
        log_data["source_type"] = source_type

    # Log the event
    if status == "failure":
        slogger.error(f"Ingest event: {event_type}", **log_data)
    else:
        slogger.info(f"Ingest event: {event_type}", **log_data)

    # Update Prometheus metrics
    if INGEST_DOCUMENTS_TOTAL and event_type == "document_ingested":
        INGEST_DOCUMENTS_TOTAL.labels(
            status=status,
            source_type=source_type or "unknown",
            tenant_id=str(tenant_id)[:8],
        ).inc()

    if INGEST_CHUNKS_TOTAL and chunks_created > 0:
        INGEST_CHUNKS_TOTAL.labels(tenant_id=str(tenant_id)[:8]).inc(chunks_created)

    if INGEST_LATENCY_SECONDS and latency_ms:
        INGEST_LATENCY_SECONDS.labels(stage="total").observe(latency_ms / 1000)


def record_embedding_latency(duration_seconds: float, model: str) -> None:
    """Record embedding generation latency.

    Args:
        duration_seconds: Latency in seconds.
        model: Embedding model name.
    """
    if EMBEDDING_LATENCY_SECONDS:
        EMBEDDING_LATENCY_SECONDS.labels(model=model).observe(duration_seconds)


def record_indexing_latency(duration_seconds: float, store: str) -> None:
    """Record indexing latency.

    Args:
        duration_seconds: Latency in seconds.
        store: Store name (qdrant, opensearch, postgres).
    """
    if INDEXING_LATENCY_SECONDS:
        INDEXING_LATENCY_SECONDS.labels(store=store).observe(duration_seconds)


async def update_index_status_metrics(db_session) -> None:
    """Update Prometheus gauges with current index status counts (US-10.1.1).

    This function queries the documents table and updates the
    documents_by_index_status gauge with current counts per store/status/tenant.

    Should be called periodically (e.g., every 60 seconds) by a background task
    or on-demand when status changes.

    Args:
        db_session: Async SQLAlchemy session.
    """
    if not DOCUMENTS_BY_INDEX_STATUS:
        return

    try:
        from sqlalchemy import text

        # Query aggregated counts grouped by tenant and status
        query = text("""
            SELECT
                tenant_id::text as tenant_id,
                qdrant_status,
                opensearch_status,
                COUNT(*) as count
            FROM documents
            WHERE status = 'active'
            GROUP BY tenant_id, qdrant_status, opensearch_status
        """)

        result = await db_session.execute(query)
        rows = result.fetchall()

        # Clear existing gauge values to avoid stale data
        DOCUMENTS_BY_INDEX_STATUS.clear()

        # Update gauges for each combination
        for row in rows:
            tenant_id = (
                row.tenant_id[:8] if row.tenant_id else "unknown"
            )  # Truncate for cardinality

            # Update Qdrant status gauge
            DOCUMENTS_BY_INDEX_STATUS.labels(
                store="qdrant",
                status=row.qdrant_status,
                tenant_id=tenant_id,
            ).set(row.count)

            # Update OpenSearch status gauge
            DOCUMENTS_BY_INDEX_STATUS.labels(
                store="opensearch",
                status=row.opensearch_status,
                tenant_id=tenant_id,
            ).set(row.count)

        logger.debug("Index status metrics updated successfully")

    except Exception as e:
        logger.error(f"Failed to update index status metrics: {e}")
