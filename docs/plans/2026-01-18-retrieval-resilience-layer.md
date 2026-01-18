# Retrieval Service Resilience Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add circuit breakers and degradation modes to the retrieval service for graceful degradation when backends become unhealthy.

**Architecture:** Copy the circuit breaker and degradation manager from orchestrator service to retrieval service. Create a retrieval-specific `RetrievalDegradationManager` that maps circuit states to search modes (HYBRID_FULL, SEMANTIC_ONLY, KEYWORD_ONLY, etc.). Wrap the existing `HybridSearcher` with a `ResilientHybridSearcher` that uses circuits and degrades gracefully.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, asyncio, prometheus-client

**Reference Spec:** `workflow/refined/10-architectural-improvements/US-10.2.1-retrieval-service-resilience-layer.md`

---

## Task 1: Copy Circuit Breaker Infrastructure from Orchestrator

**Files:**
- Create: `services/retrieval/resilience/__init__.py`
- Create: `services/retrieval/resilience/config.py`
- Create: `services/retrieval/resilience/circuit_breaker.py`

**Step 1: Create the resilience directory and config**

```bash
mkdir -p services/retrieval/resilience
```

**Step 2: Create config.py (copy from orchestrator)**

Create `services/retrieval/resilience/config.py`:

```python
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
```

**Step 3: Create circuit_breaker.py (copy from orchestrator)**

Create `services/retrieval/resilience/circuit_breaker.py`:

```python
"""Circuit breaker pattern implementation for retrieval backends."""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, TypeVar

from .config import CircuitBreakerConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and no fallback provided."""

    def __init__(self, circuit_name: str, time_until_recovery: float):
        self.circuit_name = circuit_name
        self.time_until_recovery = time_until_recovery
        super().__init__(
            f"Circuit '{circuit_name}' is open. Recovery in {time_until_recovery:.1f}s"
        )


class CircuitBreaker:
    """Circuit breaker for protecting calls to external services."""

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit (e.g., "qdrant", "opensearch")
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
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e)
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

    def _record_success(self) -> None:
        """Record a successful call."""
        self._success_count += 1
        self._total_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "Circuit '%s' recovered, closing circuit",
                self.name,
                extra={"circuit_name": self.name},
            )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
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
        """Get circuit breaker metrics."""
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
        """Reset circuit breaker to initial state."""
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
```

**Step 4: Create __init__.py**

Create `services/retrieval/resilience/__init__.py`:

```python
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
```

**Step 5: Commit**

```bash
git add services/retrieval/resilience/
git commit -m "feat(retrieval): add circuit breaker infrastructure

Copy circuit breaker pattern from orchestrator service with:
- CircuitBreaker class with CLOSED/OPEN/HALF_OPEN states
- CircuitBreakerConfig for configurable thresholds
- ResilienceConfig for retrieval-specific circuit configs"
```

---

## Task 2: Create Retrieval Degradation Manager

**Files:**
- Create: `services/retrieval/resilience/degradation.py`
- Modify: `services/retrieval/resilience/__init__.py`

**Step 1: Create degradation.py with retrieval-specific modes**

Create `services/retrieval/resilience/degradation.py`:

