"""
OpenAI-compatible request/response models for the Gateway.

These models follow the OpenAI API specification for chat completions,
embeddings, and reranking.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# =============================================================================
# Common Models
# =============================================================================


class Usage(BaseModel):
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: dict = Field(
        ...,
        description="Error details",
        examples=[
            {
                "message": "Invalid API key",
                "type": "authentication_error",
                "code": "invalid_api_key",
            },
        ],
    )

    @classmethod
    def create(
        cls,
        message: str,
        error_type: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
    ) -> "ErrorResponse":
        """Create an error response."""
        error = {
            "message": message,
            "type": error_type,
        }
        if code:
            error["code"] = code
        if param:
            error["param"] = param
        return cls(error=error)


# =============================================================================
# Chat Completion Models
# =============================================================================


class ChatMessageRole(str, Enum):
    """Valid chat message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """A single chat message."""

    role: ChatMessageRole
    content: str | None = None
    name: str | None = None
    function_call: dict | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    """Request for chat completion."""

    model: str = Field(..., description="Model ID to use")
    messages: list[ChatMessage] = Field(..., description="List of messages")

    # Generation parameters
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    n: int = Field(default=1, ge=1, le=10)
    max_tokens: int | None = Field(default=None, ge=1)
    stop: str | list[str] | None = None
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    logit_bias: dict[str, float] | None = None
    user: str | None = None

    # Streaming
    stream: bool = False

    # Response format
    response_format: dict | None = None

    # Seed for reproducibility
    seed: int | None = None


class ChatCompletionChoice(BaseModel):
    """A single completion choice."""

    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] | None = None
    logprobs: dict | None = None


class ChatCompletionResponse(BaseModel):
    """Response from chat completion."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:24]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.now(tz=UTC).timestamp()))
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage | None = None
    system_fingerprint: str | None = None


class ChatCompletionChunk(BaseModel):
    """Streaming chunk for chat completion."""

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[dict]  # Simplified for streaming
    system_fingerprint: str | None = None


class DeltaMessage(BaseModel):
    """Delta message for streaming."""

    role: str | None = None
    content: str | None = None
    function_call: dict | None = None
    tool_calls: list[dict] | None = None


# =============================================================================
# Embedding Models
# =============================================================================


class EmbeddingRequest(BaseModel):
    """Request for embeddings."""

    model: str = Field(..., description="Model ID to use")
    input: str | list[str] = Field(
        ...,
        description="Text(s) to embed",
    )
    encoding_format: Literal["float", "base64"] = "float"
    dimensions: int | None = None
    user: str | None = None


class EmbeddingData(BaseModel):
    """A single embedding result."""

    object: Literal["embedding"] = "embedding"
    index: int
    embedding: list[float] | str  # list[float] for float, str for base64


class EmbeddingResponse(BaseModel):
    """Response from embedding request."""

    object: Literal["list"] = "list"
    data: list[EmbeddingData]
    model: str
    usage: Usage


# =============================================================================
# Rerank Models
# =============================================================================


class RerankRequest(BaseModel):
    """Request for reranking documents."""

    model: str = Field(..., description="Model ID to use")
    query: str = Field(..., description="The query to rank documents against")
    documents: list[str | dict] = Field(
        ...,
        description="Documents to rerank (strings or objects with 'text' field)",
    )
    top_n: int | None = Field(
        default=None,
        description="Number of top results to return",
    )
    return_documents: bool = Field(
        default=False,
        description="Whether to return document text in response",
    )
    max_chunks_per_doc: int | None = None


class RerankResult(BaseModel):
    """A single rerank result."""

    index: int = Field(..., description="Original index of the document")
    relevance_score: float = Field(..., description="Relevance score (0-1)")
    document: str | dict | None = Field(
        default=None,
        description="Document text if return_documents=True",
    )


class RerankResponse(BaseModel):
    """Response from rerank request."""

    id: str = Field(default_factory=lambda: f"rerank-{uuid4().hex[:24]}")
    results: list[RerankResult]
    model: str
    usage: Usage | None = None


# =============================================================================
# Model Information
# =============================================================================


class ModelInfo(BaseModel):
    """Information about an available model."""

    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(datetime.now(tz=UTC).timestamp()))
    owned_by: str = "organization"
    permission: list = Field(default_factory=list)
    root: str | None = None
    parent: str | None = None


class ModelListResponse(BaseModel):
    """Response listing available models."""

    object: Literal["list"] = "list"
    data: list[ModelInfo]
