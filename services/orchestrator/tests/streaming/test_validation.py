"""Tests for streaming event validation.

This module tests the EventSequenceValidator and individual event validation
functions to ensure SSE events conform to the streaming contract.
"""

import pytest
from streaming.models import StreamEvent, StreamEventType
from streaming.validation import (
    EventSequenceValidator,
    EventValidationError,
    validate_citations_event,
    validate_delta_event,
    validate_done_event,
    validate_error_event,
    validate_start_event,
)

# ============================================================================
# EventValidationError Tests
# ============================================================================


class TestEventValidationError:
    """Tests for EventValidationError exception."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = EventValidationError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.event is None
        assert error.expected is None
        assert error.actual is None

    def test_error_with_event(self):
        """Test error with associated event."""
        event = StreamEvent.delta("req-123", "token")
        error = EventValidationError("Invalid event", event=event)
        assert error.event == event
        assert error.event.request_id == "req-123"

    def test_error_with_expected_actual(self):
        """Test error with expected/actual values."""
        error = EventValidationError(
            "Sequence error",
            expected="start event",
            actual="delta event",
        )
        assert error.expected == "start event"
        assert error.actual == "delta event"

    def test_error_is_exception(self):
        """Test that EventValidationError is a proper exception."""
        with pytest.raises(EventValidationError) as exc_info:
            raise EventValidationError("Test error")
        assert "Test error" in str(exc_info.value)


# ============================================================================
# Individual Event Validation Tests
# ============================================================================


class TestValidateStartEvent:
    """Tests for validate_start_event function."""

    def test_valid_start_event(self):
        """Test validation of a valid start event."""
        event = StreamEvent.start("req-123", "llama")
        assert validate_start_event(event) is True

    def test_valid_start_event_with_session(self):
        """Test validation of start event with session_id."""
        event = StreamEvent.start("req-123", "llama", session_id="sess-456")
        assert validate_start_event(event) is True

    def test_invalid_missing_request_id(self):
        """Test validation fails when request_id is missing."""
        event = StreamEvent(
            event=StreamEventType.START,
            data={"model": "llama"},
            request_id="req-123",
        )
        assert validate_start_event(event) is False

    def test_invalid_missing_model(self):
        """Test validation fails when model is missing."""
        event = StreamEvent(
            event=StreamEventType.START,
            data={"request_id": "req-123"},
            request_id="req-123",
        )
        assert validate_start_event(event) is False

    def test_invalid_empty_request_id(self):
        """Test validation fails when request_id is empty."""
        event = StreamEvent(
            event=StreamEventType.START,
            data={"request_id": "", "model": "llama"},
            request_id="req-123",
        )
        assert validate_start_event(event) is False

    def test_invalid_empty_model(self):
        """Test validation fails when model is empty."""
        event = StreamEvent(
            event=StreamEventType.START,
            data={"request_id": "req-123", "model": ""},
            request_id="req-123",
        )
        assert validate_start_event(event) is False

    def test_wrong_event_type(self):
        """Test validation fails for wrong event type."""
        event = StreamEvent.delta("req-123", "token")
        assert validate_start_event(event) is False


class TestValidateDeltaEvent:
    """Tests for validate_delta_event function."""

    def test_valid_delta_event(self):
        """Test validation of a valid delta event."""
        event = StreamEvent.delta("req-123", "Hello")
        assert validate_delta_event(event) is True

    def test_valid_delta_event_empty_token(self):
        """Test validation accepts empty token."""
        event = StreamEvent.delta("req-123", "")
        assert validate_delta_event(event) is True

    def test_valid_delta_event_whitespace(self):
        """Test validation accepts whitespace token."""
        event = StreamEvent.delta("req-123", " \n\t")
        assert validate_delta_event(event) is True

    def test_invalid_missing_token(self):
        """Test validation fails when token is missing."""
        event = StreamEvent(
            event=StreamEventType.DELTA,
            data={},
            request_id="req-123",
        )
        assert validate_delta_event(event) is False

    def test_wrong_event_type(self):
        """Test validation fails for wrong event type."""
        event = StreamEvent.start("req-123", "llama")
        assert validate_delta_event(event) is False


class TestValidateCitationsEvent:
    """Tests for validate_citations_event function."""

    def test_valid_citations_event(self):
        """Test validation of a valid citations event."""
        sources = [{"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"}]
        event = StreamEvent.citations("req-123", sources)
        assert validate_citations_event(event) is True

    def test_valid_citations_event_empty_sources(self):
        """Test validation accepts empty sources list."""
        event = StreamEvent.citations("req-123", [])
        assert validate_citations_event(event) is True

    def test_valid_citations_event_multiple_sources(self):
        """Test validation with multiple sources."""
        sources = [
            {"title": "Doc 1", "uri": "doc1.md", "chunk_id": "c1"},
            {"title": "Doc 2", "uri": "doc2.md", "chunk_id": "c2"},
        ]
        event = StreamEvent.citations("req-123", sources)
        assert validate_citations_event(event) is True

    def test_invalid_missing_sources(self):
        """Test validation fails when sources is missing."""
        event = StreamEvent(
            event=StreamEventType.CITATIONS,
            data={},
            request_id="req-123",
        )
        assert validate_citations_event(event) is False

    def test_invalid_sources_not_list(self):
        """Test validation fails when sources is not a list."""
        event = StreamEvent(
            event=StreamEventType.CITATIONS,
            data={"sources": "not a list"},
            request_id="req-123",
        )
        assert validate_citations_event(event) is False

    def test_wrong_event_type(self):
        """Test validation fails for wrong event type."""
        event = StreamEvent.delta("req-123", "token")
        assert validate_citations_event(event) is False


class TestValidateDoneEvent:
    """Tests for validate_done_event function."""

    def test_valid_done_event(self):
        """Test validation of a valid done event."""
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        event = StreamEvent.done("req-123", usage, 150.5)
        assert validate_done_event(event) is True

    def test_valid_done_event_zero_latency(self):
        """Test validation accepts zero latency."""
        usage = {"total_tokens": 0}
        event = StreamEvent.done("req-123", usage, 0.0)
        assert validate_done_event(event) is True

    def test_invalid_missing_usage(self):
        """Test validation fails when usage is missing."""
        event = StreamEvent(
            event=StreamEventType.DONE,
            data={"latency_ms": 150.5, "request_id": "req-123"},
            request_id="req-123",
        )
        assert validate_done_event(event) is False

    def test_invalid_missing_latency(self):
        """Test validation fails when latency_ms is missing."""
        event = StreamEvent(
            event=StreamEventType.DONE,
            data={"usage": {}, "request_id": "req-123"},
            request_id="req-123",
        )
        assert validate_done_event(event) is False

    def test_invalid_usage_not_dict(self):
        """Test validation fails when usage is not a dict."""
        event = StreamEvent(
            event=StreamEventType.DONE,
            data={"usage": "not a dict", "latency_ms": 100, "request_id": "req-123"},
            request_id="req-123",
        )
        assert validate_done_event(event) is False

    def test_wrong_event_type(self):
        """Test validation fails for wrong event type."""
        event = StreamEvent.start("req-123", "llama")
        assert validate_done_event(event) is False


class TestValidateErrorEvent:
    """Tests for validate_error_event function."""

    def test_valid_error_event(self):
        """Test validation of a valid error event."""
        event = StreamEvent.error("req-123", "Connection failed", "CONNECTION_ERROR")
        assert validate_error_event(event) is True

    def test_valid_error_event_recoverable(self):
        """Test validation with recoverable flag."""
        event = StreamEvent.error(
            "req-123",
            "Rate limited",
            "RATE_LIMIT",
            recoverable=True,
        )
        assert validate_error_event(event) is True

    def test_invalid_missing_error(self):
        """Test validation fails when error message is missing."""
        event = StreamEvent(
            event=StreamEventType.ERROR,
            data={"code": "ERROR_CODE", "recoverable": False},
            request_id="req-123",
        )
        assert validate_error_event(event) is False

    def test_invalid_missing_code(self):
        """Test validation fails when code is missing."""
        event = StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": "An error occurred", "recoverable": False},
            request_id="req-123",
        )
        assert validate_error_event(event) is False

    def test_invalid_error_not_string(self):
        """Test validation fails when error is not a string."""
        event = StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": 123, "code": "ERROR", "recoverable": False},
            request_id="req-123",
        )
        assert validate_error_event(event) is False

    def test_invalid_code_not_string(self):
        """Test validation fails when code is not a string."""
        event = StreamEvent(
            event=StreamEventType.ERROR,
            data={"error": "Error", "code": 123, "recoverable": False},
            request_id="req-123",
        )
        assert validate_error_event(event) is False

    def test_wrong_event_type(self):
        """Test validation fails for wrong event type."""
        event = StreamEvent.delta("req-123", "token")
        assert validate_error_event(event) is False


# ============================================================================
# EventSequenceValidator Tests
# ============================================================================


class TestEventSequenceValidatorInit:
    """Tests for EventSequenceValidator initialization."""

    def test_initial_state(self):
        """Test validator starts with empty state."""
        validator = EventSequenceValidator()
        assert len(validator.events) == 0
        assert validator.has_start is False
        assert validator.has_done is False
        assert validator.has_error is False
        assert validator.has_citations is False
        assert validator.is_complete is False
        assert validator.delta_count == 0


class TestEventSequenceValidatorAddEvent:
    """Tests for EventSequenceValidator.add_event method."""

    def test_add_start_event(self):
        """Test adding a start event."""
        validator = EventSequenceValidator()
        event = StreamEvent.start("req-123", "llama")
        validator.add_event(event)

        assert validator.has_start is True
        assert len(validator.events) == 1

    def test_add_delta_after_start(self):
        """Test adding delta events after start."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "Hello"))
        validator.add_event(StreamEvent.delta("req-123", " world"))

        assert validator.delta_count == 2

    def test_add_citations_after_deltas(self):
        """Test adding citations event after deltas."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "Hello"))
        validator.add_event(StreamEvent.citations("req-123", []))

        assert validator.has_citations is True

    def test_add_done_event(self):
        """Test adding done event completes sequence."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        assert validator.has_done is True
        assert validator.is_complete is True

    def test_add_error_event(self):
        """Test adding error event completes sequence."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.error("req-123", "Error", "ERROR"))

        assert validator.has_error is True
        assert validator.is_complete is True

    def test_error_can_occur_any_time(self):
        """Test error event can occur at any point in sequence."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "token"))
        validator.add_event(StreamEvent.error("req-123", "Error", "ERROR"))

        assert validator.is_complete is True
        assert validator.delta_count == 1