```python
"""Degradation manager for retrieval service.

Manages degradation modes based on circuit breaker states, enabling
graceful degradation when backends become unhealthy.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from .circuit_breaker import CircuitBreaker, CircuitState
from .config import CircuitBreakerConfig, ResilienceConfig

logger = logging.getLogger(__name__)


class DegradationMode(str, Enum):
    """Retrieval service degradation modes."""

    HYBRID_FULL = "hybrid_full"  # All components healthy
    SEMANTIC_ONLY = "semantic_only"  # OpenSearch down, use Qdrant only
    KEYWORD_ONLY = "keyword_only"  # Qdrant down, use OpenSearch only
    HYBRID_NO_RERANK = "hybrid_no_rerank"  # Reranker down, skip reranking
    MINIMAL = "minimal"  # Multiple failures, best effort


@dataclass
class DegradationStatus:
    """Current degradation status with details."""

    mode: DegradationMode
    qdrant_healthy: bool
    opensearch_healthy: bool
    reranker_healthy: bool
    components_available: list[str] = field(default_factory=list)
    components_unavailable: list[str] = field(default_factory=list)


class RetrievalDegradationManager:
    """Manages degradation modes based on circuit breaker states.

    Determines which retrieval mode to use based on health of
    backend components (Qdrant, OpenSearch, Reranker).
    """

    def __init__(self, config: ResilienceConfig | None = None):
        """Initialize degradation manager.

        Args:
            config: Resilience configuration for circuit breakers
        """
        self.config = config or ResilienceConfig()

        # Create circuit breakers for each backend
        self.qdrant_breaker = CircuitBreaker("qdrant", self.config.qdrant_circuit)
        self.opensearch_breaker = CircuitBreaker(
            "opensearch", self.config.opensearch_circuit
        )
        self.reranker_breaker = CircuitBreaker("reranker", self.config.reranker_circuit)

    def get_current_mode(self) -> DegradationMode:
        """Determine current degradation mode from circuit states."""
        qdrant_ok = self.qdrant_breaker.state != CircuitState.OPEN
        opensearch_ok = self.opensearch_breaker.state != CircuitState.OPEN
        reranker_ok = self.reranker_breaker.state != CircuitState.OPEN

        if qdrant_ok and opensearch_ok and reranker_ok:
            return DegradationMode.HYBRID_FULL

        if not qdrant_ok and not opensearch_ok:
            return DegradationMode.MINIMAL

        if not qdrant_ok:
            return DegradationMode.KEYWORD_ONLY

        if not opensearch_ok:
            return DegradationMode.SEMANTIC_ONLY

        if not reranker_ok:
            return DegradationMode.HYBRID_NO_RERANK

        return DegradationMode.HYBRID_FULL

    def get_status(self) -> DegradationStatus:
        """Get detailed degradation status."""
        mode = self.get_current_mode()

        qdrant_healthy = self.qdrant_breaker.state != CircuitState.OPEN
        opensearch_healthy = self.opensearch_breaker.state != CircuitState.OPEN
        reranker_healthy = self.reranker_breaker.state != CircuitState.OPEN

        available = []
        unavailable = []

        if qdrant_healthy:
            available.append("qdrant")
        else:
            unavailable.append("qdrant")

        if opensearch_healthy:
            available.append("opensearch")
        else:
            unavailable.append("opensearch")

        if reranker_healthy:
            available.append("reranker")
        else:
            unavailable.append("reranker")

        return DegradationStatus(
            mode=mode,
            qdrant_healthy=qdrant_healthy,
            opensearch_healthy=opensearch_healthy,
            reranker_healthy=reranker_healthy,
            components_available=available,
            components_unavailable=unavailable,
        )

    def should_use_semantic(self) -> bool:
        """Check if semantic search should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.SEMANTIC_ONLY,
            DegradationMode.HYBRID_NO_RERANK,
        )

    def should_use_keyword(self) -> bool:
        """Check if keyword search should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.KEYWORD_ONLY,
            DegradationMode.HYBRID_NO_RERANK,
        )

    def should_use_reranker(self) -> bool:
        """Check if reranker should be used."""
        mode = self.get_current_mode()
        return mode in (
            DegradationMode.HYBRID_FULL,
            DegradationMode.SEMANTIC_ONLY,
            DegradationMode.KEYWORD_ONLY,
        )

    def get_circuit_statuses(self) -> dict:
        """Get status of all circuit breakers."""
        return {
            "qdrant": self.qdrant_breaker.get_metrics(),
            "opensearch": self.opensearch_breaker.get_metrics(),
            "reranker": self.reranker_breaker.get_metrics(),
        }

    def reset_all(self) -> None:
        """Reset all circuit breakers to closed state."""
        self.qdrant_breaker.reset()
        self.opensearch_breaker.reset()
        self.reranker_breaker.reset()
        logger.info("All circuit breakers reset")


# Module-level singleton
_manager: RetrievalDegradationManager | None = None


def get_degradation_manager() -> RetrievalDegradationManager:
    """Get or create the singleton degradation manager."""
    global _manager
    if _manager is None:
        _manager = RetrievalDegradationManager()
    return _manager


def reset_degradation_manager() -> None:
    """Reset the singleton degradation manager (for testing)."""
    global _manager
    _manager = None
```

**Step 2: Update __init__.py to export degradation classes**

Modify `services/retrieval/resilience/__init__.py`:

```python
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
```

**Step 3: Commit**

```bash
git add services/retrieval/resilience/
git commit -m "feat(retrieval): add degradation manager with retrieval modes

Add RetrievalDegradationManager that:
- Manages circuit breakers for qdrant, opensearch, reranker
- Calculates degradation mode (HYBRID_FULL, SEMANTIC_ONLY, etc.)
- Provides helper methods for search decisions
- Exposes circuit breaker status for health checks"
```

---

## Task 3: Add Unit Tests for Circuit Breaker

**Files:**
- Create: `services/retrieval/tests/resilience/__init__.py`
- Create: `services/retrieval/tests/resilience/test_circuit_breaker.py`

**Step 1: Create test directory**

```bash
mkdir -p services/retrieval/tests/resilience
touch services/retrieval/tests/resilience/__init__.py
```

**Step 2: Write circuit breaker tests**

Create `services/retrieval/tests/resilience/test_circuit_breaker.py`:

