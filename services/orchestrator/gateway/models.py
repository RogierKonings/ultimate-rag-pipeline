"""Pydantic models for the Model Gateway.

This module defines the data models for LLM API interactions,
following the OpenAI API format for compatibility with vLLM and other providers.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class ModelProvider(StrEnum):
    """Supported model providers."""

    VLLM = "vllm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


class ChatMessage(BaseModel):
    """A message in a chat conversation.

    Attributes:
        role: The role of the message sender (system, user, assistant, function).
        content: The content of the message.
        name: Optional name for function messages.
    """

    role: Literal["system", "user", "assistant", "function"]
    content: str
    name: str | None = None

    def __str__(self) -> str:
        """Return a string representation of the message."""
        return f"{self.role}: {self.content[:50]}..."


class ChatCompletionRequest(BaseModel):
    """Request for chat completion.

    Attributes:
        model: The model identifier to use.
        messages: List of messages in the conversation.
        temperature: Sampling temperature (0.0-2.0).
        top_p: Nucleus sampling parameter.
        max_tokens: Maximum tokens to generate.
        stop: Stop sequences.
        stream: Whether to stream the response.
        frequency_penalty: Frequency penalty (-2.0 to 2.0).
        presence_penalty: Presence penalty (-2.0 to 2.0).
        request_id: Unique request identifier.
        user_id: Optional user identifier for tracking.
    """

    model: str
    messages: list[ChatMessage]

    # Generation parameters
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int | None = None
    stop: list[str] | None = None

    # Streaming
    stream: bool = False

    # Advanced settings
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)

    # Request metadata
    request_id: UUID = Field(default_factory=uuid4)
    user_id: str | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        """Ensure at least one message is provided."""
        if not v:
            raise ValueError("messages cannot be empty")
        return v


class ChatChoice(BaseModel):
    """A single completion choice.

    Attributes:
        index: The index of this choice in the list.
        message: The generated message.
        finish_reason: Why generation stopped.
    """

    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "length", "content_filter"] | None = None


class UsageStats(BaseModel):
    """Token usage information.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Total number of tokens used.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """Response from chat completion.

    Attributes:
        id: Unique response identifier.
        object: Object type (always "chat.completion").
        created: Unix timestamp of creation.
        model: The model used.
        choices: List of completion choices.
        usage: Token usage statistics.
        request_id: Original request ID if provided.
        latency_ms: Response latency in milliseconds.
    """

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: UsageStats

    # Extended metadata
    request_id: UUID | None = None
    latency_ms: float | None = None


class StreamDelta(BaseModel):
    """Delta content in a streaming chunk.

    Attributes:
        role: Optional role (typically only in first chunk).
        content: Incremental content.
    """

    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    """A choice in a streaming chunk.

    Attributes:
        index: The index of this choice.
        delta: The incremental content.
        finish_reason: Why generation stopped (if applicable).
    """

    index: int
    delta: StreamDelta
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    """A streaming response chunk.

    Attributes:
        id: Unique chunk identifier.
        object: Object type (always "chat.completion.chunk").
        created: Unix timestamp of creation.
        model: The model used.
        choices: List of streaming choices.
    """

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


class ModelConfig(BaseModel):
    """Configuration for a specific model.

    Attributes:
        name: Model identifier.
        provider: The model provider.
        base_url: Base URL for the API endpoint.
        api_key: Optional API key for authentication.
        max_tokens: Maximum tokens the model can generate.
        supports_streaming: Whether the model supports streaming.
        supports_function_calling: Whether the model supports function calling.
        context_window: Maximum context window size.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        retry_base_delay: Base delay for exponential backoff.
        retry_max_delay: Maximum delay between retries.
        requests_per_minute: Rate limit for requests.
        tokens_per_minute: Rate limit for tokens.
    """

    name: str
    provider: ModelProvider = ModelProvider.VLLM
    base_url: str = "http://localhost:8000/v1"
    api_key: str | None = None

    # Model capabilities
    max_tokens: int = 8192
    supports_streaming: bool = True
    supports_function_calling: bool = False
    context_window: int = 128000

    # Performance settings
    timeout: float = 60.0
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0

    # Rate limiting
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None


class GatewayConfig(BaseModel):
    """Configuration for the model gateway.

    Attributes:
        default_model: Default model to use if none specified.
        models: Dictionary of model configurations.
        enable_usage_tracking: Whether to track usage statistics.
        enable_rate_limiting: Whether to enable rate limiting.
        enable_retries: Whether to enable automatic retries.
        fallback_model: Model to use if primary fails.
        fallback_on_rate_limit: Whether to fallback on rate limit errors.
        fallback_on_timeout: Whether to fallback on timeout errors.
        max_connections: Maximum HTTP connections.
        connection_timeout: Timeout for establishing connections.
    """

    # Default model
    default_model: str = "meta-llama/Llama-3.1-8B-Instruct"

    # Available models
    models: dict[str, ModelConfig] = {}

    # Global settings
    enable_usage_tracking: bool = True
    enable_rate_limiting: bool = True
    enable_retries: bool = True

    # Fallback behavior
    fallback_model: str | None = None
    fallback_on_rate_limit: bool = True
    fallback_on_timeout: bool = True

    # Connection pooling
    max_connections: int = 100
    connection_timeout: float = 10.0


class UsageRecord(BaseModel):
    """Record of API usage for tracking.

    Attributes:
        timestamp: When the request occurred.
        request_id: Unique request identifier.
        model: Model used.
        user_id: Optional user identifier.
        prompt_tokens: Tokens in prompt.
        completion_tokens: Tokens in completion.
        total_tokens: Total tokens used.
        latency_ms: Response latency.
        success: Whether the request succeeded.
        error: Error message if request failed.
    """

    timestamp: datetime
    request_id: UUID
    model: str
    user_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    success: bool
    error: str | None = None


class HealthStatus(BaseModel):
    """Health status for a model endpoint.

    Attributes:
        status: Health status (healthy, unhealthy, error).
        latency_ms: Response latency in milliseconds.
        message: Optional status message.
    """

    status: Literal["healthy", "unhealthy", "error"]
    latency_ms: float | None = None
    message: str | None = None
