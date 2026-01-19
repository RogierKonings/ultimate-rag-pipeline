"""Business and quality metrics for RAG observability.

This module provides Prometheus metrics for tracking RAG query quality,
user feedback, and business-level KPIs.

Reference: US-10.3.3 - Business & Quality Metrics
"""

from prometheus_client import Counter, Gauge, Histogram

# =============================================================================
# Query Metrics
# =============================================================================

rag_queries_total = Counter(
    "rag_queries_total",
    "Total RAG queries processed",
    ["strategy", "rag_used", "degraded", "tenant_id", "status"],
)

rag_e2e_latency = Histogram(
    "rag_e2e_latency_seconds",
    "End-to-end RAG query latency",
    ["strategy", "tenant_tier", "degraded"],
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

# =============================================================================
# Component Latency Metrics
# =============================================================================

rag_component_latency = Histogram(
    "rag_component_latency_seconds",
    "Latency per RAG component",
    ["component"],  # routing, retrieval, prompt, generation, validation
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# =============================================================================
# Feedback Metrics
# =============================================================================

rag_feedback_total = Counter(
    "rag_feedback_total",
    "User feedback on RAG responses",
    ["rating", "tenant_id"],  # rating: positive, negative, neutral
)

rag_feedback_score = Gauge(
    "rag_feedback_score",
    "Rolling feedback score (positive / total)",
    ["tenant_id"],
)

# =============================================================================
# Fallback and Degradation Metrics
# =============================================================================

rag_fallback_usage = Counter(
    "rag_fallback_usage_total",
    "Times a fallback was used",
    ["fallback_type", "tenant_id"],  # cache_hit, no_retrieval, degraded_retrieval
)

rag_degraded_queries = Counter(
    "rag_degraded_queries_total",
    "Queries served in degraded mode",
    ["degradation_mode", "tenant_id"],
)

# =============================================================================
# Quality Indicator Metrics
# =============================================================================

rag_context_relevance = Histogram(
    "rag_context_relevance_score",
    "Relevance score of retrieved context (from reranker)",
    ["tenant_id"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

rag_citations_per_response = Histogram(
    "rag_citations_per_response",
    "Number of citations/sources in RAG response",
    ["tenant_id"],
    buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
)
