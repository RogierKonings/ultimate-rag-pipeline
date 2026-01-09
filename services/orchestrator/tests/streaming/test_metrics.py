"""Tests for streaming metrics and TTFT tracking.

This module tests the TTFTTracker, StreamMetricsRecorder, and Prometheus
metrics for monitoring streaming performance.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from streaming.metrics import (
    StreamMetricsRecorder,
    TTFTTracker,
    record_stream_error,
    record_stream_success,
    stream_completions,
    stream_duration_histogram,
    ttft_histogram,
)


# ============================================================================
# TTFTTracker Tests
# ============================================================================


class TestTTFTTrackerInit:
    """Tests for TTFTTracker initialization."""

    def test_initial_state(self):
        """Test tracker initializes with correct state."""
        tracker = TTFTTracker("req-123")

        assert tracker.request_id == "req-123"
        assert tracker.ttft_ms is None
        assert tracker.ttft_seconds is None
        assert tracker.is_started is False
        assert tracker.has_first_token is False
        assert tracker.meets_target is None

    def test_request_id_property(self):
        """Test request_id property returns correct value."""
        tracker = TTFTTracker("custom-request-id")
        assert tracker.request_id == "custom-request-id"


class TestTTFTTrackerStart:
    """Tests for TTFTTracker.start method."""

    def test_start_marks_started(self):
        """Test that start() marks the tracker as started."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        assert tracker.is_started is True

    def test_start_does_not_set_first_token(self):
        """Test that start() doesn't set first token time."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        assert tracker.has_first_token is False
        assert tracker.ttft_ms is None

    def test_multiple_starts_updates_time(self):
        """Test that multiple starts update the start time."""
        tracker = TTFTTracker("req-123")
        tracker.start()
        first_start = tracker._start_time

        time.sleep(0.01)
        tracker.start()

        assert tracker._start_time > first_start


class TestTTFTTrackerRecordFirstToken:
    """Tests for TTFTTracker.record_first_token method."""

    def test_record_first_token(self):
        """Test recording first token calculates TTFT."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        # Simulate some delay
        time.sleep(0.05)
        tracker.record_first_token()

        assert tracker.has_first_token is True
        assert tracker.ttft_ms is not None
        assert tracker.ttft_ms >= 50  # At least 50ms

    def test_record_first_token_only_once(self):
        """Test that first token is only recorded once."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        time.sleep(0.01)
        tracker.record_first_token()
        first_ttft = tracker.ttft_ms

        time.sleep(0.05)
        tracker.record_first_token()  # Should be ignored

        assert tracker.ttft_ms == first_ttft

    def test_record_first_token_without_start(self):
        """Test recording first token without start gives None TTFT."""
        tracker = TTFTTracker("req-123")
        tracker.record_first_token()

        assert tracker.has_first_token is True
        assert tracker.ttft_ms is None  # No start time

    @patch.object(ttft_histogram, "observe")
    def test_record_first_token_observes_histogram(self, mock_observe):
        """Test that recording first token observes Prometheus histogram."""
        tracker = TTFTTracker("req-123")
        tracker.start()
        tracker.record_first_token()

        mock_observe.assert_called_once()
        # The value should be a float representing seconds
        call_args = mock_observe.call_args[0][0]
        assert isinstance(call_args, float)
        assert call_args >= 0

    @patch.object(ttft_histogram, "observe")
    def test_histogram_observed_only_once(self, mock_observe):
        """Test that histogram is only observed once per tracker."""
        tracker = TTFTTracker("req-123")
        tracker.start()
        tracker.record_first_token()
        tracker.record_first_token()  # Second call

        # Should only observe once
        assert mock_observe.call_count == 1


class TestTTFTTrackerTTFT:
    """Tests for TTFT calculation and properties."""

    def test_ttft_ms_calculation(self):
        """Test TTFT in milliseconds is calculated correctly."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        # Sleep for approximately 100ms
        time.sleep(0.1)
        tracker.record_first_token()

        # Should be around 100ms (with some tolerance)
        assert tracker.ttft_ms is not None
        assert 80 <= tracker.ttft_ms <= 200  # Allow for timing variations

    def test_ttft_seconds_calculation(self):
        """Test TTFT in seconds is calculated correctly."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        time.sleep(0.1)
        tracker.record_first_token()

        assert tracker.ttft_seconds is not None
        assert 0.08 <= tracker.ttft_seconds <= 0.2


class TestTTFTTrackerMeetsTarget:
    """Tests for TTFTTracker.meets_target property."""

    def test_meets_target_when_fast(self):
        """Test meets_target returns True for fast TTFT."""
        tracker = TTFTTracker("req-123")
        tracker.start()

        # Immediate first token (should be well under 500ms)
        tracker.record_first_token()

        assert tracker.meets_target is True

    def test_meets_target_none_before_measurement(self):
        """Test meets_target returns None before measurement."""
        tracker = TTFTTracker("req-123")
        assert tracker.meets_target is None

        tracker.start()
        assert tracker.meets_target is None

    def test_target_constant(self):
        """Test that TTFT target constant is correct."""
        assert TTFTTracker.TTFT_TARGET_MS == 500.0


class TestTTFTTrackerReset:
    """Tests for TTFTTracker.reset method."""

    def test_reset_clears_all_state(self):
        """Test that reset clears all tracking state."""
        tracker = TTFTTracker("req-123")
        tracker.start()
        tracker.record_first_token()

        tracker.reset()

        assert tracker.is_started is False
        assert tracker.has_first_token is False
        assert tracker.ttft_ms is None

    def test_reset_allows_reuse(self):
        """Test that reset allows tracker to be reused."""
        tracker = TTFTTracker("req-123")
        tracker.start()
        tracker.record_first_token()
        first_ttft = tracker.ttft_ms

        tracker.reset()
        tracker.start()
        time.sleep(0.05)
        tracker.record_first_token()

        # New TTFT should be different (and valid)
        assert tracker.ttft_ms is not None
        assert tracker.ttft_ms != first_ttft


# ============================================================================
# StreamMetricsRecorder Tests
# ============================================================================


class TestStreamMetricsRecorderInit:
    """Tests for StreamMetricsRecorder initialization."""

    def test_initial_state(self):
        """Test recorder initializes with correct state."""
        recorder = StreamMetricsRecorder("req-123")

        assert recorder.request_id == "req-123"
        assert recorder.ttft_ms is None
        assert recorder.token_count == 0
        assert recorder.is_completed is False


class TestStreamMetricsRecorderStreamStarted:
    """Tests for StreamMetricsRecorder.stream_started method."""

    def test_stream_started_initializes_tracking(self):
        """Test that stream_started initializes TTFT tracking."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()

        # TTFT tracker should be started
        assert recorder._ttft_tracker.is_started is True