```python
"""Tests for circuit breaker implementation."""

import asyncio

import pytest

from resilience import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError, CircuitState


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    @pytest.fixture
    def breaker(self) -> CircuitBreaker:
        """Create a circuit breaker with low thresholds for testing."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms for fast tests
            half_open_max_calls=2,
        )
        return CircuitBreaker("test", config)

    async def test_starts_closed(self, breaker: CircuitBreaker) -> None:
        """Circuit should start in CLOSED state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_healthy is True

    async def test_successful_call_stays_closed(self, breaker: CircuitBreaker) -> None:
        """Successful calls should keep circuit closed."""

        async def success() -> str:
            return "ok"

        result = await breaker.call(success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    async def test_opens_after_threshold_failures(
        self, breaker: CircuitBreaker
    ) -> None:
        """Circuit should open after failure threshold is reached."""

        async def failing() -> None:
            raise ConnectionError("failed")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(failing)

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_healthy is False

    async def test_rejects_calls_when_open(self, breaker: CircuitBreaker) -> None:
        """Open circuit should reject calls without fallback."""
        # Force circuit open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time()

        async def func() -> str:
            return "should not run"

        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.call(func)

        assert "test" in str(exc_info.value)

    async def test_uses_fallback_when_open(self, breaker: CircuitBreaker) -> None:
        """Open circuit should use fallback if provided."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time()

        async def func() -> str:
            return "primary"

        async def fallback() -> str:
            return "fallback"

        result = await breaker.call(func, fallback=fallback)
        assert result == "fallback"

    async def test_transitions_to_half_open_after_timeout(
        self, breaker: CircuitBreaker
    ) -> None:
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = asyncio.get_event_loop().time() - 1.0  # 1s ago

        # State property should reflect HALF_OPEN
        assert breaker.state == CircuitState.HALF_OPEN

    async def test_closes_after_success_in_half_open(
        self, breaker: CircuitBreaker
    ) -> None:
        """Successful call in HALF_OPEN should close circuit."""
        breaker._state = CircuitState.HALF_OPEN

        async def success() -> str:
            return "ok"

        await breaker.call(success)
        assert breaker.state == CircuitState.CLOSED

    async def test_reopens_on_failure_in_half_open(
        self, breaker: CircuitBreaker
    ) -> None:
        """Failed call in HALF_OPEN should reopen circuit."""
        breaker._state = CircuitState.HALF_OPEN

        async def failing() -> None:
            raise ConnectionError("still failing")

        with pytest.raises(ConnectionError):
            await breaker.call(failing)

        assert breaker.state == CircuitState.OPEN

    async def test_uses_fallback_on_failure(self, breaker: CircuitBreaker) -> None:
        """Should use fallback when primary call fails."""

        async def failing() -> str:
            raise ConnectionError("failed")

        async def fallback() -> str:
            return "fallback"

        result = await breaker.call(failing, fallback=fallback)
        assert result == "fallback"

    async def test_reset_clears_state(self, breaker: CircuitBreaker) -> None:
        """Reset should return circuit to initial state."""
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    async def test_get_metrics(self, breaker: CircuitBreaker) -> None:
        """Should return comprehensive metrics."""
        metrics = breaker.get_metrics()

        assert metrics["name"] == "test"
        assert metrics["state"] == "closed"
        assert "failure_count" in metrics
        assert "total_calls" in metrics
        assert "config" in metrics
```

**Step 3: Run tests to verify they pass**

```bash
cd services/retrieval && pytest tests/resilience/test_circuit_breaker.py -v
```

Expected: All tests PASS

**Step 4: Commit**

```bash
git add services/retrieval/tests/resilience/
git commit -m "test(retrieval): add circuit breaker unit tests

Test coverage for:
- State transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure threshold behavior
- Fallback execution
- Reset functionality
- Metrics reporting"
```

---

## Task 4: Add Unit Tests for Degradation Manager

**Files:**
- Create: `services/retrieval/tests/resilience/test_degradation.py`

**Step 1: Write degradation manager tests**

Create `services/retrieval/tests/resilience/test_degradation.py`:

```python
"""Tests for degradation manager."""

import pytest

from resilience import (
    CircuitState,
    DegradationMode,
    RetrievalDegradationManager,
    ResilienceConfig,
    reset_degradation_manager,
)


class TestRetrievalDegradationManager:
    """Tests for RetrievalDegradationManager class."""

    @pytest.fixture
    def manager(self) -> RetrievalDegradationManager:
        """Create a fresh degradation manager."""
        reset_degradation_manager()
        return RetrievalDegradationManager()

    def test_all_healthy_returns_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """All circuits closed should return HYBRID_FULL mode."""
        assert manager.get_current_mode() == DegradationMode.HYBRID_FULL

    def test_qdrant_down_returns_keyword_only(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Qdrant circuit open should return KEYWORD_ONLY mode."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.KEYWORD_ONLY

    def test_opensearch_down_returns_semantic_only(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """OpenSearch circuit open should return SEMANTIC_ONLY mode."""
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.SEMANTIC_ONLY

    def test_reranker_down_returns_hybrid_no_rerank(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Reranker circuit open should return HYBRID_NO_RERANK mode."""
        manager.reranker_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.HYBRID_NO_RERANK

    def test_both_search_backends_down_returns_minimal(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Both Qdrant and OpenSearch down should return MINIMAL mode."""
        manager.qdrant_breaker._state = CircuitState.OPEN
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.get_current_mode() == DegradationMode.MINIMAL

    def test_should_use_semantic_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use semantic search in HYBRID_FULL mode."""
        assert manager.should_use_semantic() is True

    def test_should_not_use_semantic_when_qdrant_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use semantic search when Qdrant is down."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        assert manager.should_use_semantic() is False

    def test_should_use_keyword_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use keyword search in HYBRID_FULL mode."""
        assert manager.should_use_keyword() is True

    def test_should_not_use_keyword_when_opensearch_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use keyword search when OpenSearch is down."""
        manager.opensearch_breaker._state = CircuitState.OPEN

        assert manager.should_use_keyword() is False

    def test_should_use_reranker_in_hybrid_full(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should use reranker in HYBRID_FULL mode."""
        assert manager.should_use_reranker() is True

    def test_should_not_use_reranker_when_reranker_down(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """Should not use reranker when reranker is down."""
        manager.reranker_breaker._state = CircuitState.OPEN

        assert manager.should_use_reranker() is False

    def test_get_status_returns_complete_info(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_status should return complete degradation info."""
        status = manager.get_status()

        assert status.mode == DegradationMode.HYBRID_FULL
        assert status.qdrant_healthy is True
        assert status.opensearch_healthy is True
        assert status.reranker_healthy is True
        assert "qdrant" in status.components_available
        assert len(status.components_unavailable) == 0

    def test_get_status_with_failure(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_status should reflect component failures."""
        manager.qdrant_breaker._state = CircuitState.OPEN

        status = manager.get_status()

        assert status.mode == DegradationMode.KEYWORD_ONLY
        assert status.qdrant_healthy is False
        assert "qdrant" in status.components_unavailable
        assert "opensearch" in status.components_available

    def test_reset_all_clears_circuits(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """reset_all should reset all circuit breakers."""
        manager.qdrant_breaker._state = CircuitState.OPEN
        manager.opensearch_breaker._state = CircuitState.OPEN

        manager.reset_all()

        assert manager.qdrant_breaker.state == CircuitState.CLOSED
        assert manager.opensearch_breaker.state == CircuitState.CLOSED
        assert manager.get_current_mode() == DegradationMode.HYBRID_FULL

    def test_get_circuit_statuses(
        self, manager: RetrievalDegradationManager
    ) -> None:
        """get_circuit_statuses should return all circuit metrics."""
        statuses = manager.get_circuit_statuses()

        assert "qdrant" in statuses
        assert "opensearch" in statuses
        assert "reranker" in statuses
        assert statuses["qdrant"]["state"] == "closed"
```

