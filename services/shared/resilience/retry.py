"""
Retry utilities with exponential backoff for async operations.

This module provides robust retry mechanisms for async functions with:
- Configurable timeouts via asyncio.wait_for()
- Exponential backoff with jitter
- Respect for idempotency flags
- Structured logging via structlog

Usage:
    from shared.resilience.retry import with_retry, retry_on_timeout, with_timeout
    from shared.config.timeouts import RETRIEVAL_EMBEDDING_TIMEOUT

    # Functional approach
    result = await with_retry(
        fetch_embeddings,
        RETRIEVAL_EMBEDDING_TIMEOUT,
        "embedding_request",
        texts=["hello", "world"],
    )

    # Decorator approach
    @retry_on_timeout(RETRIEVAL_EMBEDDING_TIMEOUT, "embedding_request")
    async def fetch_embeddings(texts: list[str]) -> list[list[float]]:
        ...

    # Timeout only (no retry)
    result = await with_timeout(
        process_llm_request,
        timeout_ms=25000,
        operation_name="llm_generation",
        prompt=prompt,
    )
"""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Any, Callable, TypeVar

import structlog

from shared.config.timeouts import TimeoutConfig

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class RetryExhausted(Exception):
    """
    Raised when all retry attempts have been exhausted.

    Attributes:
        operation: Name of the operation that failed
        attempts: Number of attempts made
        last_error: The last exception that caused the failure
    """

    def __init__(
        self,
        operation: str,
        attempts: int,
        last_error: Exception,
    ) -> None:
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Operation '{operation}' failed after {attempts} attempts. "
            f"Last error: {last_error}"
        )


class TimeoutExceeded(Exception):
    """
    Raised when an operation exceeds its timeout.

    Attributes:
        operation: Name of the operation that timed out
        timeout_ms: The timeout value in milliseconds
    """

    def __init__(self, operation: str, timeout_ms: int) -> None:
        self.operation = operation
        self.timeout_ms = timeout_ms
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_ms}ms"
        )


def _calculate_backoff(
    attempt: int,
    base_ms: int,
    max_ms: int,
) -> float:
    """
    Calculate exponential backoff delay with jitter.

    Uses exponential backoff: base_ms * 2^attempt, capped at max_ms,
    with +/- 25% jitter to prevent thundering herd.

    Args:
        attempt: The current attempt number (0-indexed)
        base_ms: Base delay in milliseconds
        max_ms: Maximum delay in milliseconds

    Returns:
        Delay in seconds (with jitter applied)
    """
    # Exponential backoff: base * 2^attempt
    delay_ms = min(base_ms * (2 ** attempt), max_ms)

    # Add +/- 25% jitter
    jitter_factor = 1.0 + random.uniform(-0.25, 0.25)
    delay_ms = delay_ms * jitter_factor

    # Convert to seconds
    return delay_ms / 1000.0


async def with_retry(
    func: Callable[..., T],
    config: TimeoutConfig,
    operation_name: str,
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    Execute an async function with timeout and retry logic.

    Applies timeout via asyncio.wait_for() and retries on failure
    with exponential backoff. Respects the idempotent flag - non-idempotent
    operations are not retried.

    Args:
        func: The async function to execute
        config: TimeoutConfig with timeout and retry settings
        operation_name: Name for logging and error messages
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        The result of the function call

    Raises:
        RetryExhausted: When all retry attempts fail
        TimeoutExceeded: When operation times out and no retries remain
        Exception: Any non-retryable exception from the function

    Example:
        result = await with_retry(
            fetch_data,
            RETRIEVAL_QDRANT_TIMEOUT,
            "qdrant_search",
            collection="documents",
            vector=query_vector,
        )
    """
    # Calculate total attempts (1 initial + retries, but only if idempotent)
    max_attempts = 1 + (config.retries if config.idempotent else 0)
    timeout_seconds = config.timeout_seconds
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            await logger.adebug(
                "Executing operation",
                operation=operation_name,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                timeout_ms=config.timeout_ms,
            )

            # Execute with timeout
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )

            if attempt > 0:
                await logger.ainfo(
                    "Operation succeeded after retry",
                    operation=operation_name,
                    attempt=attempt + 1,
                )

            return result

        except asyncio.TimeoutError:
            last_error = TimeoutExceeded(operation_name, config.timeout_ms)
            await logger.awarning(
                "Operation timed out",
                operation=operation_name,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                timeout_ms=config.timeout_ms,
            )

        except Exception as e:
            last_error = e
            await logger.awarning(
                "Operation failed",
                operation=operation_name,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                error=str(e),
                error_type=type(e).__name__,
            )

        # Check if we should retry
        if attempt + 1 < max_attempts:
            backoff_delay = _calculate_backoff(
                attempt,
                config.backoff_base_ms,
                config.backoff_max_ms,
            )
            await logger.adebug(
                "Waiting before retry",
                operation=operation_name,
                backoff_seconds=round(backoff_delay, 3),
            )
            await asyncio.sleep(backoff_delay)

    # All attempts exhausted
    assert last_error is not None
    await logger.aerror(
        "Operation failed after all retries",
        operation=operation_name,
        attempts=max_attempts,
        last_error=str(last_error),
        last_error_type=type(last_error).__name__,
    )
    raise RetryExhausted(operation_name, max_attempts, last_error)


def retry_on_timeout(
    config: TimeoutConfig,
    operation_name: str,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to add timeout and retry logic to an async function.

    Wraps the decorated function with with_retry() using the provided
    configuration.

    Args:
        config: TimeoutConfig with timeout and retry settings
        operation_name: Name for logging and error messages

    Returns:
        Decorator function

    Example:
        @retry_on_timeout(RETRIEVAL_QDRANT_TIMEOUT, "qdrant_search")
        async def search_qdrant(collection: str, vector: list[float]) -> list[dict]:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await with_retry(
                func,
                config,
                operation_name,
                *args,
                **kwargs,
            )

        return wrapper

    return decorator


async def with_timeout(
    func: Callable[..., T],
    timeout_ms: int,
    operation_name: str,
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    Execute an async function with timeout only (no retry).

    Use this for non-idempotent operations where retry is not appropriate,
    or when you need simple timeout handling without the full retry machinery.

    Args:
        func: The async function to execute
        timeout_ms: Timeout in milliseconds
        operation_name: Name for logging and error messages
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        The result of the function call

    Raises:
        TimeoutExceeded: When the operation times out

    Example:
        result = await with_timeout(
            generate_response,
            timeout_ms=25000,
            operation_name="llm_generation",
            prompt=prompt,
            temperature=0.7,
        )
    """
    timeout_seconds = timeout_ms / 1000.0

    try:
        await logger.adebug(
            "Executing operation with timeout",
            operation=operation_name,
            timeout_ms=timeout_ms,
        )

        result = await asyncio.wait_for(
            func(*args, **kwargs),
            timeout=timeout_seconds,
        )

        return result

    except asyncio.TimeoutError:
        await logger.aerror(
            "Operation timed out",
            operation=operation_name,
            timeout_ms=timeout_ms,
        )
        raise TimeoutExceeded(operation_name, timeout_ms)
