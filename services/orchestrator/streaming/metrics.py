"""Streaming metrics for Time to First Token (TTFT) measurement.

This module provides Prometheus metrics and tracking utilities for measuring
streaming performance, particularly Time to First Token (TTFT) which is a
critical user experience metric.

Contract Requirements:
    - TTFT target: <500ms
    - Track stream completions by status (success/error)
"""

import time

from prometheus_client import Counter, Histogram

# Time to First Token histogram
# Buckets designed around the <500ms target
ttft_histogram = Histogram(
    "orchestrator_ttft_seconds",
    "Time to first token in seconds",
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0],
)

# Stream completion counter
# Tracks total completions by status for monitoring success rate
stream_completions = Counter(
    "orchestrator_stream_completions_total",
    "Total streaming completions",
    ["status"],  # success, error
)

# Additional streaming metrics
stream_tokens_total = Counter(
    "orchestrator_stream_tokens_total",
    "Total tokens streamed",
    ["request_id"],
)

stream_duration_histogram = Histogram(
    "orchestrator_stream_duration_seconds",
    "Total stream duration in seconds",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)


class TTFTTracker:
    """Tracks Time to First Token (TTFT) for streaming requests.

    TTFT is a critical metric for user experience in streaming responses.
    It measures the time from when a request starts being processed until
    the first token is emitted to the client.

    The target TTFT is <500ms as specified in the contract.

    Attributes:
        request_id: Unique identifier for the request being tracked.
        ttft_ms: Time to first token in milliseconds (None until recorded).

    Example:
        ```python
        tracker = TTFTTracker("req-123")
        tracker.start()

        # ... wait for first token ...
        tracker.record_first_token()

        print(f"TTFT: {tracker.ttft_ms}ms")
        # Metrics are automatically recorded to Prometheus
        ```
    """

    # TTFT target in milliseconds
    TTFT_TARGET_MS = 500.0

    def __init__(self, request_id: str) -> None:
        """Initialize the TTFT tracker.

        Args:
            request_id: Unique identifier for the request to track.
        """
        self._request_id = request_id
        self._start_time: float | None = None
        self._first_token_time: float | None = None
        self._recorded = False

    @property
    def request_id(self) -> str:
        """Get the request ID being tracked."""
        return self._request_id

    @property
    def ttft_ms(self) -> float | None:
        """Get TTFT in milliseconds.

        Returns:
            Time to first token in milliseconds, or None if not yet recorded.

        Example:
            ```python
            tracker = TTFTTracker("req-123")
            tracker.start()
            # ... process ...
            tracker.record_first_token()
            print(f"TTFT: {tracker.ttft_ms:.2f}ms")
            ```
        """
        if self._start_time is None or self._first_token_time is None:
            return None
        return (self._first_token_time - self._start_time) * 1000

    @property
    def ttft_seconds(self) -> float | None:
        """Get TTFT in seconds.

        Returns:
            Time to first token in seconds, or None if not yet recorded.
        """
        if self._start_time is None or self._first_token_time is None:
            return None
        return self._first_token_time - self._start_time

    @property
    def is_started(self) -> bool:
        """Check if tracking has started."""
        return self._start_time is not None

    @property
    def has_first_token(self) -> bool:
        """Check if first token has been recorded."""
        return self._first_token_time is not None

    @property
    def meets_target(self) -> bool | None:
        """Check if TTFT meets the <500ms target.

        Returns:
            True if TTFT < 500ms, False if >= 500ms, None if not yet measured.
        """
        ttft = self.ttft_ms
        if ttft is None:
            return None
        return ttft < self.TTFT_TARGET_MS

    def start(self) -> None:
        """Mark stream start.

        Records the start time for TTFT calculation. Should be called
        when the stream processing begins, typically when the start
        event is emitted.

        Example:
            ```python
            tracker = TTFTTracker("req-123")
            tracker.start()
            # Now waiting for first token...
            ```
        """
        self._start_time = time.perf_counter()

    def record_first_token(self) -> None:
        """Record first token arrival.

        Records the time when the first token arrives and observes
        the TTFT metric in Prometheus. This method should only be
        called once per stream - subsequent calls are ignored.

        The metric is automatically recorded to the `orchestrator_ttft_seconds`
        histogram.

        Example:
            ```python
            tracker = TTFTTracker("req-123")
            tracker.start()

            async for token in stream:
                if not tracker.has_first_token:
                    tracker.record_first_token()
                # ... process token ...
            ```
        """
        # Only record once
        if self._first_token_time is not None:
            return

        self._first_token_time = time.perf_counter()

        # Record to Prometheus histogram
        if self._start_time is not None and not self._recorded:
            ttft_seconds = self._first_token_time - self._start_time
            ttft_histogram.observe(ttft_seconds)
            self._recorded = True

    def reset(self) -> None:
        """Reset the tracker for reuse.

        Clears all timing data to allow tracking a new request.

        Example:
            ```python
            tracker = TTFTTracker("req-123")
            # ... use tracker ...
            tracker.reset()
            # Now can be reused for a new request
            ```
        """
        self._start_time = None
        self._first_token_time = None
        self._recorded = False