class TestStreamMetricsRecorderTokenReceived:
    """Tests for StreamMetricsRecorder.token_received method."""

    def test_token_received_increments_count(self):
        """Test that token_received increments token count."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()

        recorder.token_received()
        assert recorder.token_count == 1

        recorder.token_received()
        assert recorder.token_count == 2

    def test_first_token_records_ttft(self):
        """Test that first token_received records TTFT."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()

        time.sleep(0.05)
        recorder.token_received()

        assert recorder.ttft_ms is not None
        assert recorder.ttft_ms >= 50

    def test_subsequent_tokens_dont_update_ttft(self):
        """Test that subsequent tokens don't change TTFT."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()

        recorder.token_received()
        first_ttft = recorder.ttft_ms

        time.sleep(0.05)
        recorder.token_received()

        assert recorder.ttft_ms == first_ttft


class TestStreamMetricsRecorderStreamCompleted:
    """Tests for StreamMetricsRecorder.stream_completed method."""

    @patch.object(stream_completions.labels(status="success"), "inc")
    @patch.object(stream_duration_histogram, "observe")
    def test_stream_completed_success(self, mock_duration, mock_counter):
        """Test stream_completed with success=True."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()
        recorder.token_received()
        recorder.stream_completed(success=True)

        assert recorder.is_completed is True

    @patch.object(stream_completions.labels(status="error"), "inc")
    @patch.object(stream_duration_histogram, "observe")
    def test_stream_completed_error(self, mock_duration, mock_counter):
        """Test stream_completed with success=False."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()
        recorder.stream_completed(success=False)

        assert recorder.is_completed is True

    def test_stream_completed_only_once(self):
        """Test that stream_completed only executes once."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()
        recorder.stream_completed(success=True)

        # Second call should be a no-op
        recorder.stream_completed(success=False)  # Different status

        assert recorder.is_completed is True