**Step 2: Run tests to verify they pass**

```bash
cd services/retrieval && pytest tests/resilience/test_degradation.py -v
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add services/retrieval/tests/resilience/
git commit -m "test(retrieval): add degradation manager unit tests

Test coverage for:
- Mode selection based on circuit states
- Helper methods (should_use_semantic, etc.)
- Status reporting
- Reset functionality"
```

---

## Task 5: Create ResilientHybridSearcher

**Files:**
- Create: `services/retrieval/search/resilient_hybrid.py`
- Modify: `services/retrieval/search/__init__.py`

**Step 1: Create resilient_hybrid.py**

Create `services/retrieval/search/resilient_hybrid.py`:

```python
"""Resilient hybrid searcher with circuit breaker protection."""

import asyncio
import logging
import time

from ..resilience import (
    DegradationMode,
    RetrievalDegradationManager,
)
from .fusion import FusionMethod
from .hybrid import HybridSearcher
from .models import FusedResult, HybridSearchConfig, HybridSearchResponse

logger = logging.getLogger(__name__)


class ResilientHybridSearcher:
    """Hybrid searcher with resilience and degradation support.

    Wraps HybridSearcher with circuit breaker protection and automatically
    degrades to available components when backends fail.
    """

    def __init__(
        self,
        hybrid_searcher: HybridSearcher,
        degradation_manager: RetrievalDegradationManager,
    ):
        """Initialize resilient hybrid searcher.

        Args:
            hybrid_searcher: The underlying hybrid searcher
            degradation_manager: Manager for circuit breakers and degradation
        """
        self.hybrid = hybrid_searcher
        self.degradation = degradation_manager

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int | None = None,
        filters: dict | None = None,
        config: HybridSearchConfig | None = None,
        use_reranker: bool = True,
    ) -> HybridSearchResponse:
        """Execute hybrid search with degradation handling.

        Automatically uses available components based on circuit states.

        Args:
            query: Text query for keyword search
            query_embedding: Query embedding for semantic search
            top_k: Number of final results
            filters: ACL and metadata filters
            config: Override default hybrid config
            use_reranker: Whether to use reranker (if available)

        Returns:
            HybridSearchResponse with results and degradation info
        """
        start_time = time.time()
        mode = self.degradation.get_current_mode()
        status = self.degradation.get_status()

        logger.info(
            "search_starting",
            extra={
                "degradation_mode": mode.value,
                "components_available": status.components_available,
            },
        )

        cfg = config or self.hybrid.config
        final_top_k = top_k or cfg.top_k

        # Handle MINIMAL mode - return empty results
        if mode == DegradationMode.MINIMAL:
            logger.warning("both_search_backends_down", extra={"mode": mode.value})
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=(time.time() - start_time) * 1000,
                fusion_method=cfg.fusion_method,
                degradation_mode=mode,
                components_used=status.components_available,
                components_skipped=status.components_unavailable,
            )

        # Execute search based on degradation mode
        if mode == DegradationMode.SEMANTIC_ONLY:
            response = await self._search_semantic_with_circuit(
                query_embedding, final_top_k, filters
            )
        elif mode == DegradationMode.KEYWORD_ONLY:
            response = await self._search_keyword_with_circuit(
                query, final_top_k, filters
            )
        else:
            # HYBRID_FULL or HYBRID_NO_RERANK - run both searches
            response = await self._search_hybrid_with_circuits(
                query, query_embedding, final_top_k, filters, cfg
            )

        # Add degradation metadata to response
        search_time = (time.time() - start_time) * 1000

        return HybridSearchResponse(
            results=response.results,
            total_semantic=response.total_semantic,
            total_keyword=response.total_keyword,
            search_time_ms=search_time,
            fusion_method=response.fusion_method,
            degradation_mode=mode,
            components_used=status.components_available,
            components_skipped=status.components_unavailable,
        )

    async def _search_semantic_with_circuit(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
    ) -> HybridSearchResponse:
        """Execute semantic-only search with circuit breaker."""

        async def do_search() -> HybridSearchResponse:
            return await self.hybrid.search_semantic_only(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=filters,
            )

        async def fallback() -> HybridSearchResponse:
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=0,
                fusion_method=FusionMethod.RRF,
            )

        return await self.degradation.qdrant_breaker.call(do_search, fallback=fallback)

    async def _search_keyword_with_circuit(
        self,
        query: str,
        top_k: int,
        filters: dict | None,
    ) -> HybridSearchResponse:
        """Execute keyword-only search with circuit breaker."""

        async def do_search() -> HybridSearchResponse:
            return await self.hybrid.search_keyword_only(
                query=query,
                top_k=top_k,
                filters=filters,
            )

        async def fallback() -> HybridSearchResponse:
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=0,
                fusion_method=FusionMethod.RRF,
            )

        return await self.degradation.opensearch_breaker.call(
            do_search, fallback=fallback
        )

    async def _search_hybrid_with_circuits(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
        config: HybridSearchConfig,
    ) -> HybridSearchResponse:
        """Execute full hybrid search with circuit breakers on both backends."""

        async def do_semantic() -> list[FusedResult]:
            response = await self.hybrid.semantic.search(
                query_embedding=query_embedding,
                top_k=config.semantic_top_k,
                filters=filters,
            )
            # Convert to FusedResult format
            return [
                FusedResult(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    content=r.content,
                    fused_score=r.score,
                    semantic_score=r.score,
                    semantic_rank=i + 1,
                    metadata=r.metadata,
                    title=r.title,
                    source=r.source,
                )
                for i, r in enumerate(response.results)
            ]

        async def do_keyword() -> list[FusedResult]:
            response = await self.hybrid.keyword.search(
                query=query,
                top_k=config.keyword_top_k,
                filters=filters,
            )
            return [
                FusedResult(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    content=r.content,
                    fused_score=r.score,
                    keyword_score=r.score,
                    keyword_rank=i + 1,
                    metadata=r.metadata,
                    title=r.title,
                    source=r.source,
                )
                for i, r in enumerate(response.results)
            ]

        async def empty_fallback() -> list[FusedResult]:
            return []

        # Run both with circuit breakers
        semantic_task = self.degradation.qdrant_breaker.call(
            do_semantic, fallback=empty_fallback
        )
        keyword_task = self.degradation.opensearch_breaker.call(
            do_keyword, fallback=empty_fallback
        )

        semantic_results, keyword_results = await asyncio.gather(
            semantic_task, keyword_task
        )

        # Fuse results
        if semantic_results and keyword_results:
            fused = self.hybrid._fusion.fuse(
                semantic_results=semantic_results,
                keyword_results=keyword_results,
                top_k=top_k,
            )
        else:
            fused = semantic_results or keyword_results

        return HybridSearchResponse(
            results=fused[:top_k],
            total_semantic=len(semantic_results),
            total_keyword=len(keyword_results),
            search_time_ms=0,  # Will be set by caller
            fusion_method=config.fusion_method,
        )

    async def connect(self) -> None:
        """Connect to search backends."""
        await self.hybrid.connect()

    async def close(self) -> None:
        """Close connections to search backends."""
        await self.hybrid.close()

    async def health_check(self) -> bool:
        """Check health of search backends."""
        return await self.hybrid.health_check()
```

