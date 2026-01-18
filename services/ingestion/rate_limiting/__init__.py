"""Rate limiting module for ingestion service.

Provides per-tenant rate limiting to prevent noisy tenants from
starving others and ensure fair resource allocation.
"""

from rate_limiting.exceptions import RateLimitExceeded
from rate_limiting.limiter import IngestionRateLimiter
from rate_limiting.models import TenantLimits

__all__ = [
    "IngestionRateLimiter",
    "RateLimitExceeded",
    "TenantLimits",
]
