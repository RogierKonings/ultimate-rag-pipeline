"""Model Gateway module for the Orchestrator Service.

This module provides unified LLM access with support for:
- OpenAI-compatible API interface
- Multiple model/provider support
- Retry with exponential backoff
- Streaming support
- Health checks

Example:
    ```python
    from gateway import ModelGateway, ChatCompletionRequest, ChatMessage

    config = OrchestratorConfig()
    gateway = ModelGateway(config)

    request = ChatCompletionRequest(
        model="meta-llama/Llama-3.1-8B-Instruct",
        messages=[ChatMessage(role="user", content="Hello!")],
    )

    response = await gateway.chat_completion(request)
    print(response.choices[0].message.content)

    await gateway.close()
    ```
"""

from .client import ModelGateway
from .exceptions import (
    AuthenticationError,
    ContentFilterError,
    InvalidRequestError,
    ModelError,
    ModelGatewayError,
    ModelNotFoundError,
    ModelTimeoutError,
    RateLimitError,
    StreamingNotSupportedError,
)
from .models import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    GatewayConfig,
    HealthStatus,
    ModelConfig,
    ModelProvider,
    StreamChoice,
    StreamChunk,
    StreamDelta,
    UsageRecord,
    UsageStats,
)
from .streaming import (
    SSEBuffer,
    format_sse_done,
    format_sse_event,
    parse_sse_lines,
    parse_sse_stream,
)

__all__ = [
    # Client
    "ModelGateway",
    # Models
    "ChatMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatChoice",
    "UsageStats",
    "StreamChunk",
    "StreamChoice",
    "StreamDelta",
    "ModelConfig",
    "GatewayConfig",
    "ModelProvider",
    "UsageRecord",
    "HealthStatus",
    # Exceptions
    "ModelGatewayError",
    "ModelNotFoundError",
    "ModelTimeoutError",
    "RateLimitError",
    "AuthenticationError",
    "ModelError",
    "StreamingNotSupportedError",
    "InvalidRequestError",
    "ContentFilterError",
    # Streaming utilities
    "parse_sse_stream",
    "parse_sse_lines",
    "format_sse_event",
    "format_sse_done",
    "SSEBuffer",
]
