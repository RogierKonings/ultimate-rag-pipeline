"""Integration tests for streaming contract compliance.

This module tests end-to-end streaming scenarios to verify that the
streaming implementation conforms to the SSE contract specification.

Contract Requirements:
    - Event order: start -> delta* -> citations -> done (or error at any point)
    - Start event: {"request_id": "...", "model": "..."}
    - Delta event: {"token": "..."}
    - Citations event: {"sources": [...]}
    - Done event: {"usage": {...}, "latency_ms": N}
    - Error event: {"error": "message", "code": "ERROR_CODE", "recoverable": bool}
    - TTFT target: <500ms
"""

import asyncio
import json
import time
from typing import AsyncGenerator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streaming.manager import StreamManager
from streaming.metrics import StreamMetricsRecorder, TTFTTracker
from streaming.models import StreamEvent, StreamEventType
from streaming.validation import EventSequenceValidator, EventValidationError


# ============================================================================
# Contract Compliance Tests
# ============================================================================


class TestStreamingContractEventOrder:
    """Tests for streaming event order contract compliance."""

    def test_minimal_valid_sequence(self):
        """Test minimal valid sequence: start -> done."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-1", "llama"))
        validator.add_event(StreamEvent.done("req-1", {"total_tokens": 0}, 50.0))

        assert validator.validate_sequence() is True

    def test_typical_rag_sequence(self):
        """Test typical RAG sequence: start -> deltas -> citations -> done."""
        validator = EventSequenceValidator()

        # Start
        validator.add_event(StreamEvent.start("req-1", "llama", session_id="sess-1"))

        # Stream tokens
        tokens = ["The ", "answer ", "is ", "42."]
        for token in tokens:
            validator.add_event(StreamEvent.delta("req-1", token))

        # Citations
        sources = [
            {"title": "Hitchhiker's Guide", "uri": "h2g2.txt", "chunk_id": "c1"}
        ]
        validator.add_event(StreamEvent.citations("req-1", sources))

        # Done
        usage = {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24}
        validator.add_event(StreamEvent.done("req-1", usage, 150.0))

        assert validator.validate_sequence() is True
        assert validator.delta_count == 4
        assert validator.has_citations is True

    def test_direct_llm_sequence_no_citations(self):
        """Test direct LLM sequence without citations: start -> deltas -> done."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-1", "gpt-4"))

        for token in ["Hello", " ", "world", "!"]:
            validator.add_event(StreamEvent.delta("req-1", token))

        validator.add_event(StreamEvent.done("req-1", {"total_tokens": 10}, 100.0))

        assert validator.validate_sequence() is True
        assert validator.has_citations is False

    def test_error_interrupts_sequence(self):
        """Test that error can interrupt sequence at any point."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-1", "llama"))
        validator.add_event(StreamEvent.delta("req-1", "Starting"))
        validator.add_event(
            StreamEvent.error("req-1", "Model timeout", "TIMEOUT", recoverable=True)
        )

        assert validator.validate_sequence() is True
        assert validator.has_error is True
        assert validator.has_done is False


class TestStreamingContractEventStructure:
    """Tests for streaming event structure contract compliance."""

    def test_start_event_required_fields(self):
        """Test start event has required fields: request_id, model."""
        event = StreamEvent.start("req-123", "llama")
        sse = event.to_sse()

        # Parse SSE data
        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "request_id" in data
        assert "model" in data
        assert data["request_id"] == "req-123"
        assert data["model"] == "llama"

    def test_delta_event_required_fields(self):
        """Test delta event has required field: token."""
        event = StreamEvent.delta("req-123", "Hello")
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "token" in data
        assert data["token"] == "Hello"

    def test_citations_event_required_fields(self):
        """Test citations event has required field: sources."""
        sources = [{"title": "Doc", "uri": "doc.md", "chunk_id": "c1"}]
        event = StreamEvent.citations("req-123", sources)
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "sources" in data
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) == 1

    def test_done_event_required_fields(self):
        """Test done event has required fields: usage, latency_ms."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        event = StreamEvent.done("req-123", usage, 150.5)
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "usage" in data
        assert "latency_ms" in data
        assert isinstance(data["usage"], dict)
        assert data["latency_ms"] == 150.5

    def test_error_event_required_fields(self):
        """Test error event has required fields: error, code, recoverable."""
        event = StreamEvent.error("req-123", "Connection failed", "CONN_ERR", True)
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "error" in data
        assert "code" in data
        assert "recoverable" in data
        assert data["error"] == "Connection failed"
        assert data["code"] == "CONN_ERR"
        assert data["recoverable"] is True


