"""Observability module for the Orchestrator Service.

This module provides metrics, tracing, and logging utilities.
"""

from observability.business_metrics import (
    rag_citations_per_response,
    rag_component_latency,
    rag_context_relevance,
    rag_degraded_queries,
    rag_e2e_latency,
    rag_fallback_usage,
    rag_feedback_score,
    rag_feedback_total,
    rag_queries_total,
)
from observability.llm_metrics import (
    llm_model_fallbacks,
    llm_request_duration,
    llm_requests_by_model,
    record_llm_duration,
    record_llm_request,
    record_model_fallback,
)
from observability.metrics_collector import (
    QueryMetrics,
    RAGMetricsCollector,
    metrics_collector,
)

__all__ = [
    # LLM metrics
    "llm_requests_by_model",
    "llm_request_duration",
    "llm_model_fallbacks",
    "record_llm_request",
    "record_llm_duration",
    "record_model_fallback",
    # Business metrics (US-10.3.3)
    "rag_queries_total",
    "rag_e2e_latency",
    "rag_component_latency",
    "rag_feedback_total",
    "rag_feedback_score",
    "rag_fallback_usage",
    "rag_degraded_queries",
    "rag_context_relevance",
    "rag_citations_per_response",
    # Metrics collector
    "QueryMetrics",
    "RAGMetricsCollector",
    "metrics_collector",
]
