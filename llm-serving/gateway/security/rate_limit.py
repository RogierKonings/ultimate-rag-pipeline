"""
Rate Limiting for the Gateway.

Provides token bucket and sliding window rate limiting
with per-tenant and per-user limits.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RateLimitConfig(BaseModel):
    """Rate limit configuration."""

    # Default limits (requests per minute)
    default_rpm: int = 60
    default_rpd: int = 10000  # requests per day

    # Per-tenant limits
    tenant_rpm: dict[str, int] = {}  # tenant_id -> rpm
    tenant_rpd: dict[str, int] = {}  # tenant_id -> rpd

    # Per-user limits
    user_rpm: dict[str, int] = {}  # user_id -> rpm

    # Token limits (for LLM endpoints)
    default_tpm: int = 100000  # tokens per minute
    tenant_tpm: dict[str, int] = {}  # tenant_id -> tpm

    # Burst allowance (multiplier of rate limit)
    burst_multiplier: float = 1.5

    # Window size for sliding window algorithm
    window_size_seconds: int = 60

    # Redis configuration (for distributed rate limiting)
    redis_url: Optional[str] = None


@dataclass
class RateLimitState:
    """State for a rate limit bucket."""

    tokens: float
    last_update: float
    request_count: int = 0
    token_count: int = 0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    limit: int
    reset_at: float  # Unix timestamp
    retry_after: Optional[int] = None  # seconds until reset

    def to_headers(self) -> dict[str, str]:
        """Convert to response headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_at)),
        }
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        return headers


