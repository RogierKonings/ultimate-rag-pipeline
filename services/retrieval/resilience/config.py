"""Configuration models for the resilience module."""

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


class ResilienceConfig(BaseModel):
    """Top-level configuration for the resilience module."""

    qdrant_circuit: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig,
        description="Circuit breaker config for Qdrant",
    )
    opensearch_circuit: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig,
        description="Circuit breaker config for OpenSearch",
    )
    reranker_circuit: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig,
        description="Circuit breaker config for Reranker",
    )
    enable_metrics: bool = Field(
        default=True,
        description="Whether to emit resilience metrics",
    )
