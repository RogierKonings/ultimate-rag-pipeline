"""Prometheus metrics for rate limiting.

Exposes metrics for monitoring rate limiting behavior across tenants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge

if TYPE_CHECKING:
    from rate_limiting.limiter import IngestionRateLimiter

# Gauge for current active jobs per tenant
ingestion_active_jobs = Gauge(
    "ingestion_active_jobs",
    "Number of active ingestion jobs",
    ["tenant_id"],
)

# Gauge for queued jobs per tenant
ingestion_queued_jobs = Gauge(
    "ingestion_queued_jobs",
    "Number of queued ingestion jobs waiting for slots",
    ["tenant_id"],
)

# Counter for rate limited events
ingestion_rate_limited_total = Counter(
    "ingestion_rate_limited_total",
    "Total jobs that hit rate limit",
    ["tenant_id", "action"],  # action: "queued" or "rejected"
)


def record_rate_limit_hit(tenant_id: str, action: str) -> None:
    """Record a rate limit event.

    Args:
        tenant_id: The tenant that hit the limit.
        action: Either "queued" (soft limit) or "rejected" (hard limit).
    """
    ingestion_rate_limited_total.labels(
        tenant_id=tenant_id,
        action=action,
    ).inc()


def update_tenant_gauges(tenant_id: str, active: int, queued: int) -> None:
    """Update gauge metrics for a tenant.

    Args:
        tenant_id: The tenant ID.
        active: Number of active jobs.
        queued: Number of queued jobs.
    """
    ingestion_active_jobs.labels(tenant_id=tenant_id).set(active)
    ingestion_queued_jobs.labels(tenant_id=tenant_id).set(queued)


async def update_all_metrics(rate_limiter: IngestionRateLimiter) -> None:
    """Update Prometheus metrics from rate limiter state.

    This can be called periodically to sync metrics with Redis state.

    Args:
        rate_limiter: The rate limiter instance.
    """
    tenants = await rate_limiter.get_all_active_tenants()

    for tenant_id in tenants:
        active = await rate_limiter.get_active_count(tenant_id)
        queued = await rate_limiter.get_queued_count(tenant_id)
        update_tenant_gauges(tenant_id, active, queued)
