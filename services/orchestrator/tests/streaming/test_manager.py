"""Tests for stream manager.

This module tests the StreamManager class for orchestrating streaming LLM responses.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gateway.client import ModelGateway
from gateway.exceptions import (
    ModelGatewayError,
    ModelTimeoutError,
    RateLimitError,
)
from streaming.buffer import TokenBuffer
from streaming.manager import StreamManager
from streaming.models import StreamEvent, StreamEventType


class TestStreamManagerInit:
    """Tests for StreamManager initialization."""

    def test_init_with_gateway(self):
        """Test initialization with gateway."""
        gateway = MagicMock(spec=ModelGateway)
        manager = StreamManager(gateway=gateway)
        assert manager._gateway is gateway

    def test_init_without_gateway(self):
        """Test initialization without gateway."""
        manager = StreamManager()
        assert manager._gateway is None

    def test_init_with_buffer(self):
        """Test initialization with buffer."""
        buffer = TokenBuffer(min_tokens=3)
        manager = StreamManager(buffer=buffer)
        assert manager._buffer is buffer

    def test_init_with_both(self):
        """Test initialization with both gateway and buffer."""
        gateway = MagicMock(spec=ModelGateway)
        buffer = TokenBuffer(min_tokens=5)
        manager = StreamManager(gateway=gateway, buffer=buffer)
        assert manager._gateway is gateway
        assert manager._buffer is buffer


class TestStreamManagerStreamResponse:
    """Tests for StreamManager.stream_response() method."""

    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway that yields tokens."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            tokens = ["Hello", " ", "World", "!"]
            for token in tokens:
                yield token

        gateway.chat_completion_stream = mock_stream
        return gateway

    @pytest.fixture
    def manager(self, mock_gateway):
        """Create a StreamManager with mock gateway."""
        return StreamManager(gateway=mock_gateway)

    @pytest.mark.asyncio
    async def test_stream_response_yields_start_event(self, manager):
        """Test that stream_response yields a start event first."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)
            if event.event == StreamEventType.START:
                break

        assert len(events) >= 1
        assert events[0].event == StreamEventType.START
        assert events[0].data["request_id"] == "req-123"
        assert events[0].data["model"] == "llama"

    @pytest.mark.asyncio
    async def test_stream_response_yields_delta_events(self, manager):
        """Test that stream_response yields delta events for tokens."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)

        delta_events = [e for e in events if e.event == StreamEventType.DELTA]
        assert len(delta_events) > 0

        # Verify content is preserved
        content = "".join(e.data["token"] for e in delta_events)
        assert content == "Hello World!"

    @pytest.mark.asyncio
    async def test_stream_response_yields_done_event(self, manager):
        """Test that stream_response yields a done event at the end."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)

        # Last event should be done
        assert events[-1].event == StreamEventType.DONE
        assert "usage" in events[-1].data
        assert "latency_ms" in events[-1].data

    @pytest.mark.asyncio
    async def test_stream_response_event_order(self, manager):
        """Test that events are in correct order: START, DELTA*, DONE."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)

        # First event is START
        assert events[0].event == StreamEventType.START

        # Last event is DONE
        assert events[-1].event == StreamEventType.DONE

        # Middle events are DELTA
        for event in events[1:-1]:
            assert event.event == StreamEventType.DELTA

    @pytest.mark.asyncio
    async def test_stream_response_with_session_id(self, manager):
        """Test stream_response includes session_id in start event."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
            session_id="sess-456",
        ):
            events.append(event)
            if event.event == StreamEventType.START:
                break

        assert events[0].data["session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_stream_response_without_session_id(self, manager):
        """Test stream_response without session_id."""
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)
            if event.event == StreamEventType.START:
                break

        assert events[0].data["session_id"] is None


