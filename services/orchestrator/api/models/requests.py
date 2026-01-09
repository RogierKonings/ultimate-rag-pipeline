"""Request models for the Orchestrator API."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    session_id: Optional[UUID] = Field(
        default=None,
        description="Session ID for conversation continuity",
    )
    user_id: Optional[UUID] = Field(
        default=None,
        description="User identifier for ACL filtering",
    )
    tenant_id: Optional[UUID] = Field(
        default=None,
        description="Tenant identifier for multi-tenancy",
    )
    options: Optional[dict] = Field(
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
    session_id: Optional[UUID] = Field(
        default=None,
        description="Session ID for conversation continuity",
    )
    user_id: Optional[UUID] = Field(
        default=None,
        description="User identifier for ACL filtering",
    )
    tenant_id: Optional[UUID] = Field(
        default=None,
        description="Tenant identifier for multi-tenancy",
    )
    options: Optional[dict] = Field(
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
    comment: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional user comment",
    )
    session_id: Optional[UUID] = Field(
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

    user_id: Optional[UUID] = Field(
        default=None,
        description="User identifier",
    )
    tenant_id: Optional[UUID] = Field(
        default=None,
        description="Tenant identifier",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="Custom system prompt for this session",
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="Additional metadata for the session",
    )