class TestEventSequenceValidatorErrors:
    """Tests for EventSequenceValidator error cases."""

    def test_delta_before_start(self):
        """Test error when delta comes before start."""
        validator = EventSequenceValidator()
        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.delta("req-123", "token"))

        assert "before START" in str(exc_info.value)

    def test_done_before_start(self):
        """Test error when done comes before start."""
        validator = EventSequenceValidator()
        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        assert "before START" in str(exc_info.value)

    def test_duplicate_start(self):
        """Test error on duplicate start event."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.start("req-123", "llama"))

        assert "Duplicate START" in str(exc_info.value)

    def test_start_not_first(self):
        """Test error when start is not the first event."""
        # This case is actually prevented by other validations,
        # but we can test the message by using internal state manipulation
        validator = EventSequenceValidator()
        # Add an error event first (which doesn't require start)
        validator.add_event(StreamEvent.error("req-123", "Error", "ERROR"))

        # Now adding start should fail because sequence is complete
        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.start("req-123", "llama"))

        assert "complete" in str(exc_info.value).lower()

    def test_delta_after_citations(self):
        """Test error when delta comes after citations."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "token"))
        validator.add_event(StreamEvent.citations("req-123", []))

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.delta("req-123", "more"))

        assert "after CITATIONS" in str(exc_info.value)

    def test_duplicate_citations(self):
        """Test error on duplicate citations event."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.citations("req-123", []))

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.citations("req-123", []))

        assert "Duplicate CITATIONS" in str(exc_info.value)

    def test_event_after_done(self):
        """Test error when adding event after done."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.delta("req-123", "token"))

        assert "complete" in str(exc_info.value).lower()

    def test_event_after_error(self):
        """Test error when adding event after error."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.error("req-123", "Error", "ERROR"))

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(StreamEvent.delta("req-123", "token"))

        assert "complete" in str(exc_info.value).lower()

    def test_invalid_start_event_structure(self):
        """Test error when start event has invalid structure."""
        validator = EventSequenceValidator()
        invalid_start = StreamEvent(
            event=StreamEventType.START,
            data={},  # Missing required fields
            request_id="req-123",
        )

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(invalid_start)

        assert "request_id" in str(exc_info.value) or "model" in str(exc_info.value)

    def test_invalid_done_event_structure(self):
        """Test error when done event has invalid structure."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))

        invalid_done = StreamEvent(
            event=StreamEventType.DONE,
            data={"request_id": "req-123"},  # Missing usage and latency_ms
            request_id="req-123",
        )

        with pytest.raises(EventValidationError) as exc_info:
            validator.add_event(invalid_done)

        assert "usage" in str(exc_info.value) or "latency" in str(exc_info.value)


