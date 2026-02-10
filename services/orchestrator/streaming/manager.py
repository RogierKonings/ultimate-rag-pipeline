"""Stream manager for orchestrating streaming responses.

This module provides the StreamManager class that coordinates streaming
LLM responses with proper event sequencing and error handling.
"""

import re
import time
from collections.abc import AsyncGenerator
from typing import Any

from gateway.client import ModelGateway
from gateway.exceptions import ModelGatewayError
from gateway.models import ChatCompletionRequest, ChatMessage

from .buffer import TokenBuffer
from .models import StreamEvent


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
        gateway: ModelGateway | None = None,
        buffer: TokenBuffer | None = None,
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
        session_id: str | None = None,
        documents: list[dict[str, Any]] | None = None,
        gateway: ModelGateway | None = None,
        degradation: dict[str, Any] | None = None,
        retrieval_quality: dict[str, Any] | None = None,
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
            degradation: Optional degradation info for start event (US-10.2.2).
                Contains level, mode, and message fields.
            retrieval_quality: Optional retrieval quality info for done event (US-10.2.2).
                Contains mode and degradation_level fields.

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

        # Emit start event (with degradation info if provided)
        yield self._create_start_event(request_id, model, session_id, degradation)

        try:
            # Convert messages to ChatMessage objects
            chat_messages = [
                ChatMessage(role=msg["role"], content=msg["content"]) for msg in messages
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

            # Emit citations if documents provided (preserve original order to
            # keep [N] markers in the response aligned with source positions)
            if documents:
                yield self._create_citations_event(request_id, documents)

            # Emit done event (with quality metadata if provided)
            latency_ms = (time.perf_counter() - start_time) * 1000
            context_quality = "full"
            retrieval_mode = "hybrid_full"
            if retrieval_quality:
                # Map degradation level to context quality
                degradation_level = retrieval_quality.get("degradation_level", "normal")
                if degradation_level == "normal":
                    context_quality = "full"
                elif degradation_level == "degraded":
                    context_quality = "partial"
                elif degradation_level == "minimal":
                    context_quality = "minimal"
                retrieval_mode = retrieval_quality.get("mode", "hybrid_full")
            yield self._create_done_event(
                request_id, usage, latency_ms, context_quality, retrieval_mode
            )

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
        session_id: str | None,
        degradation: dict[str, Any] | None = None,
    ) -> StreamEvent:
        """Create a start event.

        Args:
            request_id: Unique request identifier.
            model: The model being used.
            session_id: Optional session identifier.
            degradation: Optional degradation info (US-10.2.2).

        Returns:
            A StreamEvent with START type.
        """
        return StreamEvent.start(request_id, model, session_id, degradation)

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

    @staticmethod
    def _reorder_documents_by_citations(
        response_text: str,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reorder documents so cited sources appear first.

        Parses [N] citation markers from the response and moves cited
        documents to the front (in order of first citation).

        Args:
            response_text: The full generated response text.
            documents: Source documents in retrieval order.

        Returns:
            Reordered documents with cited ones first.
        """
        if not documents or not response_text:
            return documents

        citation_matches = re.findall(r"\[(\d+)\]", response_text)
        seen: set[int] = set()
        cited_indices: list[int] = []
        for match in citation_matches:
            idx = int(match) - 1
            if 0 <= idx < len(documents) and idx not in seen:
                seen.add(idx)
                cited_indices.append(idx)

        if not cited_indices:
            return documents

        reordered = [documents[i] for i in cited_indices]
        for i, doc in enumerate(documents):
            if i not in seen:
                reordered.append(doc)
        return reordered

    def _create_done_event(
        self,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
        context_quality: str = "full",
        retrieval_mode: str = "hybrid_full",
    ) -> StreamEvent:
        """Create a done event.

        Args:
            request_id: Unique request identifier.
            usage: Token usage statistics.
            latency_ms: Total latency in milliseconds.
            context_quality: Quality of retrieved context (US-10.2.2).
            retrieval_mode: The retrieval mode used (US-10.2.2).

        Returns:
            A StreamEvent with DONE type.
        """
        return StreamEvent.done(request_id, usage, latency_ms, context_quality, retrieval_mode)

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
