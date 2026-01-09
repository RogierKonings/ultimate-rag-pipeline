"""Resilience module for graceful degradation.

This module provides resilience patterns for the Orchestrator Service:
- Circuit breaker for preventing cascading failures
- Fallback handlers for graceful degradation
- Degradation manager for system-wide health tracking

Example usage:
    from resilience import (
        CircuitBreaker,
        DegradationManager,
        FallbackHandlers,
    )

    # Create circuit breaker
    breaker = CircuitBreaker("llm_gateway")

    # Use with fallback
    result = await breaker.call(
        llm_service.generate,
        prompt,
        fallback=FallbackHandlers.llm_fallback
    )

    # Track system health
    manager = DegradationManager()
    manager.register_circuit("llm_gateway", critical=True)
    level = manager.degradation_level
"""

from .circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from .config import (
    CircuitBreakerConfig,
    FallbackConfig,
    ResilienceConfig,
)
from .degradation import (
    DegradationLevel,
    DegradationManager,
    get_degradation_manager,
    reset_degradation_manager,
)
from .fallbacks import (
    FallbackError,
    FallbackHandlers,
    create_fallback_response,
)

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    # Configuration
    "CircuitBreakerConfig",
    "FallbackConfig",
    "ResilienceConfig",
    # Degradation
    "DegradationLevel",
    "DegradationManager",
    "get_degradation_manager",
    "reset_degradation_manager",
    # Fallbacks
    "FallbackError",
    "FallbackHandlers",
    "create_fallback_response",
]