class TestEventSequenceValidatorValidateSequence:
    """Tests for EventSequenceValidator.validate_sequence method."""

    def test_valid_minimal_sequence(self):
        """Test validation of minimal valid sequence (start + done)."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        assert validator.validate_sequence() is True

    def test_valid_full_sequence(self):
        """Test validation of full sequence with all event types."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "Hello "))
        validator.add_event(StreamEvent.delta("req-123", "world!"))
        validator.add_event(StreamEvent.citations("req-123", [{"title": "Doc"}]))
        validator.add_event(StreamEvent.done("req-123", {"total_tokens": 10}, 150.0))

        assert validator.validate_sequence() is True

    def test_valid_sequence_with_error(self):
        """Test validation of sequence ending with error."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "Hello"))
        validator.add_event(StreamEvent.error("req-123", "Timeout", "TIMEOUT"))

        assert validator.validate_sequence() is True

    def test_invalid_empty_sequence(self):
        """Test validation fails for empty sequence."""
        validator = EventSequenceValidator()

        with pytest.raises(EventValidationError) as exc_info:
            validator.validate_sequence()

        assert "Empty sequence" in str(exc_info.value)

    def test_invalid_incomplete_sequence(self):
        """Test validation fails for incomplete sequence."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "Hello"))

        with pytest.raises(EventValidationError) as exc_info:
            validator.validate_sequence()

        assert "incomplete" in str(exc_info.value).lower()


