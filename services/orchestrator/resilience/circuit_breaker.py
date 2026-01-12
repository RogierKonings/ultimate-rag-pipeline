"""Circuit breaker implementation for graceful degradation.

The circuit breaker pattern prevents cascading failures by:
1. Tracking failures for each protected service/endpoint
2. Opening the circuit (rejecting requests) after failure threshold
3. Testing recovery with limited requests after timeout
4. Resuming normal operation on successful recovery

States:
- CLOSED: Normal operation, all requests pass through
- OPEN: Service failing, requests rejected immediately
- HALF_OPEN: Testing recovery, limited requests allowed
"""

import asyncio
import logging
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

from .config import CircuitBreakerConfig

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is rejected."""

    def __init__(self, name: str, time_until_recovery: float):
        self.name = name
        self.time_until_recovery = time_until_recovery
        super().__init__(
            f"Circuit '{name}' is open. Retry in {time_until_recovery:.1f} seconds.",
        )


T = TypeVar("T")


class CircuitBreaker:
    """Circuit breaker for protecting calls to external services.

    Usage:
        breaker = CircuitBreaker("llm_gateway")

        # With fallback
        result = await breaker.call(
            async_function,
            arg1, arg2,
            fallback=fallback_function
        )

        # Without fallback (raises on open circuit)
        result = await breaker.call(async_function, arg1, arg2)
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit (e.g., "llm_gateway", "retrieval")
            config: Circuit breaker configuration, uses defaults if not provided
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        # State tracking
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0

        # Thread safety
        self._lock = asyncio.Lock()

        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._total_rejections = 0

    async def call(
        self,
        func: Callable[..., T],
        *args: Any,
        fallback: Callable[..., T] | None = None,
        **kwargs: Any,
    ) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            fallback: Optional fallback function to call on failure
            **kwargs: Keyword arguments for func

        Returns:
            Result from func or fallback

        Raises:
            CircuitOpenError: If circuit is open and no fallback provided
            Exception: Original exception if no fallback and circuit allows call
        """
        async with self._lock:
            self._check_state_transition()

            if self._state == CircuitState.OPEN:
                self._total_rejections += 1
                time_until_recovery = self._time_until_recovery()

                if fallback:
                    logger.warning(
                        "Circuit '%s' is open, using fallback",
                        self.name,
                        extra={
                            "circuit_name": self.name,
                            "time_until_recovery": time_until_recovery,
                        },
                    )
                    return await self._execute_fallback(fallback, *args, **kwargs)

                raise CircuitOpenError(self.name, time_until_recovery)

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    if fallback:
                        return await self._execute_fallback(fallback, *args, **kwargs)
                    raise CircuitOpenError(self.name, self._time_until_recovery())
                self._half_open_calls += 1

            self._total_calls += 1

        # Execute outside lock to avoid blocking other calls
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(e)
            if fallback:
                logger.warning(
                    "Call through circuit '%s' failed, using fallback: %s",
                    self.name,
                    str(e),
                    extra={"circuit_name": self.name, "error": str(e)},
                )
                return await self._execute_fallback(fallback, *args, **kwargs)
            raise

    async def _execute_fallback(
        self,
        fallback: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute fallback function."""
        if asyncio.iscoroutinefunction(fallback):
            return await fallback(*args, **kwargs)
        return fallback(*args, **kwargs)

    def record_success(self) -> None:
        """Record a successful call.

        In HALF_OPEN state, success resets the circuit to CLOSED.
        In CLOSED state, success resets the failure count.
        """
        self._success_count += 1
        self._total_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            # Recovery successful, close circuit
            logger.info(
                "Circuit '%s' recovered, closing circuit",
                self.name,
                extra={"circuit_name": self.name},
            )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success in normal operation
            self._failure_count = 0

    def record_failure(self, error: Exception) -> None:
        """Record a failed call.

        May transition circuit to OPEN state if failure threshold is reached.

        Args:
            error: The exception that caused the failure
        """
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Failed during recovery test, reopen circuit
            logger.warning(
                "Circuit '%s' recovery failed, reopening circuit",
                self.name,
                extra={"circuit_name": self.name, "error": str(error)},
            )
            self._state = CircuitState.OPEN
            self._half_open_calls = 0
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                logger.warning(
                    "Circuit '%s' opened after %d failures",
                    self.name,
                    self._failure_count,
                    extra={
                        "circuit_name": self.name,
                        "failure_count": self._failure_count,
                        "error": str(error),
                    },
                )
                self._state = CircuitState.OPEN

    def _check_state_transition(self) -> None:
        """Check if circuit should transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                logger.info(
                    "Circuit '%s' entering half-open state for recovery test",
                    self.name,
                    extra={
                        "circuit_name": self.name,
                        "elapsed_seconds": elapsed,
                    },
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0

    def _time_until_recovery(self) -> float:
        """Calculate time until circuit transitions to HALF_OPEN."""
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        remaining = self.config.recovery_timeout - elapsed
        return max(0.0, remaining)

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        # Check for state transition before returning
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        """Current consecutive failure count."""
        return self._failure_count

    @property
    def is_healthy(self) -> bool:
        """Whether the circuit is in a healthy state (CLOSED)."""
        return self.state == CircuitState.CLOSED

    def get_metrics(self) -> dict:
        """Get circuit breaker metrics.

        Returns:
            Dictionary with circuit metrics
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "total_rejections": self._total_rejections,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_max_calls": self.config.half_open_max_calls,
            },
        }

    def reset(self) -> None:
        """Reset circuit breaker to initial state.

        Useful for testing or manual recovery.
        """
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        logger.info(
            "Circuit '%s' manually reset",
            self.name,
            extra={"circuit_name": self.name},
        )
