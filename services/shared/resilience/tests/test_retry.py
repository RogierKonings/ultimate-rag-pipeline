"""Tests for retry utility."""

import asyncio
import time
from typing import Any
from unittest import mock

import pytest

from shared.config.timeouts import TimeoutConfig
from shared.resilience.retry import (
    RetryExhausted,
    TimeoutExceeded,
    _calculate_backoff,
    retry_on_timeout,
    with_retry,
    with_timeout,
)


class TestRetryExhausted:
    """Tests for RetryExhausted exception."""

    def test_exception_attributes(self) -> None:
        """RetryExhausted should have correct attributes."""
        last_error = ValueError("test error")
        exc = RetryExhausted(
            operation="test_op",
            attempts=3,
            last_error=last_error,
        )

        assert exc.operation == "test_op"
        assert exc.attempts == 3
        assert exc.last_error is last_error

    def test_exception_message(self) -> None:
        """RetryExhausted should have descriptive message."""
        last_error = ValueError("test error")
        exc = RetryExhausted(
            operation="test_op",
            attempts=3,
            last_error=last_error,
        )

        message = str(exc)
        assert "test_op" in message
        assert "3 attempts" in message
        assert "test error" in message


class TestTimeoutExceeded:
    """Tests for TimeoutExceeded exception."""

    def test_exception_attributes(self) -> None:
        """TimeoutExceeded should have correct attributes."""
        exc = TimeoutExceeded(operation="test_op", timeout_ms=5000)

        assert exc.operation == "test_op"
        assert exc.timeout_ms == 5000

    def test_exception_message(self) -> None:
        """TimeoutExceeded should have descriptive message."""
        exc = TimeoutExceeded(operation="test_op", timeout_ms=5000)

        message = str(exc)
        assert "test_op" in message
        assert "5000ms" in message


class TestCalculateBackoff:
    """Tests for _calculate_backoff function."""

    def test_backoff_base_calculation(self) -> None:
        """Backoff should start at base value for attempt 0."""
        # Without jitter, delay should be base_ms
        # With jitter (+/- 25%), delay should be within range
        delay = _calculate_backoff(attempt=0, base_ms=100, max_ms=5000)

        # Should be around 100ms (0.1s) +/- 25%
        assert 0.075 <= delay <= 0.125

    def test_backoff_exponential_increase(self) -> None:
        """Backoff should increase exponentially."""
        # Attempt 0: 100ms, Attempt 1: 200ms, Attempt 2: 400ms
        delay_0 = _calculate_backoff(attempt=0, base_ms=100, max_ms=5000)
        delay_1 = _calculate_backoff(attempt=1, base_ms=100, max_ms=5000)
        delay_2 = _calculate_backoff(attempt=2, base_ms=100, max_ms=5000)

        # Each delay should roughly double (accounting for jitter variance)
        # delay_0 is ~0.1s, delay_1 is ~0.2s, delay_2 is ~0.4s
        # We can't assert exact ratios due to jitter, but ranges should be:
        assert 0.075 <= delay_0 <= 0.125  # 100ms +/- 25%
        assert 0.150 <= delay_1 <= 0.250  # 200ms +/- 25%
        assert 0.300 <= delay_2 <= 0.500  # 400ms +/- 25%

    def test_backoff_respects_max(self) -> None:
        """Backoff should not exceed max value."""
        # With large attempt number, should cap at max_ms
        delay = _calculate_backoff(attempt=10, base_ms=100, max_ms=1000)

        # Should be around 1000ms (1s) +/- 25%
        assert 0.75 <= delay <= 1.25

    def test_backoff_returns_seconds(self) -> None:
        """Backoff should return value in seconds."""
        delay = _calculate_backoff(attempt=0, base_ms=1000, max_ms=5000)

        # 1000ms = 1s, +/- 25% = 0.75 to 1.25
        assert 0.75 <= delay <= 1.25

    @mock.patch("shared.resilience.retry.random.uniform")
    def test_backoff_jitter_applied(self, mock_uniform: mock.Mock) -> None:
        """Backoff should apply jitter using random.uniform."""
        mock_uniform.return_value = 0.1  # +10% jitter

        delay = _calculate_backoff(attempt=0, base_ms=100, max_ms=5000)

        mock_uniform.assert_called_once_with(-0.25, 0.25)
        # 100ms * 1.1 (jitter factor) = 110ms = 0.11s
        assert delay == pytest.approx(0.11, rel=0.001)


