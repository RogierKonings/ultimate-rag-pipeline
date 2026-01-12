"""
Shared Observability Module for RAG Pipeline.

This module provides centralized observability capabilities:
- OpenTelemetry distributed tracing
- Prometheus metrics collection
- Structured JSON logging with trace correlation
- RAG-specific semantic attributes and metrics

Usage:
    from shared.observability import setup_observability
    from shared.observability.otel import get_tracer, traced
    from shared.observability.metrics import get_metrics, RAGMetrics

    # At application startup
    setup_observability(service_name="my-service")

    # Use decorators for tracing
    @traced("my_operation")
    async def my_function():
        pass

    # Record metrics
    metrics = get_metrics()
    metrics.record_query(mode="hybrid", duration=0.5, result_count=10)
"""

from .metrics import get_metrics, setup_metrics
from .otel import get_tracer, setup_tracing
from .otel.attributes import RAGAttributes, RAGOperation
from .otel.spans import rag_span, traced

__all__ = [
    # Setup functions
    "setup_observability",
    "setup_tracing",
    "setup_metrics",
    # Tracing
    "get_tracer",
    "traced",
    "rag_span",
    # Attributes
    "RAGOperation",
    "RAGAttributes",
    # Metrics
    "get_metrics",
]


def setup_observability(
    service_name: str,
    service_version: str = "1.0.0",
    otlp_endpoint: str | None = None,
    enable_tracing: bool = True,
    enable_metrics: bool = True,
    environment: str = "development",
) -> None:
    """
    Initialize all observability components.

    This is the main entry point for setting up observability in a service.
    Call this once at application startup.

    Args:
        service_name: Name of the service (e.g., "retrieval-service")
        service_version: Version of the service
        otlp_endpoint: OTLP collector endpoint (default: from env or localhost:4317)
        enable_tracing: Whether to enable OpenTelemetry tracing
        enable_metrics: Whether to enable Prometheus metrics
        environment: Deployment environment (development, staging, production)
    """
    if enable_tracing:
        setup_tracing(
            service_name=service_name,
            service_version=service_version,
            otlp_endpoint=otlp_endpoint,
            environment=environment,
        )

    if enable_metrics:
        setup_metrics(
            service_name=service_name,
            service_version=service_version,
        )
