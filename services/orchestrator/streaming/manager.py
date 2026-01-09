"""Stream manager for orchestrating streaming responses.

This module provides the StreamManager class that coordinates streaming
LLM responses with proper event sequencing and error handling.
"""

import time
from typing import Any, AsyncGenerator, Optional

from gateway.client import ModelGateway
from gateway.exceptions import ModelGatewayError
from gateway.models import ChatCompletionRequest, ChatMessage

from .buffer import TokenBuffer
from .models import StreamEvent, StreamEventType


class StreamManager:
    """Manager for streaming LLM responses with SSE events.

    This class orchestrates the streaming of LLM responses, emitting
    properly sequenced events for clients consuming the SSE stream.

    Event sequence:
        1. START - Stream metadata (request_id, model, session_id)
        2. DELTA* - Zero or more token chunks
        3. CITATIONS - Source documents (if RAG context provided)
        4. DONE - Completion with usage statistics

    On error, an ERROR event is emitted instead of subsequent events.

    Attributes:
        gateway: The model gateway for LLM requests.
        buffer: Token buffer for batching small tokens.

    Example:
        ```python
        manager = StreamManager(gateway=gateway)

        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hello"}],
        ):
            yield event.to_sse()
        ```
    """

    def __init__(
        self,
        gateway: Optional[ModelGateway] = None,
        buffer: Optional[TokenBuffer] = None,
    ) -> None:
        """Initialize the stream manager.

        Args:
            gateway: The model gateway for LLM requests.
                If None, a gateway must be provided to stream_response.
            buffer: Token buffer for batching. If None, no buffering is applied.
        """
        self._gateway = gateway
        self._buffer = buffer

    async def stream_response(
        self,
        request_id: str,
        model: str,
        messages: list[dict[str, Any]],
        session_id: Optional[str] = None,
        documents: Optional[list[dict[str, Any]]] = None,
        gateway: Optional[ModelGateway] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream an LLM response with proper event sequencing.

        This method handles the complete streaming lifecycle:
        1. Emits a START event with metadata
        2. Streams tokens as DELTA events
        3. Emits CITATIONS if documents are provided
        4. Emits DONE with usage statistics

        On error, emits an ERROR event and stops.

        Args:
            request_id: Unique identifier for this request.
            model: The model to use for generation.
            messages: List of chat messages in OpenAI format.
            session_id: Optional session identifier.
            documents: Optional list of source documents for citations.
            gateway: Optional gateway override (uses instance gateway if None).

        Yields:
            StreamEvent objects in the proper sequence.

        Raises:
            ValueError: If no gateway is available.

        Example:
            ```python
            async for event in manager.stream_response(
                request_id="req-123",
                model="llama",
                messages=[{"role": "user", "content": "Hello!"}],
                documents=[{"title": "Doc", "uri": "doc.md", "chunk_id": "1"}],
            ):
                print(event.to_sse())
            ```
        """
        # Use provided gateway or instance gateway
        active_gateway = gateway or self._gateway
        if active_gateway is None:
            raise ValueError("No gateway provided for streaming")

        start_time = time.perf_counter()
        usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # Emit start event
        yield self._create_start_event(request_id, model, session_id)

        try:
            # Convert messages to ChatMessage objects
            chat_messages = [
                ChatMessage(role=msg["role"], content=msg["content"])
                for msg in messages
            ]

            # Create chat completion request
            request = ChatCompletionRequest(
                model=model,
                messages=chat_messages,
                stream=True,
            )

            # Stream tokens from gateway
            token_count = 0
            async for token in active_gateway.chat_completion_stream(request):
                token_count += 1

                # Apply buffering if configured
                if self._buffer is not None:
                    buffered = self._buffer.add(token)
                    if buffered is not None:
                        yield self._create_delta_event(request_id, buffered)
                else:
                    yield self._create_delta_event(request_id, token)

            # Flush any remaining buffered content
            if self._buffer is not None:
                remaining = self._buffer.flush()
                if remaining is not None:
                    yield self._create_delta_event(request_id, remaining)

            # Estimate token usage (actual values would come from gateway response)
            usage["completion_tokens"] = token_count
            # Estimate prompt tokens based on message length
            prompt_chars = sum(len(msg["content"]) for msg in messages)
            usage["prompt_tokens"] = max(1, prompt_chars // 4)  # Rough estimate
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

            # Emit citations if documents provided
            if documents:
                yield self._create_citations_event(request_id, documents)

            # Emit done event
            latency_ms = (time.perf_counter() - start_time) * 1000
            yield self._create_done_event(request_id, usage, latency_ms)

        except ModelGatewayError as e:
            yield self._create_error_event(
                request_id=request_id,
                error=str(e),
                code=e.__class__.__name__,
            )
        except Exception as e:
            yield self._create_error_event(
                request_id=request_id,
                error=str(e),
                code="INTERNAL_ERROR",
            )

    def _create_start_event(
        self,
        request_id: str,
        model: str,
        session_id: Optional[str],
    ) -> StreamEvent:
        """Create a start event.

        Args:
            request_id: Unique request identifier.
            model: The model being used.
            session_id: Optional session identifier.

        Returns:
            A StreamEvent with START type.
        """
        return StreamEvent.start(request_id, model, session_id)

    def _create_delta_event(self, request_id: str, token: str) -> StreamEvent:
        """Create a delta event with a token.

        Args:
            request_id: Unique request identifier.
            token: The generated token.

        Returns:
            A StreamEvent with DELTA type.
        """
        return StreamEvent.delta(request_id, token)

    def _create_citations_event(
        self,
        request_id: str,
        documents: list[dict[str, Any]],
    ) -> StreamEvent:
        """Create a citations event.

        Transforms documents into a list of source references.

        Args:
            request_id: Unique request identifier.
            documents: List of source documents.

        Returns:
            A StreamEvent with CITATIONS type.
        """
        # Transform documents to citation format
        sources = []
        for doc in documents:
            source = {
                "title": doc.get("title") or doc.get("metadata", {}).get("title", ""),
                "uri": doc.get("uri") or doc.get("source", ""),
                "chunk_id": doc.get("chunk_id") or doc.get("id", ""),
            }
            sources.append(source)

        return StreamEvent.citations(request_id, sources)

    def _create_done_event(
        self,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
    ) -> StreamEvent:
        """Create a done event.

        Args:
            request_id: Unique request identifier.
            usage: Token usage statistics.
            latency_ms: Total latency in milliseconds.

        Returns:
            A StreamEvent with DONE type.
        """
        return StreamEvent.done(request_id, usage, latency_ms)

    def _create_error_event(
        self,
        request_id: str,
        error: str,
        code: str,
        recoverable: bool = False,
    ) -> StreamEvent:
        """Create an error event.

        Args:
            request_id: Unique request identifier.
            error: Human-readable error message.
            code: Machine-readable error code.
            recoverable: Whether the client can retry.

        Returns:
            A StreamEvent with ERROR type.
        """
        return StreamEvent.error(request_id, error, code, recoverable)