class StreamMetricsRecorder:
    """Records comprehensive streaming metrics.

    This class provides a higher-level interface for recording all
    streaming-related metrics including TTFT, completion status,
    and total stream duration.

    Example:
        ```python
        recorder = StreamMetricsRecorder("req-123")
        recorder.stream_started()

        async for event in stream:
            if event.type == "delta":
                recorder.token_received()

        recorder.stream_completed(success=True)
        ```
    """

    def __init__(self, request_id: str) -> None:
        """Initialize the metrics recorder.

        Args:
            request_id: Unique identifier for the request.
        """
        self._request_id = request_id
        self._ttft_tracker = TTFTTracker(request_id)
        self._stream_start_time: float | None = None
        self._token_count = 0
        self._completed = False

    @property
    def request_id(self) -> str:
        """Get the request ID."""
        return self._request_id

    @property
    def ttft_ms(self) -> float | None:
        """Get TTFT in milliseconds."""
        return self._ttft_tracker.ttft_ms

    @property
    def token_count(self) -> int:
        """Get the number of tokens received."""
        return self._token_count

    @property
    def is_completed(self) -> bool:
        """Check if the stream has been marked as completed."""
        return self._completed

    def stream_started(self) -> None:
        """Mark that the stream has started.

        Should be called when the start event is emitted.
        """
        self._stream_start_time = time.perf_counter()
        self._ttft_tracker.start()

    def token_received(self) -> None:
        """Record a token being received.

        Should be called for each delta event. The first call
        will automatically record TTFT.
        """
        if not self._ttft_tracker.has_first_token:
            self._ttft_tracker.record_first_token()
        self._token_count += 1

    def stream_completed(self, success: bool = True) -> None:
        """Mark the stream as completed and record metrics.

        Args:
            success: Whether the stream completed successfully.
                True for normal completion (done event).
                False for error completion (error event).
        """
        if self._completed:
            return

        self._completed = True

        # Record completion status
        status = "success" if success else "error"
        stream_completions.labels(status=status).inc()

        # Record total duration
        if self._stream_start_time is not None:
            duration = time.perf_counter() - self._stream_start_time
            stream_duration_histogram.observe(duration)

    def reset(self) -> None:
        """Reset the recorder for reuse."""
        self._ttft_tracker.reset()
        self._stream_start_time = None
        self._token_count = 0
        self._completed = False


def record_stream_success() -> None:
    """Record a successful stream completion.

    Convenience function for incrementing the success counter.
    """
    stream_completions.labels(status="success").inc()


def record_stream_error() -> None:
    """Record an error stream completion.

    Convenience function for incrementing the error counter.
    """
    stream_completions.labels(status="error").inc()
