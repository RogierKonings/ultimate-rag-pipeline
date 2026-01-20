"""Tests for circuit breaker implementation."""

import time

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

    @pytest.mark.asyncio
    async def test_starts_closed(self, breaker: CircuitBreaker) -> None:
        """Circuit should start in CLOSED state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_healthy is True

    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self, breaker: CircuitBreaker) -> None:
        """Successful calls should keep circuit closed."""

        async def success() -> str:
            return "ok"

        result = await breaker.call(success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self, breaker: CircuitBreaker) -> None:
        """Open circuit should reject calls without fallback."""
        # Force circuit open
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.monotonic()

        async def func() -> str:
            return "should not run"

        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.call(func)

        assert "test" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_uses_fallback_when_open(self, breaker: CircuitBreaker) -> None:
        """Open circuit should use fallback if provided."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.monotonic()

        async def func() -> str:
            return "primary"

        async def fallback() -> str:
            return "fallback"

        result = await breaker.call(func, fallback=fallback)
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(
        self, breaker: CircuitBreaker
    ) -> None:
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.monotonic() - 1.0  # 1s ago

        # State property should reflect HALF_OPEN
        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_closes_after_success_in_half_open(
        self, breaker: CircuitBreaker
    ) -> None:
        """Successful call in HALF_OPEN should close circuit."""
        breaker._state = CircuitState.HALF_OPEN

        async def success() -> str:
            return "ok"

        await breaker.call(success)
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_uses_fallback_on_failure(self, breaker: CircuitBreaker) -> None:
        """Should use fallback when primary call fails."""

        async def failing() -> str:
            raise ConnectionError("failed")

        async def fallback() -> str:
            return "fallback"

        result = await breaker.call(failing, fallback=fallback)
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, breaker: CircuitBreaker) -> None:
        """Reset should return circuit to initial state."""
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_get_metrics(self, breaker: CircuitBreaker) -> None:
        """Should return comprehensive metrics."""
        metrics = breaker.get_metrics()

        assert metrics["name"] == "test"
        assert metrics["state"] == "closed"
        assert "failure_count" in metrics
        assert "total_calls" in metrics
        assert "config" in metrics

    @pytest.mark.asyncio
    async def test_sync_fallback_function(self, breaker: CircuitBreaker) -> None:
        """Should handle synchronous fallback functions."""
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.monotonic()

        async def func() -> str:
            return "primary"

        def sync_fallback() -> str:
            return "sync_fallback"

        result = await breaker.call(func, fallback=sync_fallback)
        assert result == "sync_fallback"

    @pytest.mark.asyncio
    async def test_failure_count_resets_on_success(
        self, breaker: CircuitBreaker
    ) -> None:
        """Failure count should reset after successful call."""

        async def failing() -> None:
            raise ConnectionError("failed")

        async def success() -> str:
            return "ok"

        # Accumulate some failures (not reaching threshold)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(failing)

        assert breaker.failure_count == 2

        # Successful call should reset
        await breaker.call(success)
        assert breaker.failure_count == 0