**Step 2: Update HybridSearchResponse model to include degradation info**

First check the current models file and add degradation fields:

Modify `services/retrieval/search/models.py` - add these fields to `HybridSearchResponse`:

```python
# Add to HybridSearchResponse class (after existing fields):
    degradation_mode: DegradationMode | None = None
    components_used: list[str] = Field(default_factory=list)
    components_skipped: list[str] = Field(default_factory=list)
```

**Step 3: Update search/__init__.py to export ResilientHybridSearcher**

Add to `services/retrieval/search/__init__.py`:

```python
from .resilient_hybrid import ResilientHybridSearcher
```

And add `"ResilientHybridSearcher"` to `__all__`.

**Step 4: Commit**

```bash
git add services/retrieval/search/
git commit -m "feat(retrieval): add ResilientHybridSearcher with circuit protection

ResilientHybridSearcher wraps HybridSearcher with:
- Circuit breaker protection for each backend
- Automatic degradation based on DegradationManager
- Fallback to available search methods
- Degradation metadata in response"
```

---

## Task 6: Update Health Endpoint with Degradation Status

**Files:**
- Modify: `services/retrieval/api/routes/health.py`

**Step 1: Update health endpoint to include degradation info**

Modify `services/retrieval/api/routes/health.py` to add degradation status:

