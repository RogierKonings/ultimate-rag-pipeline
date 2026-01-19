"""Answer cache metrics for the Orchestrator Service.

This module provides Prometheus metrics for tracking answer cache performance.

Reference: US-10.5.3 - Answer-Level Caching
"""

from prometheus_client import Counter, Gauge, Histogram

# =============================================================================
# Answer Cache Metrics
# =============================================================================

answer_cache_hit_total = Counter(
    "answer_cache_hit_total",
    "Total answer cache hits (responses served from cache)",
    ["tenant_id"],
)

answer_cache_miss_total = Counter(
    "answer_cache_miss_total",
    "Total answer cache misses",
    ["tenant_id"],
)

answer_cache_set_total = Counter(
    "answer_cache_set_total",
    "Total answer cache entries stored",
    ["tenant_id"],
)

answer_cache_invalidation_total = Counter(
    "answer_cache_invalidation_total",
    "Total answer cache invalidations",
    ["tenant_id", "reason"],  # reason: document_update, tenant_clear, ttl_expire
)

answer_cache_error_total = Counter(
    "answer_cache_error_total",
    "Total answer cache errors",
    ["operation"],  # operation: get, set, invalidate
)

# =============================================================================
# Performance Metrics
# =============================================================================

answer_cache_latency = Histogram(
    "answer_cache_latency_seconds",
    "Answer cache operation latency",
    ["operation", "result"],  # operation: get, set; result: hit, miss
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

answer_cache_hit_rate = Gauge(
    "answer_cache_hit_rate",
    "Current answer cache hit rate",
    ["tenant_id"],
)

# =============================================================================
# Cost Savings Metrics
# =============================================================================

answer_cache_llm_tokens_saved = Counter(
    "answer_cache_llm_tokens_saved_total",
    "Estimated LLM tokens saved by cache hits",
    ["tenant_id"],
)

answer_cache_cost_savings = Counter(
    "answer_cache_cost_savings_total",
    "Estimated cost savings from cache hits (in microdollars)",
    ["tenant_id"],
)


def record_cache_hit(tenant_id: str, latency_seconds: float) -> None:
    """Record a cache hit with metrics.

    Args:
        tenant_id: Tenant identifier.
        latency_seconds: Time taken to retrieve from cache.
    """
    answer_cache_hit_total.labels(tenant_id=tenant_id).inc()
    answer_cache_latency.labels(operation="get", result="hit").observe(latency_seconds)


def record_cache_miss(tenant_id: str, latency_seconds: float) -> None:
    """Record a cache miss with metrics.

    Args:
        tenant_id: Tenant identifier.
        latency_seconds: Time taken to check cache.
    """
    answer_cache_miss_total.labels(tenant_id=tenant_id).inc()
    answer_cache_latency.labels(operation="get", result="miss").observe(latency_seconds)


def record_cache_set(tenant_id: str, latency_seconds: float) -> None:
    """Record a cache set operation.

    Args:
        tenant_id: Tenant identifier.
        latency_seconds: Time taken to store in cache.
    """
    answer_cache_set_total.labels(tenant_id=tenant_id).inc()
    answer_cache_latency.labels(operation="set", result="success").observe(latency_seconds)


def record_cache_invalidation(tenant_id: str, reason: str, count: int = 1) -> None:
    """Record cache invalidation.

    Args:
        tenant_id: Tenant identifier.
        reason: Reason for invalidation.
        count: Number of entries invalidated.
    """
    answer_cache_invalidation_total.labels(tenant_id=tenant_id, reason=reason).inc(count)


def record_cache_error(operation: str) -> None:
    """Record a cache error.

    Args:
        operation: The operation that failed (get, set, invalidate).
    """
    answer_cache_error_total.labels(operation=operation).inc()


def update_hit_rate(tenant_id: str, hit_rate: float) -> None:
    """Update the cache hit rate gauge.

    Args:
        tenant_id: Tenant identifier.
        hit_rate: Current hit rate (0.0 to 1.0).
    """
    answer_cache_hit_rate.labels(tenant_id=tenant_id).set(hit_rate)


def record_cost_savings(
    tenant_id: str,
    tokens_saved: int,
    cost_microdollars: float,
) -> None:
    """Record estimated cost savings from cache hit.

    Args:
        tenant_id: Tenant identifier.
        tokens_saved: Estimated tokens that would have been used.
        cost_microdollars: Estimated cost saved in microdollars.
    """
    answer_cache_llm_tokens_saved.labels(tenant_id=tenant_id).inc(tokens_saved)
    answer_cache_cost_savings.labels(tenant_id=tenant_id).inc(cost_microdollars)
