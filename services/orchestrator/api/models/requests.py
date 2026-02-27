"""Request models for the Orchestrator API."""

from uuid import UUID

from pydantic import BaseModel, Field


class QueryOptions(BaseModel):
    """Typed configuration overrides for a query request.

    All fields are optional; omitted fields fall back to service defaults.
    """

    model: str | None = Field(
        default=None,
        description="LLM model name to use for answer generation",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0–2.0)",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of retrieved chunks (1–100)",
    )
    semantic_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Weight for semantic search in hybrid fusion (0.0–1.0)",
    )
    keyword_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Weight for keyword search in hybrid fusion (0.0–1.0)",
    )
    rerank: bool | None = Field(
        default=None,
        description="Whether to enable cross-encoder reranking",
    )
    answer_cache: bool | None = Field(
        default=None,
        description="Whether to use the answer cache",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=8192,
        description="Maximum tokens in the generated answer (1–8192)",
    )


class QueryRequest(BaseModel):
    """Request model for synchronous RAG query.

    Attributes:
        query: The user's query text.
        session_id: Optional session ID for conversation continuity.
        user_id: Optional user identifier for ACL filtering.
        tenant_id: Optional tenant identifier for multi-tenancy.
        options: Optional configuration overrides.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's query text",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Session ID for conversation continuity",
    )
    user_id: UUID | None = Field(
        default=None,
        description="User identifier for ACL filtering",
    )
    tenant_id: UUID | None = Field(
        default=None,
        description="Tenant identifier for multi-tenancy",
    )
    options: QueryOptions | None = Field(
        default=None,
        description="Optional configuration overrides (model, temperature, etc.)",
    )


class StreamQueryRequest(BaseModel):
    """Request model for streaming RAG query.

    Attributes:
        query: The user's query text.
        session_id: Optional session ID for conversation continuity.
        user_id: Optional user identifier for ACL filtering.
        tenant_id: Optional tenant identifier for multi-tenancy.
        options: Optional configuration overrides.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's query text",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Session ID for conversation continuity",
    )
    user_id: UUID | None = Field(
        default=None,
        description="User identifier for ACL filtering",
    )
    tenant_id: UUID | None = Field(
        default=None,
        description="Tenant identifier for multi-tenancy",
    )
    options: QueryOptions | None = Field(
        default=None,
        description="Optional configuration overrides",
    )


class FeedbackRequest(BaseModel):
    """Request model for submitting user feedback.

    Attributes:
        request_id: The request ID to provide feedback for.
        rating: User rating (1-5).
        feedback_type: Type of feedback (helpful, unhelpful, wrong, etc.).
        comment: Optional user comment.
        session_id: Optional session ID for context.
    """

    request_id: str = Field(
        ...,
        description="The request ID to provide feedback for",
    )
    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="User rating from 1 (poor) to 5 (excellent)",
    )
    feedback_type: str = Field(
        default="general",
        description="Type of feedback (helpful, unhelpful, wrong, general)",
    )
    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional user comment",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Session ID for context",
    )


class CreateSessionRequest(BaseModel):
    """Request model for creating a new session.

    Attributes:
        user_id: Optional user identifier.
        tenant_id: Optional tenant identifier.
        system_prompt: Optional custom system prompt for this session.
        metadata: Optional additional metadata for the session.
    """

    user_id: UUID | None = Field(
        default=None,
        description="User identifier",
    )
    tenant_id: UUID | None = Field(
        default=None,
        description="Tenant identifier",
    )
    system_prompt: str | None = Field(
        default=None,
        max_length=4000,
        description="Custom system prompt for this session",
    )
    metadata: dict | None = Field(
        default=None,
        description="Additional metadata for the session",
    )