class TestWithRetry:
    """Tests for with_retry function."""

    @pytest.fixture
    def config(self) -> TimeoutConfig:
        """Create test timeout config."""
        return TimeoutConfig(
            timeout_ms=100,
            retries=2,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

    @pytest.mark.asyncio
    async def test_successful_call(self, config: TimeoutConfig) -> None:
        """Successful call should return result immediately."""

        async def success_func() -> str:
            return "success"

        result = await with_retry(success_func, config, "test_op")

        assert result == "success"

    @pytest.mark.asyncio
    async def test_successful_call_with_args(self, config: TimeoutConfig) -> None:
        """Successful call should pass args and kwargs correctly."""

        async def func_with_args(a: int, b: int, c: int = 0) -> int:
            return a + b + c

        result = await with_retry(func_with_args, config, "test_op", 1, 2, c=3)

        assert result == 6

    @pytest.mark.asyncio
    async def test_retries_on_failure(self, config: TimeoutConfig) -> None:
        """Should retry on failure until success."""
        call_count = 0

        async def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("First call fails")
            return "success"

        result = await with_retry(fail_then_succeed, config, "test_op")

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_multiple_failures(self, config: TimeoutConfig) -> None:
        """Should retry multiple times until success."""
        call_count = 0

        async def fail_twice_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Call {call_count} fails")
            return "success"

        result = await with_retry(fail_twice_then_succeed, config, "test_op")

        assert result == "success"
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_raises_after_retries_exhausted(self, config: TimeoutConfig) -> None:
        """Should raise RetryExhausted after all attempts fail."""
        call_count = 0

        async def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Call {call_count} fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(always_fail, config, "test_op")

        exc = exc_info.value
        assert exc.operation == "test_op"
        assert exc.attempts == 3  # 1 initial + 2 retries
        assert isinstance(exc.last_error, ValueError)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self, config: TimeoutConfig) -> None:
        """Timeout should trigger retry."""
        call_count = 0

        async def slow_then_fast() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call times out (100ms timeout, sleep 200ms)
                await asyncio.sleep(0.2)
            return "success"

        result = await with_retry(slow_then_fast, config, "test_op")

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_after_exhausted(self, config: TimeoutConfig) -> None:
        """Should raise RetryExhausted with TimeoutExceeded when all timeouts."""
        call_count = 0

        async def always_slow() -> str:
            nonlocal call_count
            call_count += 1
            # Always times out
            await asyncio.sleep(0.2)
            return "success"

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(always_slow, config, "test_op")

        exc = exc_info.value
        assert exc.operation == "test_op"
        assert exc.attempts == 3
        assert isinstance(exc.last_error, TimeoutExceeded)
        assert exc.last_error.timeout_ms == 100
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_idempotent_not_retried(self) -> None:
        """Non-idempotent operations should not be retried."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=2,  # Would allow 2 retries if idempotent
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=False,
        )
        call_count = 0

        async def fail_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(fail_func, config, "test_op")

        exc = exc_info.value
        assert exc.attempts == 1  # Only 1 attempt, no retries
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_non_idempotent_success_on_first_try(self) -> None:
        """Non-idempotent operations should succeed on first try."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=2,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=False,
        )

        async def success_func() -> str:
            return "success"

        result = await with_retry(success_func, config, "test_op")

        assert result == "success"

    @pytest.mark.asyncio
    async def test_zero_retries_single_attempt(self) -> None:
        """Zero retries should mean only 1 attempt."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=0,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )
        call_count = 0

        async def fail_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(fail_func, config, "test_op")

        assert exc_info.value.attempts == 1
        assert call_count == 1


class TestBackoffBehavior:
    """Tests for backoff behavior in with_retry."""

    @pytest.mark.asyncio
    async def test_backoff_increases_exponentially(self) -> None:
        """Backoff should increase with each attempt."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=3,
            backoff_base_ms=50,
            backoff_max_ms=1000,
            idempotent=True,
        )
        delays: list[float] = []
        last_call_time: float | None = None

        async def track_delays() -> str:
            nonlocal last_call_time
            current_time = time.monotonic()
            if last_call_time is not None:
                delays.append(current_time - last_call_time)
            last_call_time = current_time
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted):
            await with_retry(track_delays, config, "test_op")

        # Should have 3 delays (between 4 calls: initial + 3 retries)
        assert len(delays) == 3

        # Delays should increase (with some tolerance for jitter)
        # delay[0] ~= 50ms (0.05s), delay[1] ~= 100ms (0.1s), delay[2] ~= 200ms (0.2s)
        # With +/- 25% jitter: 37.5-62.5ms, 75-125ms, 150-250ms
        assert 0.025 <= delays[0] <= 0.080
        assert 0.060 <= delays[1] <= 0.150
        assert 0.120 <= delays[2] <= 0.280