```python
"""Health check routes for retrieval service."""

import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...resilience import DegradationMode, get_degradation_manager

router = APIRouter(tags=["health"])

VERSION = "1.0.0"


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None
    circuit_state: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    components: dict[str, bool]
    component_details: list[ComponentHealth] = Field(default_factory=list)
    degradation_level: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """
    Check service health.

    Returns status of all dependent components including:
    - Qdrant (semantic search)
    - OpenSearch (keyword search)
    - Reranker (LLM Gateway)

    Also includes degradation mode and capabilities.

    **Status Values:**
    - `healthy`: All components operational
    - `degraded`: Some components down but service functional
    - `unhealthy`: Critical components down
    """
    components: dict[str, bool] = {}
    component_details: list[ComponentHealth] = []

    # Get degradation manager for circuit states
    degradation_manager = get_degradation_manager()
    degradation_status = degradation_manager.get_status()
    circuit_statuses = degradation_manager.get_circuit_statuses()

    # Check Qdrant (semantic search)
    try:
        start = time.time()
        if hasattr(request.app.state, "hybrid"):
            await request.app.state.hybrid.semantic.health_check()
        components["qdrant"] = True
        component_details.append(
            ComponentHealth(
                name="qdrant",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["qdrant"]["state"],
            ),
        )
    except Exception as e:
        components["qdrant"] = False
        component_details.append(
            ComponentHealth(
                name="qdrant",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["qdrant"]["state"],
            ),
        )

    # Check OpenSearch (keyword search)
    try:
        start = time.time()
        if hasattr(request.app.state, "hybrid"):
            await request.app.state.hybrid.keyword.health_check()
        components["opensearch"] = True
        component_details.append(
            ComponentHealth(
                name="opensearch",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["opensearch"]["state"],
            ),
        )
    except Exception as e:
        components["opensearch"] = False
        component_details.append(
            ComponentHealth(
                name="opensearch",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["opensearch"]["state"],
            ),
        )

    # Check Reranker (LLM Gateway)
    try:
        start = time.time()
        if hasattr(request.app.state, "reranker"):
            await request.app.state.reranker.health_check()
        components["reranker"] = True
        component_details.append(
            ComponentHealth(
                name="reranker",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["reranker"]["state"],
            ),
        )
    except Exception as e:
        components["reranker"] = False
        component_details.append(
            ComponentHealth(
                name="reranker",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["reranker"]["state"],
            ),
        )

    # Determine overall status based on degradation mode
    mode = degradation_status.mode
    if mode == DegradationMode.HYBRID_FULL:
        status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    elif mode == DegradationMode.MINIMAL:
        status = "unhealthy"
    else:
        status = "degraded"

    # Capabilities based on circuit states
    capabilities = {
        "semantic_search": degradation_status.qdrant_healthy,
        "keyword_search": degradation_status.opensearch_healthy,
        "reranking": degradation_status.reranker_healthy,
        "hybrid_search": (
            degradation_status.qdrant_healthy and degradation_status.opensearch_healthy
        ),
    }

    return HealthResponse(
        status=status,
        version=VERSION,
        components=components,
        component_details=component_details,
        degradation_level=mode.value,
        capabilities=capabilities,
        timestamp=datetime.now(tz=UTC),
    )


@router.get("/health/live")
async def liveness() -> dict:
    """Kubernetes liveness probe."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(request: Request) -> dict:
    """Kubernetes readiness probe."""
    degradation_manager = get_degradation_manager()
    mode = degradation_manager.get_current_mode()

    # Ready if at least one search backend is available
    ready = mode != DegradationMode.MINIMAL

    return {
        "status": "ready" if ready else "not_ready",
        "degradation_mode": mode.value,
    }
```

**Step 2: Commit**

```bash
git add services/retrieval/api/routes/health.py
git commit -m "feat(retrieval): enhance health endpoint with degradation status

Health endpoint now includes:
- degradation_level field showing current mode
- circuit_state for each component
- capabilities map based on component health
- readiness probe considers degradation mode"
```

---

## Task 7: Add Prometheus Metrics for Degradation

**Files:**
- Modify: `services/retrieval/observability/metrics.py`

**Step 1: Add degradation metrics to RetrievalMetrics class**

Add these metrics to `services/retrieval/observability/metrics.py` in the `__init__` method:

```python
        # Degradation metrics
        self.degradation_mode = Gauge(
            f"{service_name}_degradation_mode",
            "Current degradation mode (1 = active)",
            ["mode"],
        )

        self.circuit_breaker_state = Gauge(
            f"{service_name}_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half_open)",
            ["component"],
        )

        self.degraded_searches = Counter(
            f"{service_name}_degraded_searches_total",
            "Total searches executed in degraded mode",
            ["mode"],
        )
```

Add this method to the class:

```python
    def update_degradation_metrics(
        self,
        mode: str,
        circuit_states: dict[str, str],
    ) -> None:
        """Update degradation-related metrics.

        Args:
            mode: Current degradation mode
            circuit_states: Dict mapping component name to circuit state
        """
        # Set active mode
        all_modes = [
            "hybrid_full",
            "semantic_only",
            "keyword_only",
            "hybrid_no_rerank",
            "minimal",
        ]
        for m in all_modes:
            self.degradation_mode.labels(mode=m).set(1 if m == mode else 0)

        # Set circuit states
        state_map = {"closed": 0, "open": 1, "half_open": 2}
        for component, state in circuit_states.items():
            self.circuit_breaker_state.labels(component=component).set(
                state_map.get(state, 0)
            )

    def record_degraded_search(self, mode: str) -> None:
        """Record a search executed in degraded mode.

        Args:
            mode: The degradation mode used for the search
        """
        if mode != "hybrid_full":
            self.degraded_searches.labels(mode=mode).inc()
```

**Step 2: Commit**

