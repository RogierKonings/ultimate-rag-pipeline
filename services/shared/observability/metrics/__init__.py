"""
Prometheus Metrics Module.

Provides centralized metrics collection for RAG pipeline services:
- Standard RAG metrics (queries, retrieval, LLM, ingestion, cache)
- Custom collectors for external systems (Qdrant, PostgreSQL)
- FastAPI middleware for request metrics
- /metrics endpoint for Prometheus scraping

Usage:
    from shared.observability.metrics import setup_metrics, get_metrics

    # At startup
    setup_metrics(service_name="retrieval-service")

    # Record metrics
    metrics = get_metrics()
    metrics.record_query(mode="hybrid", duration=0.5, result_count=10)
"""

from .registry import (
    RAGMetrics,
    setup_metrics,
    get_metrics,
    get_metrics_registry,
)
from .middleware import PrometheusMiddleware
from .exporters import get_metrics_endpoint, setup_metrics_endpoint

__all__ = [
    # Core metrics
    "RAGMetrics",
    "setup_metrics",
    "get_metrics",
    "get_metrics_registry",
    # Middleware
    "PrometheusMiddleware",
    # Exporters
    "get_metrics_endpoint",
    "setup_metrics_endpoint",
]
