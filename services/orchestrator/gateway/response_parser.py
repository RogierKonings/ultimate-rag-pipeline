"""Response parsing utilities for the Model Gateway.

This module handles parsing raw API responses into typed model objects
for both regular and streaming completions.
"""

import time
from typing import Any

from .models import (
    ChatChoice,
    ChatCompletionResponse,
    ChatMessage,
    StreamChoice,
    StreamChunk,
    StreamDelta,
    UsageStats,
)


def parse_completion_response(data: dict[str, Any]) -> ChatCompletionResponse:
    """Parse raw API response into ChatCompletionResponse.

    Args:
        data: The raw JSON response dictionary.

    Returns:
        Parsed ChatCompletionResponse.
    """
    choices = []
    for choice_data in data.get("choices", []):
        message_data = choice_data.get("message", {})
        message = ChatMessage(
            role=message_data.get("role", "assistant"),
            content=message_data.get("content", ""),
            name=message_data.get("name"),
        )
        choices.append(
            ChatChoice(
                index=choice_data.get("index", 0),
                message=message,
                finish_reason=choice_data.get("finish_reason"),
            ),
        )

    usage_data = data.get("usage", {})
    usage = UsageStats(
        prompt_tokens=usage_data.get("prompt_tokens", 0),
        completion_tokens=usage_data.get("completion_tokens", 0),
        total_tokens=usage_data.get("total_tokens", 0),
    )

    return ChatCompletionResponse(
        id=data.get("id", ""),
        object=data.get("object", "chat.completion"),
        created=data.get("created", int(time.time())),
        model=data.get("model", ""),
        choices=choices,
        usage=usage,
    )


def parse_stream_chunk(data: dict[str, Any]) -> StreamChunk:
    """Parse raw chunk data into StreamChunk.

    Args:
        data: The raw chunk data dictionary.

    Returns:
        Parsed StreamChunk object.
    """
    choices = []
    for choice_data in data.get("choices", []):
        delta_data = choice_data.get("delta", {})
        delta = StreamDelta(
            role=delta_data.get("role"),
            content=delta_data.get("content"),
        )
        choices.append(
            StreamChoice(
                index=choice_data.get("index", 0),
                delta=delta,
                finish_reason=choice_data.get("finish_reason"),
            ),
        )

    return StreamChunk(
        id=data.get("id", ""),
        object=data.get("object", "chat.completion.chunk"),
        created=data.get("created", int(time.time())),
        model=data.get("model", ""),
        choices=choices,
    )