class TestStreamMetricsRecorderReset:
    """Tests for StreamMetricsRecorder.reset method."""

    def test_reset_clears_all_state(self):
        """Test that reset clears all recorder state."""
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()
        recorder.token_received()
        recorder.token_received()
        recorder.stream_completed()

        recorder.reset()

        assert recorder.ttft_ms is None
        assert recorder.token_count == 0
        assert recorder.is_completed is False


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for convenience metric recording functions."""

    @patch.object(stream_completions.labels(status="success"), "inc")
    def test_record_stream_success(self, mock_inc):
        """Test record_stream_success increments success counter."""
        record_stream_success()
        mock_inc.assert_called_once()

    @patch.object(stream_completions.labels(status="error"), "inc")
    def test_record_stream_error(self, mock_inc):
        """Test record_stream_error increments error counter."""
        record_stream_error()
        mock_inc.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================


class TestStreamMetricsIntegration:
    """Integration tests for streaming metrics in realistic scenarios."""

    def test_full_streaming_lifecycle(self):
        """Test metrics through a complete streaming lifecycle."""
        recorder = StreamMetricsRecorder("req-lifecycle")

        # Start stream
        recorder.stream_started()

        # Receive tokens
        for i in range(10):
            time.sleep(0.01)  # Simulate token arrival
            recorder.token_received()

        # Complete stream
        recorder.stream_completed(success=True)

        assert recorder.token_count == 10
        assert recorder.ttft_ms is not None
        assert recorder.is_completed is True

    def test_error_after_partial_stream(self):
        """Test metrics when error occurs mid-stream."""
        recorder = StreamMetricsRecorder("req-error")

        recorder.stream_started()

        # Receive some tokens before error
        recorder.token_received()
        recorder.token_received()
        recorder.token_received()

        # Error occurs
        recorder.stream_completed(success=False)

        assert recorder.token_count == 3
        assert recorder.ttft_ms is not None
        assert recorder.is_completed is True

    def test_immediate_error(self):
        """Test metrics when error occurs immediately."""
        recorder = StreamMetricsRecorder("req-imm-error")

        recorder.stream_started()
        recorder.stream_completed(success=False)

        assert recorder.token_count == 0
        assert recorder.ttft_ms is None
        assert recorder.is_completed is True

    def test_ttft_tracker_standalone(self):
        """Test TTFTTracker in standalone usage."""
        tracker = TTFTTracker("req-standalone")

        tracker.start()

        # Simulate waiting for first token
        time.sleep(0.02)
        tracker.record_first_token()

        assert tracker.ttft_ms is not None
        assert tracker.ttft_ms >= 20
        assert tracker.meets_target is True


class TestPrometheusMetricsRegistration:
    """Tests to verify Prometheus metrics are properly defined."""

    def test_ttft_histogram_exists(self):
        """Test that TTFT histogram is properly defined."""
        assert ttft_histogram is not None
        assert ttft_histogram._name == "orchestrator_ttft_seconds"

    def test_stream_completions_counter_exists(self):
        """Test that stream completions counter is properly defined."""
        assert stream_completions is not None
        # Prometheus counters have _total suffix added automatically in some contexts
        assert "orchestrator_stream_completions" in stream_completions._name

    def test_stream_duration_histogram_exists(self):
        """Test that stream duration histogram is properly defined."""
        assert stream_duration_histogram is not None
        assert stream_duration_histogram._name == "orchestrator_stream_duration_seconds"

    def test_ttft_histogram_buckets(self):
        """Test that TTFT histogram has appropriate buckets."""
        # The buckets should be designed around the <500ms target
        # Expected: [0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0]
        expected_buckets = [0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0]
        # Note: prometheus_client adds +Inf bucket
        assert list(ttft_histogram._upper_bounds[:-1]) == expected_buckets

    def test_stream_completions_labels(self):
        """Test that stream completions counter has correct labels."""
        # Should have 'status' label
        assert "status" in stream_completions._labelnames
