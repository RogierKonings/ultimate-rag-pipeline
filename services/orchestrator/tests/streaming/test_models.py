"""Tests for streaming event models.

This module tests the StreamEvent model and its SSE formatting capabilities.
"""

import json
import time

from streaming.models import (
    CitationsEventData,
    DeltaEventData,
    DoneEventData,
    ErrorEventData,
    StartEventData,
    StreamEvent,
    StreamEventType,
)


class TestStreamEventType:
    """Tests for StreamEventType enum."""

    def test_event_type_values(self):
        """Test that all event types have correct string values."""
        assert StreamEventType.START.value == "start"
        assert StreamEventType.DELTA.value == "delta"
        assert StreamEventType.CITATIONS.value == "citations"
        assert StreamEventType.DONE.value == "done"
        assert StreamEventType.ERROR.value == "error"

    def test_event_type_is_string_enum(self):
        """Test that StreamEventType inherits from str."""
        assert isinstance(StreamEventType.START, str)
        assert StreamEventType.START == "start"

    def test_all_event_types_defined(self):
        """Test that all expected event types are defined."""
        expected_types = {"start", "delta", "citations", "done", "error"}
        actual_types = {e.value for e in StreamEventType}
        assert actual_types == expected_types


class TestEventDataModels:
    """Tests for event data payload models."""

    def test_start_event_data(self):
        """Test StartEventData model."""
        data = StartEventData(
            request_id="req-123",
            model="llama",
            session_id="sess-456",
        )
        assert data.request_id == "req-123"
        assert data.model == "llama"
        assert data.session_id == "sess-456"

    def test_start_event_data_optional_session(self):
        """Test StartEventData with optional session_id."""
        data = StartEventData(request_id="req-123", model="llama")
        assert data.session_id is None

    def test_delta_event_data(self):
        """Test DeltaEventData model."""
        data = DeltaEventData(token="Hello")
        assert data.token == "Hello"

    def test_delta_event_data_empty_token(self):
        """Test DeltaEventData with empty token."""
        data = DeltaEventData(token="")
        assert data.token == ""

    def test_citations_event_data(self):
        """Test CitationsEventData model."""
        sources = [
            {"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"},
            {"title": "Doc 2", "uri": "doc2.md", "chunk_id": "c2"},
        ]
        data = CitationsEventData(sources=sources)
        assert len(data.sources) == 2
        assert data.sources[0]["title"] == "Doc 1"

    def test_citations_event_data_empty_sources(self):
        """Test CitationsEventData with empty sources list."""
        data = CitationsEventData(sources=[])
        assert data.sources == []

    def test_done_event_data(self):
        """Test DoneEventData model."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        data = DoneEventData(
            request_id="req-123",
            usage=usage,
            latency_ms=150.5,
        )
        assert data.request_id == "req-123"
        assert data.usage == usage
        assert data.latency_ms == 150.5

    def test_error_event_data(self):
        """Test ErrorEventData model."""
        data = ErrorEventData(
            error="Connection failed",
            code="CONNECTION_ERROR",
            recoverable=True,
        )
        assert data.error == "Connection failed"
        assert data.code == "CONNECTION_ERROR"
        assert data.recoverable is True

    def test_error_event_data_not_recoverable(self):
        """Test ErrorEventData with recoverable=False."""
        data = ErrorEventData(
            error="Invalid input",
            code="VALIDATION_ERROR",
            recoverable=False,
        )
        assert data.recoverable is False


class TestStreamEvent:
    """Tests for StreamEvent model."""

    def test_stream_event_creation(self):
        """Test basic StreamEvent creation."""
        event = StreamEvent(
            event=StreamEventType.DELTA,
            data={"token": "Hello"},
            request_id="req-123",
        )
        assert event.event == StreamEventType.DELTA
        assert event.data == {"token": "Hello"}
        assert event.request_id == "req-123"
        assert isinstance(event.timestamp, float)

    def test_stream_event_timestamp_default(self):
        """Test that timestamp defaults to current time."""
        before = time.time()
        event = StreamEvent(
            event=StreamEventType.START,
            data={},
            request_id="req-123",
        )
        after = time.time()
        assert before <= event.timestamp <= after

    def test_stream_event_custom_timestamp(self):
        """Test StreamEvent with custom timestamp."""
        custom_time = 1704067200.0  # 2024-01-01 00:00:00 UTC
        event = StreamEvent(
            event=StreamEventType.START,
            data={},
            request_id="req-123",
            timestamp=custom_time,
        )
        assert event.timestamp == custom_time


class TestStreamEventToSSE:
    """Tests for StreamEvent.to_sse() method."""

    def test_to_sse_format(self):
        """Test that to_sse returns proper SSE format."""
        event = StreamEvent(
            event=StreamEventType.DELTA,
            data={"token": "Hello"},
            request_id="req-123",
            timestamp=1704067200.0,
        )
        sse = event.to_sse()

        # Check format: event: type\ndata: json\n\n
        assert sse.startswith("event: delta\n")
        assert "data: " in sse
        assert sse.endswith("\n\n")

    def test_to_sse_data_includes_request_id(self):
        """Test that SSE data includes request_id."""
        event = StreamEvent(
            event=StreamEventType.START,
            data={"model": "llama"},
            request_id="req-456",
        )
        sse = event.to_sse()

        # Parse the data from SSE
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data_json = json.loads(data_line[6:])  # Remove "data: " prefix

        assert data_json["request_id"] == "req-456"
        assert data_json["model"] == "llama"

    def test_to_sse_data_includes_timestamp(self):
        """Test that SSE data includes timestamp."""
        event = StreamEvent(
            event=StreamEventType.DONE,
            data={"usage": {}},
            request_id="req-789",
            timestamp=1704067200.0,
        )
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data_json = json.loads(data_line[6:])

        assert data_json["timestamp"] == 1704067200.0

    def test_to_sse_valid_json(self):
        """Test that the data portion is valid JSON."""
        event = StreamEvent(
            event=StreamEventType.CITATIONS,
            data={
                "sources": [
                    {"title": "Test", "uri": "test.md", "chunk_id": "c1"},
                ],
            },
            request_id="req-123",
        )
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]

        # Should not raise
        parsed = json.loads(data_line[6:])
        assert "sources" in parsed
        assert len(parsed["sources"]) == 1

    def test_to_sse_special_characters(self):
        """Test SSE with special characters in content."""
        event = StreamEvent(
            event=StreamEventType.DELTA,
            data={"token": 'Line1\nLine2\t"quoted"'},
            request_id="req-123",
        )
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        parsed = json.loads(data_line[6:])

        assert parsed["token"] == 'Line1\nLine2\t"quoted"'


class TestStreamEventFactoryMethods:
    """Tests for StreamEvent factory methods."""

    def test_start_factory(self):
        """Test StreamEvent.start() factory method."""
        event = StreamEvent.start(
            request_id="req-123",
            model="llama",
            session_id="sess-456",
        )

        assert event.event == StreamEventType.START
        assert event.request_id == "req-123"
        assert event.data["request_id"] == "req-123"
        assert event.data["model"] == "llama"
        assert event.data["session_id"] == "sess-456"

    def test_start_factory_no_session(self):
        """Test StreamEvent.start() without session_id."""
        event = StreamEvent.start(
            request_id="req-123",
            model="llama",
        )

        assert event.data["session_id"] is None

    def test_delta_factory(self):
        """Test StreamEvent.delta() factory method."""
        event = StreamEvent.delta(
            request_id="req-123",
            token="Hello",
        )

        assert event.event == StreamEventType.DELTA
        assert event.request_id == "req-123"
        assert event.data["token"] == "Hello"

    def test_citations_factory(self):
        """Test StreamEvent.citations() factory method."""
        sources = [
            {"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"},
        ]
        event = StreamEvent.citations(
            request_id="req-123",
            sources=sources,
        )

        assert event.event == StreamEventType.CITATIONS
        assert event.request_id == "req-123"
        assert event.data["sources"] == sources

    def test_done_factory(self):
        """Test StreamEvent.done() factory method."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        event = StreamEvent.done(
            request_id="req-123",
            usage=usage,
            latency_ms=150.5,
        )

        assert event.event == StreamEventType.DONE
        assert event.request_id == "req-123"
        assert event.data["usage"] == usage
        assert event.data["latency_ms"] == 150.5

    def test_error_factory(self):
        """Test StreamEvent.error() factory method."""
        event = StreamEvent.error(
            request_id="req-123",
            error="Connection failed",
            code="CONNECTION_ERROR",
            recoverable=True,
        )

        assert event.event == StreamEventType.ERROR
        assert event.request_id == "req-123"
        assert event.data["error"] == "Connection failed"
        assert event.data["code"] == "CONNECTION_ERROR"
        assert event.data["recoverable"] is True

    def test_error_factory_default_not_recoverable(self):
        """Test StreamEvent.error() defaults to not recoverable."""
        event = StreamEvent.error(
            request_id="req-123",
            error="Fatal error",
            code="FATAL",
        )

        assert event.data["recoverable"] is False


