"""Tests for circuit breaker implementation."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from resilience.config import CircuitBreakerConfig


class TestCircuitBreakerInitialization:
    """Tests for circuit breaker initialization."""

    def test_default_initialization(self):
        """Test circuit breaker with default config."""
        breaker = CircuitBreaker("test_service")

        assert breaker.name == "test_service"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.is_healthy is True

    def test_custom_config_initialization(self):
        """Test circuit breaker with custom config."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=60.0,
            half_open_max_calls=5,
        )
        breaker = CircuitBreaker("test_service", config)

        assert breaker.config.failure_threshold == 10
        assert breaker.config.recovery_timeout == 60.0
        assert breaker.config.half_open_max_calls == 5


class TestCircuitBreakerStateTransitions:
    """Tests for circuit breaker state transitions."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with low threshold for testing."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms for fast tests
            half_open_max_calls=2,
        )
        return CircuitBreaker("test_service", config)

    def test_initial_state_is_closed(self, breaker):
        """Test that initial state is CLOSED."""
        assert breaker.state == CircuitState.CLOSED

    def test_stays_closed_under_threshold(self, breaker):
        """Test circuit stays closed under failure threshold."""
        error = Exception("test error")

        breaker.record_failure(error)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 1

        breaker.record_failure(error)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 2

    def test_opens_at_threshold(self, breaker):
        """Test circuit opens when failure threshold reached."""
        error = Exception("test error")

        for _ in range(3):
            breaker.record_failure(error)

        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    def test_success_resets_failure_count(self, breaker):
        """Test successful call resets failure count."""
        error = Exception("test error")

        breaker.record_failure(error)
        breaker.record_failure(error)
        assert breaker.failure_count == 2

        breaker.record_success()
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        error = Exception("test error")

        # Open the circuit
        for _ in range(3):
            breaker.record_failure(error)
        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)  # Slightly more than 100ms

        # State should now be HALF_OPEN
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self, breaker):
        """Test circuit transitions from HALF_OPEN to CLOSED on success."""
        error = Exception("test error")

        # Open the circuit
        for _ in range(3):
            breaker.record_failure(error)

        # Manually set to half-open for testing
        breaker._state = CircuitState.HALF_OPEN

        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_half_open_to_open_on_failure(self, breaker):
        """Test circuit transitions from HALF_OPEN to OPEN on failure."""
        error = Exception("test error")

        # Set to half-open
        breaker._state = CircuitState.HALF_OPEN

        breaker.record_failure(error)
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerCall:
    """Tests for circuit breaker call method."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            half_open_max_calls=2,
        )
        return CircuitBreaker("test_service", config)

    @pytest.mark.asyncio
    async def test_successful_call(self, breaker):
        """Test successful call through circuit breaker."""
        async_func = AsyncMock(return_value="success")

        result = await breaker.call(async_func, "arg1", kwarg1="value1")

        assert result == "success"
        async_func.assert_called_once_with("arg1", kwarg1="value1")
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_failed_call_records_failure(self, breaker):
        """Test failed call records failure."""
        async_func = AsyncMock(side_effect=Exception("test error"))

        with pytest.raises(Exception, match="test error"):
            await breaker.call(async_func)

        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_failed_call_uses_fallback(self, breaker):
        """Test failed call uses fallback when provided."""
        async_func = AsyncMock(side_effect=Exception("test error"))
        fallback_func = AsyncMock(return_value="fallback_result")

        result = await breaker.call(async_func, fallback=fallback_func)

        assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_without_fallback(self, breaker):
        """Test open circuit rejects calls without fallback."""
        error = Exception("test error")

        # Open the circuit
        breaker.record_failure(error)
        breaker.record_failure(error)
        assert breaker.state == CircuitState.OPEN

        async_func = AsyncMock(return_value="success")

        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.call(async_func)

        assert exc_info.value.name == "test_service"
        async_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_circuit_uses_fallback(self, breaker):
        """Test open circuit uses fallback when provided."""
        error = Exception("test error")

        # Open the circuit
        breaker.record_failure(error)
        breaker.record_failure(error)

        async_func = AsyncMock(return_value="success")
        fallback_func = AsyncMock(return_value="fallback_result")

        result = await breaker.call(async_func, fallback=fallback_func)

        assert result == "fallback_result"
        async_func.assert_not_called()

    @pytest.mark.asyncio
    async def test_half_open_allows_limited_calls(self, breaker):
        """Test HALF_OPEN state allows limited calls."""
        # Set to half-open
        breaker._state = CircuitState.HALF_OPEN
        breaker._half_open_calls = 0

        async_func = AsyncMock(return_value="success")

        # First call should succeed
        result1 = await breaker.call(async_func)
        assert result1 == "success"

    @pytest.mark.asyncio
    async def test_half_open_recovery_on_success(self, breaker):
        """Test circuit recovers in HALF_OPEN on success."""
        # Set to half-open
        breaker._state = CircuitState.HALF_OPEN
        breaker._half_open_calls = 0

        async_func = AsyncMock(return_value="success")

        await breaker.call(async_func)

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_sync_fallback_function(self, breaker):
        """Test that synchronous fallback functions work."""
        async_func = AsyncMock(side_effect=Exception("test error"))

        def sync_fallback(*args, **kwargs):
            return "sync_fallback_result"

        result = await breaker.call(async_func, fallback=sync_fallback)

        assert result == "sync_fallback_result"


class TestCircuitBreakerMetrics:
    """Tests for circuit breaker metrics."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker for testing."""
        return CircuitBreaker("test_service")

    def test_initial_metrics(self, breaker):
        """Test initial metrics are zero."""
        metrics = breaker.get_metrics()

        assert metrics["name"] == "test_service"
        assert metrics["state"] == "closed"
        assert metrics["failure_count"] == 0
        assert metrics["total_calls"] == 0
        assert metrics["total_successes"] == 0
        assert metrics["total_failures"] == 0
        assert metrics["total_rejections"] == 0

    @pytest.mark.asyncio
    async def test_metrics_after_calls(self, breaker):
        """Test metrics are updated after calls."""
        success_func = AsyncMock(return_value="success")
        fail_func = AsyncMock(side_effect=Exception("error"))

        # Make successful calls
        await breaker.call(success_func)
        await breaker.call(success_func)

        # Make failed call (with fallback so it doesn't raise)
        await breaker.call(fail_func, fallback=AsyncMock(return_value="fallback"))

        metrics = breaker.get_metrics()

        assert metrics["total_calls"] == 3
        assert metrics["total_successes"] == 2
        assert metrics["total_failures"] == 1


class TestCircuitBreakerReset:
    """Tests for circuit breaker reset."""

    def test_reset_restores_closed_state(self):
        """Test reset restores circuit to CLOSED state."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker("test_service", config)
        error = Exception("test error")

        # Open the circuit
        breaker.record_failure(error)
        breaker.record_failure(error)
        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_reset_clears_half_open_state(self):
        """Test reset clears HALF_OPEN state."""
        breaker = CircuitBreaker("test_service")
        breaker._state = CircuitState.HALF_OPEN
        breaker._half_open_calls = 2

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception."""

    def test_error_message(self):
        """Test error message format."""
        error = CircuitOpenError("my_service", 15.5)

        assert error.name == "my_service"
        assert error.time_until_recovery == 15.5
        assert "my_service" in str(error)
        assert "15.5" in str(error)