class TestRetryOnTimeoutDecorator:
    """Tests for retry_on_timeout decorator."""

    @pytest.mark.asyncio
    async def test_decorator_applies_retry(self) -> None:
        """Decorator should apply retry logic."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=2,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )
        call_count = 0

        @retry_on_timeout(config, "decorated_op")
        async def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("First call fails")
            return "success"

        result = await fail_then_succeed()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decorator_with_args(self) -> None:
        """Decorator should pass args and kwargs correctly."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

        @retry_on_timeout(config, "decorated_op")
        async def add(a: int, b: int, c: int = 0) -> int:
            return a + b + c

        result = await add(1, 2, c=3)

        assert result == 6

    @pytest.mark.asyncio
    async def test_decorator_raises_retry_exhausted(self) -> None:
        """Decorator should raise RetryExhausted when all retries fail."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

        @retry_on_timeout(config, "decorated_op")
        async def always_fail() -> str:
            raise ValueError("Always fails")

        with pytest.raises(RetryExhausted) as exc_info:
            await always_fail()

        assert exc_info.value.operation == "decorated_op"
        assert exc_info.value.attempts == 2  # 1 initial + 1 retry

    @pytest.mark.asyncio
    async def test_decorator_preserves_function_metadata(self) -> None:
        """Decorator should preserve function name and docstring."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

        @retry_on_timeout(config, "decorated_op")
        async def my_function() -> str:
            """My function docstring."""
            return "result"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My function docstring."