class TestEventSequenceValidatorReset:
    """Tests for EventSequenceValidator.reset method."""

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "token"))
        validator.add_event(StreamEvent.citations("req-123", []))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        validator.reset()

        assert len(validator.events) == 0
        assert validator.has_start is False
        assert validator.has_done is False
        assert validator.has_error is False
        assert validator.has_citations is False
        assert validator.is_complete is False
        assert validator.delta_count == 0

    def test_reset_allows_reuse(self):
        """Test that reset allows validator reuse."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        validator.reset()

        # Should be able to start fresh
        validator.add_event(StreamEvent.start("req-456", "gpt"))
        validator.add_event(StreamEvent.done("req-456", {}, 200.0))

        assert validator.validate_sequence() is True
        assert len(validator.events) == 2


class TestEventSequenceValidatorProperties:
    """Tests for EventSequenceValidator property methods."""

    def test_events_property_returns_copy(self):
        """Test that events property returns a copy."""
        validator = EventSequenceValidator()
        event = StreamEvent.start("req-123", "llama")
        validator.add_event(event)

        events = validator.events
        events.clear()

        # Original should not be affected
        assert len(validator.events) == 1

    def test_delta_count_accurate(self):
        """Test that delta_count accurately counts delta events."""
        validator = EventSequenceValidator()
        validator.add_event(StreamEvent.start("req-123", "llama"))
        validator.add_event(StreamEvent.delta("req-123", "a"))
        validator.add_event(StreamEvent.delta("req-123", "b"))
        validator.add_event(StreamEvent.delta("req-123", "c"))
        validator.add_event(StreamEvent.done("req-123", {}, 100.0))

        assert validator.delta_count == 3


# ============================================================================
# Integration Tests
# ============================================================================


class TestEventSequenceValidatorIntegration:
    """Integration tests for realistic streaming scenarios."""

    def test_typical_rag_response(self):
        """Test validation of typical RAG response sequence."""
        validator = EventSequenceValidator()

        # Start stream
        validator.add_event(StreamEvent.start("req-rag-1", "llama", "sess-1"))

        # Stream tokens
        for token in ["Python ", "is ", "a ", "programming ", "language."]:
            validator.add_event(StreamEvent.delta("req-rag-1", token))

        # Add citations
        sources = [
            {"title": "Python Docs", "uri": "python.org", "chunk_id": "c1"},
            {"title": "Wikipedia", "uri": "wiki.org", "chunk_id": "c2"},
        ]
        validator.add_event(StreamEvent.citations("req-rag-1", sources))

        # Complete with usage stats
        usage = {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}
        validator.add_event(StreamEvent.done("req-rag-1", usage, 250.5))

        assert validator.validate_sequence() is True
        assert validator.delta_count == 5
        assert validator.has_citations is True

    def test_direct_llm_response_no_citations(self):
        """Test validation of direct LLM response without RAG."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-direct-1", "gpt-4"))

        for token in ["Hello, ", "how ", "can ", "I ", "help?"]:
            validator.add_event(StreamEvent.delta("req-direct-1", token))

        # No citations for direct response
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        validator.add_event(StreamEvent.done("req-direct-1", usage, 100.0))

        assert validator.validate_sequence() is True
        assert validator.has_citations is False

    def test_error_during_generation(self):
        """Test validation when error occurs during generation."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-err-1", "llama"))
        validator.add_event(StreamEvent.delta("req-err-1", "Starting "))
        validator.add_event(StreamEvent.delta("req-err-1", "to generate..."))

        # Error occurs
        validator.add_event(
            StreamEvent.error(
                "req-err-1",
                "Model timeout exceeded",
                "MODEL_TIMEOUT",
                recoverable=True,
            ),
        )

        assert validator.validate_sequence() is True
        assert validator.has_error is True
        assert validator.has_done is False

    def test_immediate_error(self):
        """Test validation when error occurs immediately after start."""
        validator = EventSequenceValidator()

        validator.add_event(StreamEvent.start("req-imm-err", "llama"))
        validator.add_event(
            StreamEvent.error(
                "req-imm-err",
                "Rate limit exceeded",
                "RATE_LIMIT_ERROR",
                recoverable=True,
            ),
        )

        assert validator.validate_sequence() is True
        assert validator.delta_count == 0
