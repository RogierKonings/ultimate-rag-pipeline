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
from .degradation import (
    DegradationMode,
    DegradationStatus,
    RetrievalDegradationManager,
    get_degradation_manager,
    reset_degradation_manager,
)

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    # Configuration
    "CircuitBreakerConfig",
    "ResilienceConfig",
    # Degradation
    "DegradationMode",
    "DegradationStatus",
    "RetrievalDegradationManager",
    "get_degradation_manager",
    "reset_degradation_manager",
]
