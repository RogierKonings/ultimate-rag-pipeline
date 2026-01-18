"""LLM request metrics for model tiering observability.

This module provides Prometheus metrics for tracking LLM requests by model,
enabling cost monitoring and optimization analysis.

Reference: US-10.5.2 - LLM Model Tiering
"""

from prometheus_client import Counter, Histogram

# Total LLM requests by model and tier
# Labels allow filtering by model, tier, and tenant_tier for cost analysis
llm_requests_by_model = Counter(
    "orchestrator_llm_requests_total",
    "Total LLM requests by model and tier",
    ["model", "tier", "tenant_tier"],
)

# LLM request latency by model tier
llm_request_duration = Histogram(
    "orchestrator_llm_request_duration_seconds",
    "LLM request duration in seconds by tier",
    ["tier"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# Model fallback counter
llm_model_fallbacks = Counter(
    "orchestrator_llm_model_fallbacks_total",
    "Total model fallbacks when primary model fails",
    ["failed_model", "fallback_model"],
)


def record_llm_request(model: str, tier: str, tenant_tier: str) -> None:
    """Record an LLM request metric.

    Args:
        model: The model name used.
        tier: The model tier (small, medium, large).
        tenant_tier: The tenant tier (basic, standard, premium).
    """
    llm_requests_by_model.labels(
        model=model,
        tier=tier,
        tenant_tier=tenant_tier,
    ).inc()


def record_llm_duration(tier: str, duration_seconds: float) -> None:
    """Record LLM request duration.

    Args:
        tier: The model tier.
        duration_seconds: Request duration in seconds.
    """
    llm_request_duration.labels(tier=tier).observe(duration_seconds)


def record_model_fallback(failed_model: str, fallback_model: str) -> None:
    """Record a model fallback event.

    Args:
        failed_model: The model that failed.
        fallback_model: The model used as fallback.
    """
    llm_model_fallbacks.labels(
        failed_model=failed_model,
        fallback_model=fallback_model,
    ).inc()