class TestWithTimeout:
    """Tests for with_timeout function."""

    @pytest.mark.asyncio
    async def test_successful_call(self) -> None:
        """Successful call within timeout should return result."""

        async def fast_func() -> str:
            return "success"

        result = await with_timeout(fast_func, timeout_ms=100, operation_name="test_op")

        assert result == "success"

    @pytest.mark.asyncio
    async def test_successful_call_with_args(self) -> None:
        """Successful call should pass args and kwargs correctly."""

        async def func_with_args(a: int, b: int, c: int = 0) -> int:
            return a + b + c

        result = await with_timeout(
            func_with_args,
            timeout_ms=100,
            operation_name="test_op",
            a=1,
            b=2,
            c=3,
        )

        assert result == 6

    @pytest.mark.asyncio
    async def test_successful_call_with_positional_args(self) -> None:
        """Successful call should pass positional args correctly."""

        async def func_with_args(a: int, b: int) -> int:
            return a + b

        result = await with_timeout(func_with_args, 100, "test_op", 1, 2)

        assert result == 3

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        """Slow call should raise TimeoutExceeded."""

        async def slow_func() -> str:
            await asyncio.sleep(0.2)
            return "too slow"

        with pytest.raises(TimeoutExceeded) as exc_info:
            await with_timeout(slow_func, timeout_ms=50, operation_name="slow_op")

        exc = exc_info.value
        assert exc.operation == "slow_op"
        assert exc.timeout_ms == 50

    @pytest.mark.asyncio
    async def test_no_retry_on_timeout(self) -> None:
        """with_timeout should not retry on timeout."""
        call_count = 0

        async def slow_func() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.2)
            return "too slow"

        with pytest.raises(TimeoutExceeded):
            await with_timeout(slow_func, timeout_ms=50, operation_name="slow_op")

        # Should only be called once (no retries)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exception_propagation(self) -> None:
        """Non-timeout exceptions should propagate unchanged."""

        async def error_func() -> str:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await with_timeout(error_func, timeout_ms=100, operation_name="error_op")


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.mark.asyncio
    async def test_immediate_success_no_delay(self) -> None:
        """Immediate success should not incur any backoff delay."""
        config = TimeoutConfig(
            timeout_ms=1000,
            retries=5,
            backoff_base_ms=1000,  # Large backoff to detect if applied
            backoff_max_ms=5000,
            idempotent=True,
        )
        start_time = time.monotonic()

        async def fast_func() -> str:
            return "success"

        result = await with_retry(fast_func, config, "test_op")
        elapsed = time.monotonic() - start_time

        assert result == "success"
        # Should complete almost instantly (well under 1 second)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_concurrent_calls_independent(self) -> None:
        """Concurrent calls should be independent."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )
        results: list[str] = []

        async def task(task_id: str) -> str:
            return f"result_{task_id}"

        # Run multiple concurrent calls
        tasks = [with_retry(task, config, f"op_{i}", f"task_{i}") for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert results == ["result_task_0", "result_task_1", "result_task_2"]

    @pytest.mark.asyncio
    async def test_very_short_timeout(self) -> None:
        """Very short timeout should still work correctly."""
        config = TimeoutConfig(
            timeout_ms=1,  # 1ms timeout
            retries=1,
            backoff_base_ms=1,
            backoff_max_ms=5,
            idempotent=True,
        )

        async def slow_func() -> str:
            await asyncio.sleep(0.1)
            return "success"

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(slow_func, config, "test_op")

        assert isinstance(exc_info.value.last_error, TimeoutExceeded)

    @pytest.mark.asyncio
    async def test_mixed_errors_and_timeouts(self) -> None:
        """Should handle mix of regular errors and timeouts."""
        config = TimeoutConfig(
            timeout_ms=50,
            retries=3,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )
        call_count = 0

        async def mixed_failures() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Regular error")
            if call_count == 2:
                await asyncio.sleep(0.2)  # Timeout
            elif call_count == 3:
                raise ConnectionError("Connection lost")
            else:
                # 4th call also fails
                raise RuntimeError("Final failure")

        with pytest.raises(RetryExhausted) as exc_info:
            await with_retry(mixed_failures, config, "test_op")

        exc = exc_info.value
        assert exc.attempts == 4  # 1 initial + 3 retries
        # Last error should be RuntimeError (4th call)
        assert isinstance(exc.last_error, RuntimeError)
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_return_none(self) -> None:
        """Should correctly return None values."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

        async def returns_none() -> None:
            return None

        result = await with_retry(returns_none, config, "test_op")

        assert result is None

    @pytest.mark.asyncio
    async def test_return_falsy_values(self) -> None:
        """Should correctly return falsy values."""
        config = TimeoutConfig(
            timeout_ms=100,
            retries=1,
            backoff_base_ms=10,
            backoff_max_ms=50,
            idempotent=True,
        )

        async def returns_zero() -> int:
            return 0

        async def returns_empty_list() -> list[Any]:
            return []

        async def returns_empty_string() -> str:
            return ""

        assert await with_retry(returns_zero, config, "op1") == 0
        assert await with_retry(returns_empty_list, config, "op2") == []
        assert await with_retry(returns_empty_string, config, "op3") == ""
