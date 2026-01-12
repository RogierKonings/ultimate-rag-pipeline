"""Response models for the Orchestrator API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SourceDocument(BaseModel):
    """Source document included in query response.

    Attributes:
        id: Document/chunk identifier.
        title: Document title.
        uri: Source URI or path.
        score: Relevance score.
        snippet: Content snippet used in context.
    """

    id: str = Field(..., description="Document/chunk identifier")
    title: str | None = Field(default=None, description="Document title")
    uri: str | None = Field(default=None, description="Source URI or path")
    score: float | None = Field(default=None, description="Relevance score")
    snippet: str | None = Field(default=None, description="Content snippet")


class UsageInfo(BaseModel):
    """Token usage information.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Total token count.
    """

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens used")


class QueryResponse(BaseModel):
    """Response model for synchronous RAG query.

    Attributes:
        request_id: Unique identifier for this request.
        response: The generated response text.
        sources: List of source documents used.
        session_id: Session ID if conversation tracking is enabled.
        model: The model used for generation.
        usage: Token usage statistics.
        latency_ms: Response latency in milliseconds.
        strategy_used: The retrieval strategy used (simple, rerank, etc.).
    """

    request_id: str = Field(..., description="Unique request identifier")
    response: str = Field(..., description="Generated response text")
    sources: list[SourceDocument] = Field(
        default_factory=list,
        description="Source documents used in response",
    )
    session_id: UUID | None = Field(
        default=None,
        description="Session ID for conversation tracking",
    )
    model: str = Field(..., description="Model used for generation")
    usage: UsageInfo = Field(
        default_factory=UsageInfo,
        description="Token usage statistics",
    )
    latency_ms: float = Field(default=0.0, description="Response latency in milliseconds")
    strategy_used: str | None = Field(
        default=None,
        description="Retrieval strategy used",
    )


class SessionInfo(BaseModel):
    """Session information model.

    Attributes:
        id: Session identifier.
        user_id: Optional user identifier.
        tenant_id: Optional tenant identifier.
        created_at: Session creation timestamp.
        updated_at: Last update timestamp.
        message_count: Number of messages in session.
        total_tokens: Total tokens used in session.
    """

    id: UUID = Field(..., description="Session identifier")
    user_id: UUID | None = Field(default=None, description="User identifier")
    tenant_id: UUID | None = Field(default=None, description="Tenant identifier")
    created_at: datetime = Field(..., description="Session creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    message_count: int = Field(default=0, description="Number of messages")
    total_tokens: int = Field(default=0, description="Total tokens used")


class SessionResponse(BaseModel):
    """Response model for session operations.

    Attributes:
        session: Session information.
        message: Optional status message.
    """

    session: SessionInfo = Field(..., description="Session information")
    message: str | None = Field(default=None, description="Status message")


class MessageInfo(BaseModel):
    """Message information model.

    Attributes:
        id: Message identifier.
        role: Message role (user, assistant, system).
        content: Message content.
        timestamp: Message timestamp.
        sources: Optional source references for assistant messages.
    """

    id: UUID = Field(..., description="Message identifier")
    role: str = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")
    sources: list[str] | None = Field(
        default=None,
        description="Source references for assistant messages",
    )


class HistoryResponse(BaseModel):
    """Response model for session history.

    Attributes:
        session_id: Session identifier.
        messages: List of messages in the session.
        has_summary: Whether the session has been summarized.
        summary: Optional summary of earlier messages.
    """

    session_id: UUID = Field(..., description="Session identifier")
    messages: list[MessageInfo] = Field(
        default_factory=list,
        description="Messages in the session",
    )
    has_summary: bool = Field(default=False, description="Whether session is summarized")
    summary: str | None = Field(
        default=None,
        description="Summary of earlier messages",
    )


class ComponentHealth(BaseModel):
    """Health status of a single component.

    Attributes:
        name: Component name.
        status: Health status (healthy, degraded, unhealthy).
        latency_ms: Optional latency measurement.
        message: Optional status message.
    """

    name: str = Field(..., description="Component name")
    status: str = Field(..., description="Health status")
    latency_ms: float | None = Field(default=None, description="Latency in ms")
    message: str | None = Field(default=None, description="Status message")


class HealthResponse(BaseModel):
    """Response model for health check endpoints.

    Attributes:
        status: Overall health status.
        service: Service name.
        version: Service version.
        uptime_seconds: Service uptime in seconds.
        components: Health status of individual components.
        timestamp: Health check timestamp.
    """

    status: str = Field(..., description="Overall health status")
    service: str = Field(default="orchestrator-service", description="Service name")
    version: str = Field(default="1.0.0", description="Service version")
    uptime_seconds: float = Field(default=0.0, description="Service uptime")
    components: list[ComponentHealth] = Field(
        default_factory=list,
        description="Component health status",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Health check timestamp",
    )


class ErrorDetail(BaseModel):
    """Detailed error information.

    Attributes:
        field: Optional field that caused the error.
        message: Error message.
        code: Error code.
    """

    field: str | None = Field(default=None, description="Field causing error")
    message: str = Field(..., description="Error message")
    code: str | None = Field(default=None, description="Error code")


class ErrorResponse(BaseModel):
    """Response model for error responses.

    Attributes:
        error: Error type/name.
        message: Human-readable error message.
        request_id: Optional request identifier.
        details: Optional detailed error information.
        timestamp: Error timestamp.
    """

    error: str = Field(..., description="Error type/name")
    message: str = Field(..., description="Human-readable error message")
    request_id: str | None = Field(default=None, description="Request identifier")
    details: list[ErrorDetail] | None = Field(
        default=None,
        description="Detailed error information",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp",
    )


class FeedbackResponse(BaseModel):
    """Response model for feedback submission.

    Attributes:
        success: Whether feedback was recorded successfully.
        message: Status message.
        feedback_id: Optional identifier for the recorded feedback.
    """

    success: bool = Field(..., description="Whether feedback was recorded")
    message: str = Field(..., description="Status message")
    feedback_id: str | None = Field(
        default=None,
        description="Identifier for recorded feedback",
    )


class ClearSessionResponse(BaseModel):
    """Response model for clearing a session.

    Attributes:
        success: Whether session was cleared successfully.
        session_id: Session identifier that was cleared.
        message: Status message.
    """

    success: bool = Field(..., description="Whether session was cleared")
    session_id: UUID = Field(..., description="Cleared session identifier")
    message: str = Field(..., description="Status message")


class DeleteSessionResponse(BaseModel):
    """Response model for deleting a session.

    Attributes:
        success: Whether session was deleted successfully.
        session_id: Session identifier that was deleted.
        message: Status message.
    """

    success: bool = Field(..., description="Whether session was deleted")
    session_id: UUID = Field(..., description="Deleted session identifier")
    message: str = Field(..., description="Status message")