class TestStreamingContractSSEFormat:
    """Tests for SSE wire format compliance."""

    def test_sse_event_format(self):
        """Test SSE format: event: type\\ndata: json\\n\\n."""
        event = StreamEvent.start("req-123", "llama")
        sse = event.to_sse()

        # Must start with "event: <type>\n"
        assert sse.startswith("event: start\n")

        # Must have "data: " line
        assert "\ndata: " in sse

        # Must end with double newline
        assert sse.endswith("\n\n")

    def test_sse_data_is_valid_json(self):
        """Test that SSE data payload is valid JSON."""
        events = [
            StreamEvent.start("req-1", "llama"),
            StreamEvent.delta("req-1", "token"),
            StreamEvent.citations("req-1", []),
            StreamEvent.done("req-1", {}, 100.0),
            StreamEvent.error("req-1", "err", "ERR"),
        ]

        for event in events:
            sse = event.to_sse()
            lines = sse.strip().split("\n")
            data_line = next(l for l in lines if l.startswith("data: "))

            # Should not raise
            parsed = json.loads(data_line[6:])
            assert isinstance(parsed, dict)

    def test_sse_handles_special_characters(self):
        """Test SSE properly escapes special characters in JSON."""
        event = StreamEvent.delta("req-123", 'Line1\nLine2\t"quoted"\\slash')
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert data["token"] == 'Line1\nLine2\t"quoted"\\slash'

    def test_sse_includes_timestamp(self):
        """Test that SSE data includes timestamp."""
        event = StreamEvent.start("req-123", "llama")
        sse = event.to_sse()

        lines = sse.strip().split("\n")
        data_line = next(l for l in lines if l.startswith("data: "))
        data = json.loads(data_line[6:])

        assert "timestamp" in data
        assert isinstance(data["timestamp"], (int, float))


# ============================================================================
# TTFT Contract Tests
# ============================================================================


class TestTTFTContractCompliance:
    """Tests for TTFT (Time to First Token) contract compliance."""

    def test_ttft_target_defined(self):
        """Test that TTFT target is <500ms as per contract."""
        assert TTFTTracker.TTFT_TARGET_MS == 500.0

    def test_ttft_tracking_accuracy(self):
        """Test TTFT tracking measures correctly."""
        tracker = TTFTTracker("req-ttft-1")

        tracker.start()
        time.sleep(0.1)  # 100ms delay
        tracker.record_first_token()

        # Should be around 100ms (with tolerance for timing)
        assert tracker.ttft_ms is not None
        assert 80 <= tracker.ttft_ms <= 200

    def test_ttft_meets_target_evaluation(self):
        """Test meets_target property evaluates correctly."""
        # Fast TTFT (should meet target)
        fast_tracker = TTFTTracker("req-fast")
        fast_tracker.start()
        fast_tracker.record_first_token()  # Immediate
        assert fast_tracker.meets_target is True

        # The target is 500ms - hard to test "slow" in unit tests

    def test_ttft_recorder_integration(self):
        """Test TTFT recording through StreamMetricsRecorder."""
        recorder = StreamMetricsRecorder("req-recorder")

        recorder.stream_started()
        time.sleep(0.05)
        recorder.token_received()

        assert recorder.ttft_ms is not None
        assert recorder.ttft_ms >= 50


# ============================================================================
# End-to-End Stream Validation Tests
# ============================================================================


