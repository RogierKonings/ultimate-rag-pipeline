"""
Resilience utilities for the RAG pipeline.

This module provides retry and timeout mechanisms for async operations,
with exponential backoff and structured logging.

Exports:
    - RetryExhausted: Exception raised when all retries are exhausted
    - TimeoutExceeded: Exception raised when an operation times out
    - with_retry: Execute async function with timeout and retry
    - retry_on_timeout: Decorator for retry logic
    - with_timeout: Execute async function with timeout only (no retry)
"""

from shared.resilience.retry import (
    RetryExhausted,
    TimeoutExceeded,
    retry_on_timeout,
    with_retry,
    with_timeout,
)

__all__ = [
    "RetryExhausted",
    "TimeoutExceeded",
    "with_retry",
    "retry_on_timeout",
    "with_timeout",
]