class TestStreamManagerWithCitations:
    """Tests for StreamManager with citations."""

    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            yield "Response"

        gateway.chat_completion_stream = mock_stream
        return gateway

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents for citations."""
        return [
            {"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"},
            {"title": "Doc 2", "uri": "doc2.md", "chunk_id": "c2"},
        ]

    @pytest.mark.asyncio
    async def test_stream_response_with_documents(self, mock_gateway, sample_documents):
        """Test that citations event is emitted when documents provided."""
        manager = StreamManager(gateway=mock_gateway)
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
            documents=sample_documents,
        ):
            events.append(event)

        # Find citations event
        citations_events = [e for e in events if e.event == StreamEventType.CITATIONS]
        assert len(citations_events) == 1

        sources = citations_events[0].data["sources"]
        assert len(sources) == 2
        assert sources[0]["title"] == "Doc 1"

    @pytest.mark.asyncio
    async def test_stream_response_without_documents(self, mock_gateway):
        """Test that no citations event when no documents."""
        manager = StreamManager(gateway=mock_gateway)
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)

        citations_events = [e for e in events if e.event == StreamEventType.CITATIONS]
        assert len(citations_events) == 0

    @pytest.mark.asyncio
    async def test_citations_event_order(self, mock_gateway, sample_documents):
        """Test that citations event comes after deltas but before done."""
        manager = StreamManager(gateway=mock_gateway)
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
            documents=sample_documents,
        ):
            events.append(event)

        event_types = [e.event for e in events]

        # Order: START, DELTA*, CITATIONS, DONE
        citations_idx = event_types.index(StreamEventType.CITATIONS)
        done_idx = event_types.index(StreamEventType.DONE)

        assert citations_idx < done_idx  # Citations before done


class TestStreamManagerWithBuffer:
    """Tests for StreamManager with token buffering."""

    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway that yields many small tokens."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            tokens = ["H", "e", "l", "l", "o", " ", "W", "o", "r", "l", "d"]
            for token in tokens:
                yield token

        gateway.chat_completion_stream = mock_stream
        return gateway

    @pytest.mark.asyncio
    async def test_buffering_reduces_delta_events(self, mock_gateway):
        """Test that buffering reduces the number of delta events."""
        # Without buffer
        manager_no_buffer = StreamManager(gateway=mock_gateway)
        events_no_buffer = []
        async for event in manager_no_buffer.stream_response(
            request_id="req-1",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events_no_buffer.append(event)

        # With buffer (batch every 3 tokens)
        buffer = TokenBuffer(min_tokens=3, max_wait_ms=10000.0)
        manager_with_buffer = StreamManager(gateway=mock_gateway, buffer=buffer)
        events_with_buffer = []
        async for event in manager_with_buffer.stream_response(
            request_id="req-2",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events_with_buffer.append(event)

        deltas_no_buffer = [e for e in events_no_buffer if e.event == StreamEventType.DELTA]
        deltas_with_buffer = [e for e in events_with_buffer if e.event == StreamEventType.DELTA]

        # Buffer should result in fewer delta events
        assert len(deltas_with_buffer) < len(deltas_no_buffer)

    @pytest.mark.asyncio
    async def test_buffered_content_preserved(self, mock_gateway):
        """Test that all content is preserved with buffering."""
        buffer = TokenBuffer(min_tokens=3, max_wait_ms=10000.0)
        manager = StreamManager(gateway=mock_gateway, buffer=buffer)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events.append(event)

        delta_events = [e for e in events if e.event == StreamEventType.DELTA]
        content = "".join(e.data["token"] for e in delta_events)

        assert content == "Hello World"


class TestStreamManagerErrorHandling:
    """Tests for StreamManager error handling."""

    @pytest.mark.asyncio
    async def test_no_gateway_raises_error(self):
        """Test that missing gateway raises ValueError."""
        manager = StreamManager()  # No gateway
        messages = [{"role": "user", "content": "Hello"}]

        with pytest.raises(ValueError, match="No gateway provided"):
            async for _ in manager.stream_response(
                request_id="req-123",
                model="llama",
                messages=messages,
            ):
                pass

    @pytest.mark.asyncio
    async def test_gateway_override(self):
        """Test that gateway can be overridden per request."""
        override_gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            yield "Override"

        override_gateway.chat_completion_stream = mock_stream

        manager = StreamManager()  # No default gateway

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
            gateway=override_gateway,
        ):
            events.append(event)

        # Should succeed with override gateway
        delta_events = [e for e in events if e.event == StreamEventType.DELTA]
        assert len(delta_events) == 1
        assert delta_events[0].data["token"] == "Override"

    @pytest.mark.asyncio
    async def test_gateway_error_yields_error_event(self):
        """Test that gateway errors yield error events."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            raise ModelGatewayError("Connection failed")
            yield  # Make it a generator

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)
        messages = [{"role": "user", "content": "Hello"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=messages,
        ):
            events.append(event)

        # Should have start event and error event
        assert events[0].event == StreamEventType.START
        assert events[-1].event == StreamEventType.ERROR
        assert "Connection failed" in events[-1].data["error"]

    @pytest.mark.asyncio
    async def test_timeout_error_yields_error_event(self):
        """Test that timeout errors yield error events."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            raise ModelTimeoutError("Request timed out")
            yield

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events.append(event)

        error_event = events[-1]
        assert error_event.event == StreamEventType.ERROR
        assert error_event.data["code"] == "ModelTimeoutError"

    @pytest.mark.asyncio
    async def test_rate_limit_error_yields_error_event(self):
        """Test that rate limit errors yield error events."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            raise RateLimitError("Rate limit exceeded")
            yield

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events.append(event)

        error_event = events[-1]
        assert error_event.event == StreamEventType.ERROR
        assert "rate limit" in error_event.data["error"].lower()

    @pytest.mark.asyncio
    async def test_generic_exception_yields_error_event(self):
        """Test that generic exceptions yield error events."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            raise RuntimeError("Unexpected error")
            yield

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events.append(event)

        error_event = events[-1]
        assert error_event.event == StreamEventType.ERROR
        assert error_event.data["code"] == "INTERNAL_ERROR"


class TestStreamManagerUsageStats:
    """Tests for StreamManager usage statistics."""

    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            for token in ["One", " Two", " Three"]:
                yield token

        gateway.chat_completion_stream = mock_stream
        return gateway

    @pytest.mark.asyncio
    async def test_done_event_includes_usage(self, mock_gateway):
        """Test that done event includes usage statistics."""
        manager = StreamManager(gateway=mock_gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hello World"}],
        ):
            events.append(event)

        done_event = events[-1]
        assert done_event.event == StreamEventType.DONE
        assert "usage" in done_event.data
        assert "prompt_tokens" in done_event.data["usage"]
        assert "completion_tokens" in done_event.data["usage"]
        assert "total_tokens" in done_event.data["usage"]

    @pytest.mark.asyncio
    async def test_done_event_includes_latency(self, mock_gateway):
        """Test that done event includes latency."""
        manager = StreamManager(gateway=mock_gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            events.append(event)

        done_event = events[-1]
        assert done_event.data["latency_ms"] > 0


class TestStreamManagerIntegration:
    """Integration tests for StreamManager."""

    @pytest.mark.asyncio
    async def test_full_stream_flow(self):
        """Test complete streaming flow with all event types."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            for token in ["Based on the documents, ", "Python is great."]:
                yield token

        gateway.chat_completion_stream = mock_stream

        documents = [
            {"title": "Python Intro", "uri": "intro.md", "chunk_id": "c1"},
        ]

        manager = StreamManager(gateway=gateway)

        events = []
        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "What is Python?"}],
            session_id="sess-456",
            documents=documents,
        ):
            events.append(event)

        # Verify event sequence
        event_types = [e.event for e in events]
        assert event_types[0] == StreamEventType.START
        assert StreamEventType.DELTA in event_types
        assert StreamEventType.CITATIONS in event_types
        assert event_types[-1] == StreamEventType.DONE

    @pytest.mark.asyncio
    async def test_sse_output_format(self):
        """Test that all events produce valid SSE output."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            yield "Test response"

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)

        async for event in manager.stream_response(
            request_id="req-123",
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            sse = event.to_sse()

            # Verify SSE format
            assert sse.startswith("event: ")
            assert "\ndata: " in sse
            assert sse.endswith("\n\n")

    @pytest.mark.asyncio
    async def test_request_id_consistency(self):
        """Test that all events have consistent request_id."""
        gateway = MagicMock(spec=ModelGateway)

        async def mock_stream(request):
            yield "Response"

        gateway.chat_completion_stream = mock_stream

        manager = StreamManager(gateway=gateway)
        request_id = "unique-req-id-12345"

        async for event in manager.stream_response(
            request_id=request_id,
            model="llama",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            assert event.request_id == request_id