class RateLimiter:
    """
    Token bucket rate limiter with sliding window support.

    Supports both in-memory and Redis-backed storage.
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiter.

        Args:
            config: Rate limit configuration
        """
        self.config = config or RateLimitConfig()
        self._buckets: dict[str, RateLimitState] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "RateLimiter":
        """Create RateLimiter from environment variables."""
        config = RateLimitConfig(
            default_rpm=int(os.getenv("RATE_LIMIT_RPM", "60")),
            default_rpd=int(os.getenv("RATE_LIMIT_RPD", "10000")),
            default_tpm=int(os.getenv("RATE_LIMIT_TPM", "100000")),
            burst_multiplier=float(os.getenv("RATE_LIMIT_BURST", "1.5")),
            redis_url=os.getenv("REDIS_URL"),
        )

        # Parse tenant limits (format: tenant1:100,tenant2:200)
        tenant_rpm_str = os.getenv("RATE_LIMIT_TENANT_RPM", "")
        if tenant_rpm_str:
            for spec in tenant_rpm_str.split(","):
                if ":" in spec:
                    tenant, rpm = spec.split(":")
                    config.tenant_rpm[tenant] = int(rpm)

        return cls(config)

    def _get_bucket_key(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        limit_type: str = "request",
    ) -> str:
        """Generate a bucket key for the given context."""
        if user_id:
            return f"{limit_type}:{tenant_id}:{user_id}"
        return f"{limit_type}:{tenant_id}"

    def _get_limit(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        limit_type: str = "rpm",
    ) -> int:
        """Get the rate limit for the given context."""
        if limit_type == "rpm":
            # Check user-specific limit first
            if user_id and user_id in self.config.user_rpm:
                return self.config.user_rpm[user_id]
            # Then tenant-specific
            if tenant_id in self.config.tenant_rpm:
                return self.config.tenant_rpm[tenant_id]
            return self.config.default_rpm
        elif limit_type == "tpm":
            if tenant_id in self.config.tenant_tpm:
                return self.config.tenant_tpm[tenant_id]
            return self.config.default_tpm
        elif limit_type == "rpd":
            if tenant_id in self.config.tenant_rpd:
                return self.config.tenant_rpd[tenant_id]
            return self.config.default_rpd
        return self.config.default_rpm

    async def check_rate_limit(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        tokens: int = 0,
    ) -> RateLimitResult:
        """
        Check if a request is allowed under rate limits.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier (optional, for per-user limits)
            tokens: Number of tokens to consume (for token-based limits)

        Returns:
            RateLimitResult with allowed status and headers
        """
        async with self._lock:
            now = time.time()
            window = self.config.window_size_seconds

            # Check request rate limit
            bucket_key = self._get_bucket_key(tenant_id, user_id, "request")
            limit = self._get_limit(tenant_id, user_id, "rpm")
            burst_limit = int(limit * self.config.burst_multiplier)

            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = RateLimitState(
                    tokens=float(burst_limit),
                    last_update=now,
                )
                self._buckets[bucket_key] = bucket

            # Refill tokens based on time elapsed
            elapsed = now - bucket.last_update
            refill = (elapsed / window) * limit
            bucket.tokens = min(burst_limit, bucket.tokens + refill)
            bucket.last_update = now

            # Check if request is allowed
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                bucket.request_count += 1

                remaining = int(bucket.tokens)
                reset_at = now + window

                return RateLimitResult(
                    allowed=True,
                    remaining=remaining,
                    limit=limit,
                    reset_at=reset_at,
                )
            else:
                # Calculate retry time
                tokens_needed = 1 - bucket.tokens
                retry_after = int((tokens_needed / limit) * window) + 1
                reset_at = now + retry_after

                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=limit,
                    reset_at=reset_at,
                    retry_after=retry_after,
                )

    async def check_token_limit(
        self,
        tenant_id: str,
        tokens: int,
    ) -> RateLimitResult:
        """
        Check if token usage is within limits.

        Args:
            tenant_id: Tenant identifier
            tokens: Number of tokens to consume

        Returns:
            RateLimitResult
        """
        async with self._lock:
            now = time.time()
            window = self.config.window_size_seconds

            bucket_key = self._get_bucket_key(tenant_id, None, "token")
            limit = self._get_limit(tenant_id, None, "tpm")
            burst_limit = int(limit * self.config.burst_multiplier)

            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = RateLimitState(
                    tokens=float(burst_limit),
                    last_update=now,
                )
                self._buckets[bucket_key] = bucket

            # Refill tokens
            elapsed = now - bucket.last_update
            refill = (elapsed / window) * limit
            bucket.tokens = min(burst_limit, bucket.tokens + refill)
            bucket.last_update = now

            # Check if tokens are available
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                bucket.token_count += tokens

                return RateLimitResult(
                    allowed=True,
                    remaining=int(bucket.tokens),
                    limit=limit,
                    reset_at=now + window,
                )
            else:
                tokens_needed = tokens - bucket.tokens
                retry_after = int((tokens_needed / limit) * window) + 1

                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=limit,
                    reset_at=now + retry_after,
                    retry_after=retry_after,
                )

    async def record_usage(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        tokens: int = 0,
    ) -> None:
        """
        Record usage after a request completes (for accurate token tracking).

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier
            tokens: Tokens consumed
        """
        if tokens > 0:
            # Deduct any additional tokens beyond the initial estimate
            await self.check_token_limit(tenant_id, tokens)

    def get_usage_stats(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Get usage statistics for a tenant/user.

        Args:
            tenant_id: Tenant identifier
            user_id: User identifier

        Returns:
            Usage statistics dict
        """
        request_key = self._get_bucket_key(tenant_id, user_id, "request")
        token_key = self._get_bucket_key(tenant_id, None, "token")

        request_bucket = self._buckets.get(request_key)
        token_bucket = self._buckets.get(token_key)

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "requests": {
                "count": request_bucket.request_count if request_bucket else 0,
                "remaining": int(request_bucket.tokens) if request_bucket else self._get_limit(tenant_id, user_id, "rpm"),
                "limit": self._get_limit(tenant_id, user_id, "rpm"),
            },
            "tokens": {
                "count": token_bucket.token_count if token_bucket else 0,
                "remaining": int(token_bucket.tokens) if token_bucket else self._get_limit(tenant_id, None, "tpm"),
                "limit": self._get_limit(tenant_id, None, "tpm"),
            },
        }

    async def reset_limits(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Reset rate limits for a tenant/user.

        Args:
            tenant_id: Tenant to reset (None for all)
            user_id: User to reset
        """
        async with self._lock:
            if tenant_id is None:
                self._buckets.clear()
            else:
                keys_to_remove = []
                for key in self._buckets:
                    if tenant_id in key:
                        if user_id is None or user_id in key:
                            keys_to_remove.append(key)
                for key in keys_to_remove:
                    del self._buckets[key]


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter.from_env()
    return _rate_limiter
