"""Retry and fallback logic for the Model Gateway.

This module handles retry with exponential backoff and jitter,
as well as fallback model selection on failure.
"""

import asyncio
import random

import httpx
import structlog

from .exceptions import (
    AuthenticationError,
    ModelError,
    ModelGatewayError,
    ModelNotFoundError,
    ModelTimeoutError,
    RateLimitError,
)
from .models import ChatCompletionRequest, GatewayConfig, ModelConfig

logger = structlog.get_logger(__name__)


def map_http_error(error: httpx.HTTPStatusError) -> ModelGatewayError:
    """Map HTTP errors to gateway exceptions.

    Args:
        error: The HTTP error.

    Returns:
        The appropriate gateway exception.
    """
    status = error.response.status_code

    if status == 429:
        return RateLimitError("Rate limit exceeded")
    if status == 401:
        return AuthenticationError("Invalid API key")
    if status == 404:
        return ModelNotFoundError("Model not found")
    if status >= 500:
        return ModelError(f"Server error: {status}")
    return ModelError(f"Request failed: {status}")


def is_retryable_http_error(error: httpx.HTTPStatusError) -> bool:
    """Check if an HTTP error is retryable.

    Client errors (4xx) are not retried, except for rate limits (429).
    Server errors (5xx) are retried.

    Args:
        error: The HTTP error.

    Returns:
        True if the error should be retried.
    """
    status_code = error.response.status_code
    if 400 <= status_code < 500 and status_code != 429:
        return False
    return True


async def sleep_with_backoff(
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> None:
    """Sleep with exponential backoff and jitter.

    Uses the formula: min(base_delay * 2^attempt, max_delay) * jitter
    where jitter is uniformly distributed in [0.5, 1.5].

    Args:
        attempt: The zero-based attempt number.
        base_delay: Base delay in seconds.
        max_delay: Maximum delay in seconds.
    """
    delay = min(base_delay * (2**attempt), max_delay)
    # Add jitter (0.5 to 1.5 of the delay)
    delay *= 0.5 + random.random()  # noqa: S311
    await asyncio.sleep(delay)


def should_fallback(
    error: Exception | None,
    gateway_config: GatewayConfig,
) -> bool:
    """Check if a fallback model should be attempted.

    Args:
        error: The error that occurred.
        gateway_config: The gateway configuration.

    Returns:
        True if fallback should be attempted.
    """
    if not gateway_config.fallback_model:
        return False

    if error is None:
        return False

    if isinstance(error, RateLimitError) and gateway_config.fallback_on_rate_limit:
        return True

    return bool(
        isinstance(error, ModelTimeoutError) and gateway_config.fallback_on_timeout,
    )


def build_fallback_request(
    original_request: ChatCompletionRequest,
    fallback_model: str,
) -> ChatCompletionRequest:
    """Create a new request targeting the fallback model.

    Args:
        original_request: The original request that failed.
        fallback_model: The fallback model identifier.

    Returns:
        A new ChatCompletionRequest with the fallback model.
    """
    return ChatCompletionRequest(
        model=fallback_model,
        messages=original_request.messages,
        temperature=original_request.temperature,
        top_p=original_request.top_p,
        max_tokens=original_request.max_tokens,
        stop=original_request.stop,
        stream=original_request.stream,
        frequency_penalty=original_request.frequency_penalty,
        presence_penalty=original_request.presence_penalty,
        request_id=original_request.request_id,
        user_id=original_request.user_id,
    )
