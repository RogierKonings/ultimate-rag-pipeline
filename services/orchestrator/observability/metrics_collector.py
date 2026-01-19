"""RAG metrics collector for business observability.

This module provides a collector class that records RAG query metrics
to Prometheus for business-level monitoring and quality tracking.

Reference: US-10.3.3 - Business & Quality Metrics
"""

from dataclasses import dataclass, field

import structlog

from .business_metrics import (
    rag_citations_per_response,
    rag_component_latency,
    rag_context_relevance,
    rag_degraded_queries,
    rag_e2e_latency,
    rag_fallback_usage,
    rag_queries_total,
)

logger = structlog.get_logger(__name__)


@dataclass
class QueryMetrics:
    """Metrics collected during a RAG query.

    Attributes:
        request_id: Unique identifier for the request.
        tenant_id: Tenant identifier (None for anonymous).
        tenant_tier: Tenant tier level (basic, standard, premium).
        strategy: Query strategy used (hybrid, semantic, direct).
        rag_used: Whether RAG retrieval was used.
        degraded: Whether the query ran in degraded mode.
        degradation_mode: The degradation mode if degraded (e.g., semantic_only).
        fallbacks_used: List of fallback types used during the query.
        e2e_latency_ms: End-to-end latency in milliseconds.
        component_timings: Dict mapping component names to latency in ms.
        context_relevance_score: Relevance score from reranker (0-1).
        citation_count: Number of citations/sources in response.
        status: Query status (success, error).
    """

    request_id: str
    tenant_id: str | None
    tenant_tier: str = "standard"
    strategy: str = "direct"
    rag_used: bool = False
    degraded: bool = False
    degradation_mode: str | None = None
    fallbacks_used: list[str] = field(default_factory=list)
    e2e_latency_ms: float = 0.0
    component_timings: dict[str, float] = field(default_factory=dict)
    context_relevance_score: float | None = None
    citation_count: int = 0
    status: str = "success"


class RAGMetricsCollector:
    """Collects and records RAG business metrics to Prometheus."""

    def record_query(self, metrics: QueryMetrics) -> None:
        """Record metrics for a completed query.

        Args:
            metrics: The collected query metrics.
        """
        tenant_label = metrics.tenant_id or "anonymous"

        # Query counter
        rag_queries_total.labels(
            strategy=metrics.strategy,
            rag_used=str(metrics.rag_used).lower(),
            degraded=str(metrics.degraded).lower(),
            tenant_id=tenant_label,
            status=metrics.status,
        ).inc()

        # E2E latency
        rag_e2e_latency.labels(
            strategy=metrics.strategy,
            tenant_tier=metrics.tenant_tier,
            degraded=str(metrics.degraded).lower(),
        ).observe(metrics.e2e_latency_ms / 1000.0)

        # Component latencies
        for component, latency_ms in metrics.component_timings.items():
            rag_component_latency.labels(
                component=component,
            ).observe(latency_ms / 1000.0)

        # Fallbacks
        for fallback in metrics.fallbacks_used:
            rag_fallback_usage.labels(
                fallback_type=fallback,
                tenant_id=tenant_label,
            ).inc()

        # Degradation
        if metrics.degraded and metrics.degradation_mode:
            rag_degraded_queries.labels(
                degradation_mode=metrics.degradation_mode,
                tenant_id=tenant_label,
            ).inc()

        # Quality metrics
        if metrics.context_relevance_score is not None:
            rag_context_relevance.labels(
                tenant_id=tenant_label,
            ).observe(metrics.context_relevance_score)

        rag_citations_per_response.labels(
            tenant_id=tenant_label,
        ).observe(metrics.citation_count)

        logger.info(
            "query_metrics_recorded",
            request_id=metrics.request_id,
            tenant_id=tenant_label,
            strategy=metrics.strategy,
            e2e_latency_ms=metrics.e2e_latency_ms,
            status=metrics.status,
        )


# Singleton instance for use across the service
metrics_collector = RAGMetricsCollector()
