"""Streaming event models for Server-Sent Events (SSE) support.

This module defines the data models for streaming responses, following
the SSE protocol for real-time token delivery to clients.
"""

import json
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StreamEventType(str, Enum):
    """Types of streaming events.

    Attributes:
        START: Stream started, includes metadata about the request.
        DELTA: Token chunk containing generated content.
        CITATIONS: Source citations for RAG responses.
        DONE: Stream complete, includes usage statistics.
        ERROR: Error occurred during streaming.
    """

    START = "start"
    DELTA = "delta"
    CITATIONS = "citations"
    DONE = "done"
    ERROR = "error"


class StartEventData(BaseModel):
    """Data payload for stream start events.

    Attributes:
        request_id: Unique identifier for this request.
        model: The model being used for generation.
        session_id: Optional session identifier for conversation tracking.
        degradation: Optional degradation info if service is degraded (US-10.2.2).
    """

    request_id: str
    model: str
    session_id: str | None = None
    degradation: dict[str, Any] | None = None  # {level, mode, message}


class DeltaEventData(BaseModel):
    """Data payload for token delta events.

    Attributes:
        token: The generated token or token chunk.
    """

    token: str


class CitationsEventData(BaseModel):
    """Data payload for citation events.

    Attributes:
        sources: List of source documents with metadata.
            Each source contains title, uri, and chunk_id.
    """

    sources: list[dict[str, Any]]


class DoneEventData(BaseModel):
    """Data payload for stream completion events.

    Attributes:
        request_id: Unique identifier for the completed request.
        usage: Token usage statistics with prompt_tokens,
            completion_tokens, and total_tokens.
        latency_ms: Total response latency in milliseconds.
        context_quality: Quality of retrieved context (US-10.2.2).
        retrieval_mode: The retrieval mode used (US-10.2.2).
    """

    request_id: str
    usage: dict[str, int]
    latency_ms: float
    context_quality: str = "full"  # "full", "partial", "minimal"
    retrieval_mode: str = "hybrid_full"  # The retrieval mode used


class ErrorEventData(BaseModel):
    """Data payload for error events.

    Attributes:
        error: Human-readable error message.
        code: Machine-readable error code.
        recoverable: Whether the client can retry the request.
    """

    error: str
    code: str
    recoverable: bool


class StreamEvent(BaseModel):
    """A streaming event following SSE protocol.

    This model represents a single event in the streaming response,
    with methods to convert to SSE wire format.

    Attributes:
        event: The type of event.
        data: Event-specific payload data.
        request_id: Unique identifier for the request.
        timestamp: Unix timestamp when the event was created.

    Example:
        ```python
        event = StreamEvent(
            event=StreamEventType.DELTA,
            data={"token": "Hello"},
            request_id="req-123"
        )
        sse_str = event.to_sse()
        # Returns: "event: delta\\ndata: {\\"token\\": \\"Hello\\", ...}\\n\\n"
        ```
    """

    event: StreamEventType
    data: dict[str, Any]
    request_id: str
    timestamp: float = Field(default_factory=lambda: time.time())

    def to_sse(self) -> str:
        """Convert the event to SSE wire format.

        Returns:
            SSE-formatted string with event type, data, and double newline.

        Example:
            ```python
            event = StreamEvent(
                event=StreamEventType.START,
                data={"request_id": "123", "model": "llama"},
                request_id="123"
            )
            print(event.to_sse())
            # event: start
            # data: {"request_id": "123", "model": "llama", ...}
            #
            ```
        """
        data_with_meta = {
            **self.data,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }
        return f"event: {self.event.value}\ndata: {json.dumps(data_with_meta)}\n\n"

    @classmethod
    def start(
        cls,
        request_id: str,
        model: str,
        session_id: str | None = None,
        degradation: dict[str, Any] | None = None,
    ) -> "StreamEvent":
        """Create a start event.

        Args:
            request_id: Unique request identifier.
            model: The model being used.
            session_id: Optional session identifier.
            degradation: Optional degradation info (US-10.2.2).

        Returns:
            A new StreamEvent with START type.
        """
        data = StartEventData(
            request_id=request_id,
            model=model,
            session_id=session_id,
            degradation=degradation,
        )
        return cls(
            event=StreamEventType.START,
            data=data.model_dump(),
            request_id=request_id,
        )

    @classmethod
    def delta(cls, request_id: str, token: str) -> "StreamEvent":
        """Create a delta event with a token.

        Args:
            request_id: Unique request identifier.
            token: The generated token.

        Returns:
            A new StreamEvent with DELTA type.
        """
        data = DeltaEventData(token=token)
        return cls(
            event=StreamEventType.DELTA,
            data=data.model_dump(),
            request_id=request_id,
        )

    @classmethod
    def citations(
        cls,
        request_id: str,
        sources: list[dict[str, Any]],
    ) -> "StreamEvent":
        """Create a citations event.

        Args:
            request_id: Unique request identifier.
            sources: List of source documents.

        Returns:
            A new StreamEvent with CITATIONS type.
        """
        data = CitationsEventData(sources=sources)
        return cls(
            event=StreamEventType.CITATIONS,
            data=data.model_dump(),
            request_id=request_id,
        )

    @classmethod
    def done(
        cls,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
        context_quality: str = "full",
        retrieval_mode: str = "hybrid_full",
    ) -> "StreamEvent":
        """Create a done event.

        Args:
            request_id: Unique request identifier.
            usage: Token usage statistics.
            latency_ms: Total latency in milliseconds.
            context_quality: Quality of retrieved context (US-10.2.2).
            retrieval_mode: The retrieval mode used (US-10.2.2).

        Returns:
            A new StreamEvent with DONE type.
        """
        data = DoneEventData(
            request_id=request_id,
            usage=usage,
            latency_ms=latency_ms,
            context_quality=context_quality,
            retrieval_mode=retrieval_mode,
        )
        return cls(
            event=StreamEventType.DONE,
            data=data.model_dump(),
            request_id=request_id,
        )

    @classmethod
    def error(
        cls,
        request_id: str,
        error: str,
        code: str,
        recoverable: bool = False,
    ) -> "StreamEvent":
        """Create an error event.

        Args:
            request_id: Unique request identifier.
            error: Human-readable error message.
            code: Machine-readable error code.
            recoverable: Whether the client can retry.

        Returns:
            A new StreamEvent with ERROR type.
        """
        data = ErrorEventData(
            error=error,
            code=code,
            recoverable=recoverable,
        )
        return cls(
            event=StreamEventType.ERROR,
            data=data.model_dump(),
            request_id=request_id,
        )