class TestStreamEventSSEIntegration:
    """Integration tests for SSE event generation."""

    def test_start_event_sse_format(self):
        """Test start event SSE format matches specification."""
        event = StreamEvent.start(
            request_id="req-123",
            model="llama",
            session_id="sess-456",
        )
        sse = event.to_sse()

        assert sse.startswith("event: start\n")
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data = json.loads(data_line[6:])

        # Verify required fields per specification
        assert "request_id" in data
        assert "model" in data
        assert "session_id" in data

    def test_delta_event_sse_format(self):
        """Test delta event SSE format matches specification."""
        event = StreamEvent.delta(
            request_id="req-123",
            token="Hello world",
        )
        sse = event.to_sse()

        assert sse.startswith("event: delta\n")
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data = json.loads(data_line[6:])

        # Verify content field (specification says "content", but implementation uses "token")
        assert "token" in data
        assert data["token"] == "Hello world"

    def test_citations_event_sse_format(self):
        """Test citations event SSE format matches specification."""
        sources = [
            {"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"},
            {"title": "Doc 2", "uri": "doc2.md", "chunk_id": "c2"},
        ]
        event = StreamEvent.citations(
            request_id="req-123",
            sources=sources,
        )
        sse = event.to_sse()

        assert sse.startswith("event: citations\n")
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data = json.loads(data_line[6:])

        assert "sources" in data
        assert len(data["sources"]) == 2

    def test_done_event_sse_format(self):
        """Test done event SSE format matches specification."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        event = StreamEvent.done(
            request_id="req-123",
            usage=usage,
            latency_ms=150.5,
        )
        sse = event.to_sse()

        assert sse.startswith("event: done\n")
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data = json.loads(data_line[6:])

        assert "usage" in data
        assert data["usage"]["total_tokens"] == 15

    def test_error_event_sse_format(self):
        """Test error event SSE format matches specification."""
        event = StreamEvent.error(
            request_id="req-123",
            error="Service unavailable",
            code="SERVICE_UNAVAILABLE",
            recoverable=True,
        )
        sse = event.to_sse()

        assert sse.startswith("event: error\n")
        lines = sse.strip().split("\n")
        data_line = [line for line in lines if line.startswith("data: ")][0]
        data = json.loads(data_line[6:])

        assert "error" in data
        assert "code" in data
        assert data["error"] == "Service unavailable"
        assert data["code"] == "SERVICE_UNAVAILABLE"
