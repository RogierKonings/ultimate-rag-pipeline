"""Configuration models for the resilience module.

This module defines configuration for:
- Circuit breaker settings (failure threshold, recovery timeout)
- Fallback behavior (cache fallback, default responses)
- Overall resilience settings
"""

from pydantic import BaseModel, Field


class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker behavior.

    The circuit breaker pattern prevents cascading failures by temporarily
    stopping calls to a failing service after a threshold of failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests are rejected immediately
    - HALF_OPEN: Testing recovery, limited requests allowed
    """

    failure_threshold: int = Field(
        default=5,
        ge=1,
        description="Number of failures before the circuit opens",
    )
    recovery_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Seconds to wait before attempting recovery (HALF_OPEN state)",
    )
    half_open_max_calls: int = Field(
        default=3,
        ge=1,
        description="Maximum calls allowed in HALF_OPEN state to test recovery",
    )


class FallbackConfig(BaseModel):
    """Configuration for fallback behavior when services fail.

    Fallbacks provide graceful degradation by returning cached or default
    responses when the primary service is unavailable.
    """

    enable_cache_fallback: bool = Field(
        default=True,
        description="Whether to attempt cached responses on failure",
    )
    enable_default_response: bool = Field(
        default=True,
        description="Whether to return default responses when cache is unavailable",
    )
    default_response: str = Field(
        default="I apologize, but I'm unable to process your request right now.",
        description="Default message to return when all fallbacks fail",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        description="Time-to-live for cached fallback responses in seconds",
    )


class ResilienceConfig(BaseModel):
    """Top-level configuration for the resilience module.

    Combines circuit breaker and fallback settings with additional
    resilience-related configuration.
    """

    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig,
        description="Circuit breaker configuration",
    )
    fallback: FallbackConfig = Field(
        default_factory=FallbackConfig,
        description="Fallback behavior configuration",
    )
    enable_metrics: bool = Field(
        default=True,
        description="Whether to emit resilience metrics",
    )
    log_failures: bool = Field(
        default=True,
        description="Whether to log individual failures",
    )