class TestEndToEndStreamValidation:
    """End-to-end tests validating complete streaming scenarios."""

    @pytest.mark.asyncio
    async def test_validated_stream_generation(self):
        """Test generating and validating a complete stream."""
        validator = EventSequenceValidator()
        recorder = StreamMetricsRecorder("req-e2e-1")

        # Simulate stream generation
        events = []

        # Start
        start_event = StreamEvent.start("req-e2e-1", "llama", "sess-1")
        validator.add_event(start_event)
        events.append(start_event)
        recorder.stream_started()

        # Deltas
        tokens = ["The ", "quick ", "brown ", "fox."]
        for token in tokens:
            delta_event = StreamEvent.delta("req-e2e-1", token)
            validator.add_event(delta_event)
            events.append(delta_event)
            recorder.token_received()

        # Citations
        citations_event = StreamEvent.citations(
            "req-e2e-1",
            [{"title": "Animals", "uri": "animals.md", "chunk_id": "c1"}],
        )
        validator.add_event(citations_event)
        events.append(citations_event)

        # Done
        done_event = StreamEvent.done(
            "req-e2e-1",
            {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            150.0,
        )
        validator.add_event(done_event)
        events.append(done_event)
        recorder.stream_completed(success=True)

        # Validate
        assert validator.validate_sequence() is True
        assert len(events) == 7  # start + 4 deltas + citations + done
        assert recorder.token_count == 4
        assert recorder.is_completed is True

    @pytest.mark.asyncio
    async def test_validated_error_stream(self):
        """Test validating a stream that ends with error."""
        validator = EventSequenceValidator()
        recorder = StreamMetricsRecorder("req-err-1")

        # Start
        validator.add_event(StreamEvent.start("req-err-1", "llama"))
        recorder.stream_started()

        # Some deltas before error
        validator.add_event(StreamEvent.delta("req-err-1", "Starting"))
        recorder.token_received()

        # Error
        validator.add_event(
            StreamEvent.error(
                "req-err-1",
                "Model overloaded",
                "MODEL_OVERLOAD",
                recoverable=True,
            )
        )
        recorder.stream_completed(success=False)

        assert validator.validate_sequence() is True
        assert validator.has_error is True
        assert recorder.token_count == 1

    def test_invalid_sequence_detection(self):
        """Test that invalid sequences are detected."""
        # Missing start
        v1 = EventSequenceValidator()
        with pytest.raises(EventValidationError):
            v1.add_event(StreamEvent.delta("req-1", "token"))

        # Delta after citations
        v2 = EventSequenceValidator()
        v2.add_event(StreamEvent.start("req-1", "llama"))
        v2.add_event(StreamEvent.citations("req-1", []))
        with pytest.raises(EventValidationError):
            v2.add_event(StreamEvent.delta("req-1", "late delta"))

        # Event after done
        v3 = EventSequenceValidator()
        v3.add_event(StreamEvent.start("req-1", "llama"))
        v3.add_event(StreamEvent.done("req-1", {}, 100.0))
        with pytest.raises(EventValidationError):
            v3.add_event(StreamEvent.delta("req-1", "after done"))


# ============================================================================
# Stream Manager Contract Tests
# ============================================================================


class TestStreamManagerContractCompliance:
    """Tests for StreamManager contract compliance."""

    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway that yields tokens."""
        gateway = AsyncMock()

        async def mock_stream(*args, **kwargs):
            for token in ["Hello", " ", "World", "!"]:
                yield token

        gateway.chat_completion_stream = mock_stream
        return gateway

    @pytest.mark.asyncio
    async def test_stream_manager_event_order(self, mock_gateway):
        """Test StreamManager produces events in correct order."""
        manager = StreamManager(gateway=mock_gateway)
        validator = EventSequenceValidator()

        events = []
        async for event in manager.stream_response(
            request_id="req-sm-1",
            model="llama",
            messages=[{"role": "user", "content": "Hello"}],
        ):
            validator.add_event(event)
            events.append(event)

        # Validate sequence
        assert validator.validate_sequence() is True

        # Check event types
        assert events[0].event == StreamEventType.START
        assert all(e.event == StreamEventType.DELTA for e in events[1:-1])
        assert events[-1].event == StreamEventType.DONE

    @pytest.mark.asyncio
    async def test_stream_manager_with_documents(self, mock_gateway):
        """Test StreamManager includes citations when documents provided."""
        manager = StreamManager(gateway=mock_gateway)
        validator = EventSequenceValidator()

        documents = [{"title": "Doc", "uri": "doc.md", "chunk_id": "c1"}]

        events = []
        async for event in manager.stream_response(
            request_id="req-sm-2",
            model="llama",
            messages=[{"role": "user", "content": "Hello"}],
            documents=documents,
        ):
            validator.add_event(event)
            events.append(event)

        assert validator.validate_sequence() is True
        assert validator.has_citations is True

    @pytest.mark.asyncio
    async def test_stream_manager_error_handling(self):
        """Test StreamManager handles errors correctly."""
        gateway = AsyncMock()

        async def error_stream(*args, **kwargs):
            yield "Start"
            raise Exception("Connection lost")

        gateway.chat_completion_stream = error_stream

        manager = StreamManager(gateway=gateway)
        validator = EventSequenceValidator()

        async for event in manager.stream_response(
            request_id="req-sm-err",
            model="llama",
            messages=[{"role": "user", "content": "Hello"}],
        ):
            validator.add_event(event)

        assert validator.validate_sequence() is True
        assert validator.has_error is True


# ============================================================================
# Contract Specification Tests
# ============================================================================


class TestContractSpecification:
    """Tests verifying contract specification requirements."""

    def test_event_types_match_specification(self):
        """Test that event types match contract specification."""
        expected_types = {"start", "delta", "citations", "done", "error"}
        actual_types = {e.value for e in StreamEventType}
        assert actual_types == expected_types

    def test_start_event_specification(self):
        """Test start event matches: {"request_id": "...", "model": "..."}."""
        event = StreamEvent.start("test-req", "test-model", "test-session")

        assert "request_id" in event.data
        assert "model" in event.data
        # session_id is optional per spec

    def test_delta_event_specification(self):
        """Test delta event matches: {"token": "..."}."""
        event = StreamEvent.delta("test-req", "test-token")

        assert "token" in event.data
        assert event.data["token"] == "test-token"

    def test_citations_event_specification(self):
        """Test citations event matches: {"sources": [...]}."""
        sources = [{"id": "1"}, {"id": "2"}]
        event = StreamEvent.citations("test-req", sources)

        assert "sources" in event.data
        assert isinstance(event.data["sources"], list)

    def test_done_event_specification(self):
        """Test done event matches: {"usage": {...}, "latency_ms": N}."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        event = StreamEvent.done("test-req", usage, 100.5)

        assert "usage" in event.data
        assert "latency_ms" in event.data
        assert isinstance(event.data["usage"], dict)
        assert isinstance(event.data["latency_ms"], (int, float))

    def test_error_event_specification(self):
        """Test error event matches: {"error": "message", "code": "CODE", "recoverable": bool}."""
        event = StreamEvent.error("test-req", "Error message", "ERROR_CODE", True)

        assert "error" in event.data
        assert "code" in event.data
        assert "recoverable" in event.data
        assert isinstance(event.data["error"], str)
        assert isinstance(event.data["code"], str)
        assert isinstance(event.data["recoverable"], bool)

    def test_ttft_target_specification(self):
        """Test TTFT target is <500ms as per specification."""
        # The contract specifies TTFT target: <500ms
        assert TTFTTracker.TTFT_TARGET_MS == 500.0

        # Test that meets_target uses this threshold
        tracker = TTFTTracker("test")
        tracker._start_time = 0
        tracker._first_token_time = 0.499  # 499ms - should meet target
        assert tracker.meets_target is True

        tracker._first_token_time = 0.501  # 501ms - should not meet target
        assert tracker.meets_target is False
