"""Resilience module for retrieval service graceful degradation.

This module provides:
- Circuit breakers for Qdrant, OpenSearch, and Reranker
- Degradation modes for automatic fallback behavior
- Metrics for observability
"""

from .circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from .config import (
    CircuitBreakerConfig,
    ResilienceConfig,
)

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "CircuitBreakerConfig",
    "ResilienceConfig",
]
