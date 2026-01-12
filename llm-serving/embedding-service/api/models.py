"""
Pydantic models for the Embedding Service API.
"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class EmbeddingRequest(BaseModel):
    """
    OpenAI-compatible embedding request.

    Supports both single string and list of strings as input.
    """

    model: str = "BAAI/bge-large-en-v1.5"
    input: str | list[str]
    encoding_format: Literal["float", "base64"] = "float"

    # Extension: prefix for BGE models
    input_type: Literal["query", "passage"] | None = None

    # Request metadata
    user: str | None = None
    request_id: UUID = Field(default_factory=uuid4)

    @field_validator("input")
    @classmethod
    def validate_input(cls, v: str | list[str]) -> str | list[str]:
        """Validate that input is not empty."""
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("Input cannot be empty")
        elif isinstance(v, list):
            if len(v) == 0:
                raise ValueError("Input list cannot be empty")
            if any(not s.strip() for s in v):
                raise ValueError("Input list cannot contain empty strings")
        return v


class EmbeddingData(BaseModel):
    """Single embedding in the response."""

    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingUsage(BaseModel):
    """Token usage for embedding request."""

    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    """OpenAI-compatible embedding response."""

    object: str = "list"
    model: str
    data: list[EmbeddingData]
    usage: EmbeddingUsage


class BatchEmbeddingRequest(BaseModel):
    """Batch embedding request for internal use."""

    texts: list[str]
    input_type: Literal["query", "passage"] | None = None
    request_ids: list[UUID] = Field(default_factory=list)


class BatchEmbeddingResult(BaseModel):
    """Batch embedding result."""

    embeddings: list[list[float]]
    dimensions: int
    total_tokens: int
    processing_time_ms: float


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "unhealthy", "degraded"]
    model_loaded: bool
    model_name: str
    embedding_dim: int
    device: str
    gpu_available: bool
    gpu_memory_used_mb: float | None = None
    queue_size: int
    uptime_seconds: float


class ModelInfo(BaseModel):
    """Model information for /v1/models endpoint."""

    id: str
    object: str = "model"
    owned_by: str = "bge"
    permission: list = Field(default_factory=list)


class ModelsResponse(BaseModel):
    """Response for /v1/models endpoint."""

    object: str = "list"
    data: list[ModelInfo]