```bash
git add services/retrieval/observability/metrics.py
git commit -m "feat(retrieval): add Prometheus metrics for degradation

New metrics:
- retrieval_service_degradation_mode{mode} - gauge for current mode
- retrieval_service_circuit_breaker_state{component} - circuit states
- retrieval_service_degraded_searches_total{mode} - counter for degraded searches"
```

---

## Task 8: Wire Up Resilience in Application Lifespan

**Files:**
- Modify: `services/retrieval/api/main.py`
- Modify: `services/retrieval/config.py`

**Step 1: Add resilience config to RetrievalConfig**

Add to `services/retrieval/config.py`:

```python
    # Circuit Breaker settings
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0
    circuit_half_open_max_calls: int = 3
```

**Step 2: Update lifespan to initialize resilience components**

Modify `services/retrieval/api/main.py` lifespan function to add:

```python
from ..resilience import (
    CircuitBreakerConfig,
    ResilienceConfig,
    RetrievalDegradationManager,
    reset_degradation_manager,
)
from ..search.resilient_hybrid import ResilientHybridSearcher
```

In the lifespan function, after creating `hybrid`, add:

```python
    # Initialize resilience components
    reset_degradation_manager()  # Clear any previous state
    circuit_config = CircuitBreakerConfig(
        failure_threshold=config.circuit_failure_threshold,
        recovery_timeout=config.circuit_recovery_timeout,
        half_open_max_calls=config.circuit_half_open_max_calls,
    )
    resilience_config = ResilienceConfig(
        qdrant_circuit=circuit_config,
        opensearch_circuit=circuit_config,
        reranker_circuit=circuit_config,
    )
    degradation_manager = RetrievalDegradationManager(resilience_config)

    # Create resilient hybrid searcher
    resilient_hybrid = ResilientHybridSearcher(hybrid, degradation_manager)

    # Store in app state
    app.state.degradation_manager = degradation_manager
    app.state.resilient_hybrid = resilient_hybrid
```

**Step 3: Commit**

```bash
git add services/retrieval/api/main.py services/retrieval/config.py
git commit -m "feat(retrieval): wire up resilience in application lifespan

- Add circuit breaker config options to RetrievalConfig
- Initialize RetrievalDegradationManager on startup
- Create ResilientHybridSearcher wrapping HybridSearcher
- Store in app.state for use by routes"
```

---

## Task 9: Integration Tests for Degradation Scenarios

**Files:**
- Create: `services/retrieval/tests/resilience/test_integration.py`

**Step 1: Write integration tests**

Create `services/retrieval/tests/resilience/test_integration.py`:

```python
"""Integration tests for retrieval resilience."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from resilience import (
    CircuitBreakerConfig,
    CircuitState,
    DegradationMode,
    ResilienceConfig,
    RetrievalDegradationManager,
)
from search import HybridSearcher
from search.resilient_hybrid import ResilientHybridSearcher
from search.models import HybridSearchConfig, HybridSearchResponse, FusedResult


class TestResilientHybridSearcherIntegration:
    """Integration tests for ResilientHybridSearcher."""

    @pytest.fixture
    def mock_hybrid_searcher(self) -> MagicMock:
        """Create mock hybrid searcher."""
        mock = MagicMock(spec=HybridSearcher)
        mock.config = HybridSearchConfig()
        mock.semantic = MagicMock()
        mock.keyword = MagicMock()
        mock._fusion = MagicMock()
        return mock

    @pytest.fixture
    def degradation_manager(self) -> RetrievalDegradationManager:
        """Create degradation manager with fast circuit breakers."""
        config = ResilienceConfig(
            qdrant_circuit=CircuitBreakerConfig(
                failure_threshold=2, recovery_timeout=0.1
            ),
            opensearch_circuit=CircuitBreakerConfig(
                failure_threshold=2, recovery_timeout=0.1
            ),
            reranker_circuit=CircuitBreakerConfig(
                failure_threshold=2, recovery_timeout=0.1
            ),
        )
        return RetrievalDegradationManager(config)

    @pytest.fixture
    def resilient_searcher(
        self,
        mock_hybrid_searcher: MagicMock,
        degradation_manager: RetrievalDegradationManager,
    ) -> ResilientHybridSearcher:
        """Create resilient searcher with mocks."""
        return ResilientHybridSearcher(mock_hybrid_searcher, degradation_manager)

    async def test_search_hybrid_full_mode(
        self,
        resilient_searcher: ResilientHybridSearcher,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use both backends in HYBRID_FULL mode."""
        # Setup mocks
        mock_hybrid_searcher.semantic.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
            top_k=10,
        )

        assert response.degradation_mode == DegradationMode.HYBRID_FULL
        mock_hybrid_searcher.semantic.search.assert_called_once()
        mock_hybrid_searcher.keyword.search.assert_called_once()

    async def test_search_degrades_to_keyword_only(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use keyword-only when Qdrant circuit opens."""
        # Force Qdrant circuit open
        degradation_manager.qdrant_breaker._state = CircuitState.OPEN

        mock_hybrid_searcher.search_keyword_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=5,
                search_time_ms=10,
                fusion_method=mock_hybrid_searcher.config.fusion_method,
            )
        )

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.KEYWORD_ONLY
        assert "qdrant" in response.components_skipped

    async def test_search_degrades_to_semantic_only(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Search should use semantic-only when OpenSearch circuit opens."""
        # Force OpenSearch circuit open
        degradation_manager.opensearch_breaker._state = CircuitState.OPEN

        mock_hybrid_searcher.search_semantic_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[],
                total_semantic=5,
                total_keyword=0,
                search_time_ms=10,
                fusion_method=mock_hybrid_searcher.config.fusion_method,
            )
        )

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.SEMANTIC_ONLY
        assert "opensearch" in response.components_skipped

    async def test_search_returns_empty_in_minimal_mode(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
    ) -> None:
        """Search should return empty results in MINIMAL mode."""
        # Force both circuits open
        degradation_manager.qdrant_breaker._state = CircuitState.OPEN
        degradation_manager.opensearch_breaker._state = CircuitState.OPEN

        response = await resilient_searcher.search(
            query="test",
            query_embedding=[0.1] * 768,
        )

        assert response.degradation_mode == DegradationMode.MINIMAL
        assert len(response.results) == 0
        assert "qdrant" in response.components_skipped
        assert "opensearch" in response.components_skipped

    async def test_circuit_opens_after_failures(
        self,
        resilient_searcher: ResilientHybridSearcher,
        degradation_manager: RetrievalDegradationManager,
        mock_hybrid_searcher: MagicMock,
    ) -> None:
        """Circuit should open after threshold failures."""
        # Make semantic search fail
        mock_hybrid_searcher.semantic.search = AsyncMock(
            side_effect=ConnectionError("Qdrant unavailable")
        )
        mock_hybrid_searcher.keyword.search = AsyncMock(
            return_value=MagicMock(results=[], total_found=0)
        )
        mock_hybrid_searcher._fusion.fuse = MagicMock(return_value=[])

        # Trigger failures (threshold is 2)
        for _ in range(2):
            await resilient_searcher.search(
                query="test",
                query_embedding=[0.1] * 768,
            )

        # Circuit should now be open
        assert degradation_manager.qdrant_breaker.state == CircuitState.OPEN
        assert degradation_manager.get_current_mode() == DegradationMode.KEYWORD_ONLY
```

