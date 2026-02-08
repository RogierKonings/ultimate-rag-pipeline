"""Request building utilities for the Model Gateway.

This module handles construction of HTTP request payloads and headers
for LLM API calls.
"""

from typing import Any

from orchestrator.observability.correlation import get_correlation_context

from .models import ChatCompletionRequest, ModelConfig


def build_chat_payload(
    request: ChatCompletionRequest,
    model: str,
    max_tokens_default: int | None,
    stream: bool = False,
) -> dict[str, Any]:
    """Build the JSON payload for a chat completion request.

    Args:
        request: The chat completion request.
        model: The resolved model identifier.
        max_tokens_default: Default max_tokens from config (used if not set on request).
        stream: Whether to enable streaming.

    Returns:
        Dictionary payload ready for JSON serialization.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": [msg.model_dump() for msg in request.messages],
        "temperature": request.temperature,
        "top_p": request.top_p,
        "stream": stream,
    }

    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    elif max_tokens_default:
        payload["max_tokens"] = max_tokens_default

    if request.stop:
        payload["stop"] = request.stop
    if request.frequency_penalty != 0.0:
        payload["frequency_penalty"] = request.frequency_penalty
    if request.presence_penalty != 0.0:
        payload["presence_penalty"] = request.presence_penalty

    return payload


def build_headers(model_config: ModelConfig) -> dict[str, str]:
    """Build HTTP headers for an API request.

    Includes Content-Type, optional Authorization, and correlation
    headers for distributed tracing.

    Args:
        model_config: The model configuration (may contain an API key).

    Returns:
        Dictionary of HTTP headers.
    """
    headers = {"Content-Type": "application/json"}
    if model_config.api_key:
        headers["Authorization"] = f"Bearer {model_config.api_key}"

    # Add correlation headers for distributed tracing (US-10.3.1)
    ctx = get_correlation_context()
    if ctx:
        headers.update(ctx.to_headers())

    return headers
