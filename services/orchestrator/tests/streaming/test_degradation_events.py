"""Tests for degradation info in streaming events."""

import pytest
from streaming.models import (
    StartEventData,
    DoneEventData,
    StreamEvent,
    StreamEventType,
)


class TestStartEventDataDegradation:
    """Tests for degradation field in StartEventData."""

    def test_start_event_has_degradation_field(self):
        """StartEventData should have optional degradation field."""
        event = StartEventData(
            request_id="test-123",
            model="test-model",
            session_id=None,
            degradation=None,
        )
        assert event.degradation is None

    def test_start_event_with_degradation_info(self):
        """StartEventData should accept degradation info dict."""
        degradation = {
            "level": "degraded",
            "mode": "semantic_only",
            "message": "Keyword search unavailable",
        }
        event = StartEventData(
            request_id="test-123",
            model="test-model",
            session_id=None,
            degradation=degradation,
        )
        assert event.degradation is not None
        assert event.degradation["level"] == "degraded"
        assert event.degradation["mode"] == "semantic_only"
        assert "unavailable" in event.degradation["message"].lower()

    def test_start_event_degradation_in_model_dump(self):
        """Degradation should be included in model_dump output."""
        degradation = {"level": "minimal", "mode": "minimal", "message": "Limited"}
        event = StartEventData(
            request_id="test-123",
            model="test-model",
            degradation=degradation,
        )
        data = event.model_dump()
        assert "degradation" in data
        assert data["degradation"]["level"] == "minimal"


class TestDoneEventDataQuality:
    """Tests for quality fields in DoneEventData."""

    def test_done_event_has_context_quality(self):
        """DoneEventData should have context_quality field."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            context_quality="partial",
        )
        assert event.context_quality == "partial"

    def test_done_event_has_retrieval_mode(self):
        """DoneEventData should have retrieval_mode field."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            retrieval_mode="semantic_only",
        )
        assert event.retrieval_mode == "semantic_only"

    def test_done_event_quality_defaults(self):
        """DoneEventData should have sensible defaults for quality fields."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
        )
        assert event.context_quality == "full"
        assert event.retrieval_mode == "hybrid_full"

    def test_done_event_quality_in_model_dump(self):
        """Quality fields should be included in model_dump output."""
        event = DoneEventData(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            context_quality="minimal",
            retrieval_mode="minimal",
        )
        data = event.model_dump()
        assert data["context_quality"] == "minimal"
        assert data["retrieval_mode"] == "minimal"


class TestStreamEventFactoryMethods:
    """Tests for StreamEvent factory methods with degradation support."""

    def test_stream_event_start_with_degradation(self):
        """StreamEvent.start should accept degradation parameter."""
        degradation = {
            "level": "degraded",
            "mode": "keyword_only",
            "message": "Semantic search unavailable",
        }
        event = StreamEvent.start(
            request_id="test-123",
            model="test-model",
            session_id="session-456",
            degradation=degradation,
        )
        assert event.event == StreamEventType.START
        assert event.data["degradation"]["level"] == "degraded"
        assert event.data["degradation"]["mode"] == "keyword_only"

    def test_stream_event_start_without_degradation(self):
        """StreamEvent.start should work without degradation."""
        event = StreamEvent.start(
            request_id="test-123",
            model="test-model",
        )
        assert event.event == StreamEventType.START
        assert event.data.get("degradation") is None

    def test_stream_event_done_with_quality(self):
        """StreamEvent.done should accept quality parameters."""
        event = StreamEvent.done(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            context_quality="partial",
            retrieval_mode="semantic_only",
        )
        assert event.event == StreamEventType.DONE
        assert event.data["context_quality"] == "partial"
        assert event.data["retrieval_mode"] == "semantic_only"

    def test_stream_event_done_quality_defaults(self):
        """StreamEvent.done should use defaults when quality not specified."""
        event = StreamEvent.done(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
        )
        assert event.data["context_quality"] == "full"
        assert event.data["retrieval_mode"] == "hybrid_full"

    def test_stream_event_to_sse_includes_degradation(self):
        """SSE output should include degradation info when present."""
        degradation = {"level": "minimal", "mode": "minimal", "message": "Limited"}
        event = StreamEvent.start(
            request_id="test-123",
            model="test-model",
            degradation=degradation,
        )
        sse = event.to_sse()
        assert "event: start" in sse
        assert '"level": "minimal"' in sse or '"level":"minimal"' in sse

    def test_stream_event_to_sse_includes_quality(self):
        """SSE output should include quality fields in done event."""
        event = StreamEvent.done(
            request_id="test-123",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            latency_ms=500.0,
            context_quality="partial",
            retrieval_mode="semantic_only",
        )
        sse = event.to_sse()
        assert "event: done" in sse
        assert "partial" in sse
        assert "semantic_only" in sse