**Step 2: Run integration tests**

```bash
cd services/retrieval && pytest tests/resilience/test_integration.py -v
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add services/retrieval/tests/resilience/
git commit -m "test(retrieval): add resilience integration tests

Test coverage for:
- HYBRID_FULL mode using both backends
- Degradation to KEYWORD_ONLY when Qdrant fails
- Degradation to SEMANTIC_ONLY when OpenSearch fails
- MINIMAL mode when both backends fail
- Circuit breaker opening after threshold failures"
```

---

## Task 10: Update API Schemas with Degradation Info

**Files:**
- Modify: `services/retrieval/api/schemas/retrieve.py` (or equivalent)

**Step 1: Add degradation fields to response schemas**

Find the retrieve response schema and add:

```python
    degradation_mode: str | None = Field(
        default=None,
        description="Current degradation mode if service is degraded",
    )
    components_used: list[str] = Field(
        default_factory=list,
        description="List of components used for this search",
    )
    components_skipped: list[str] = Field(
        default_factory=list,
        description="List of components skipped due to failures",
    )
```

**Step 2: Commit**

```bash
git add services/retrieval/api/schemas/
git commit -m "feat(retrieval): add degradation fields to API response schemas

Search responses now include:
- degradation_mode: current mode (hybrid_full, semantic_only, etc.)
- components_used: which backends were used
- components_skipped: which backends were unavailable"
```

---

## Task 11: Final Verification and Documentation

**Step 1: Run all tests**

```bash
cd services/retrieval && pytest tests/ -v --tb=short
```

Expected: All tests PASS

**Step 2: Run linting**

```bash
cd services/retrieval && make lint
```

Or if using ruff directly:
```bash
ruff check services/retrieval/
ruff format services/retrieval/ --check
```

**Step 3: Verify health endpoint works**

Start the service and test:
```bash
curl http://localhost:8002/health | jq
```

Expected response should include `degradation_level` and `capabilities`.

**Step 4: Mark user story tasks complete**

Update `workflow/refined/10-architectural-improvements/US-10.2.1-retrieval-service-resilience-layer.md`:
- Check off completed acceptance criteria
- Update status to "In Review" or "Done"

**Step 5: Final commit**

```bash
git add .
git commit -m "docs: mark US-10.2.1 acceptance criteria complete

Retrieval Service Resilience Layer implementation complete:
- [x] AC-1: Circuit breakers for Qdrant, OpenSearch, Reranker
- [x] AC-2: Degradation modes (HYBRID_FULL, SEMANTIC_ONLY, etc.)
- [x] AC-3: Automatic mode selection via DegradationManager
- [x] AC-4: Health endpoint with degradation_level
- [x] AC-5: Response metadata with degradation info"
```

---

## Summary

This plan implements US-10.2.1 by:

1. **Copying circuit breaker infrastructure** from orchestrator (reuse existing code)
2. **Creating retrieval-specific degradation manager** with search modes
3. **Wrapping HybridSearcher** with circuit protection
4. **Updating health endpoint** with degradation status
5. **Adding Prometheus metrics** for observability
6. **Comprehensive testing** for all degradation scenarios

All code follows existing patterns in the codebase. Tests use pytest fixtures consistent with existing test files.
