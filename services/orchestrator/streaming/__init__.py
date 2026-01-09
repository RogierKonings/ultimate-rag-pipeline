"""Streaming module for Server-Sent Events (SSE) support.

This module provides components for streaming LLM responses with proper
event sequencing, token buffering, SSE formatting, validation, and metrics.

Exports:
    Event Types and Models:
        - StreamEventType: Enum of event types (START, DELTA, CITATIONS, DONE, ERROR)
        - StreamEvent: SSE event model with to_sse() method
        - StartEventData: Data payload for start events
        - DeltaEventData: Data payload for delta events
        - CitationsEventData: Data payload for citation events
        - DoneEventData: Data payload for done events
        - ErrorEventData: Data payload for error events

    Buffering:
        - TokenBuffer: Buffer for batching tokens before emission

    Manager:
        - StreamManager: Manager for orchestrating streaming responses

    Validation:
        - EventValidationError: Exception for validation failures
        - EventSequenceValidator: Validates SSE event sequences
        - validate_start_event: Validate start event structure
        - validate_delta_event: Validate delta event structure
        - validate_citations_event: Validate citations event structure
        - validate_done_event: Validate done event structure
        - validate_error_event: Validate error event structure

    Metrics:
        - TTFTTracker: Track Time to First Token
        - StreamMetricsRecorder: Record comprehensive streaming metrics
        - ttft_histogram: Prometheus histogram for TTFT
        - stream_completions: Prometheus counter for stream completions
        - stream_duration_histogram: Prometheus histogram for stream duration
        - record_stream_success: Convenience function for success counter
        - record_stream_error: Convenience function for error counter
"""

from .buffer import TokenBuffer
from .manager import StreamManager
from .metrics import (
    StreamMetricsRecorder,
    TTFTTracker,
    record_stream_error,
    record_stream_success,
    stream_completions,
    stream_duration_histogram,
    ttft_histogram,
)
from .models import (
    CitationsEventData,
    DeltaEventData,
    DoneEventData,
    ErrorEventData,
    StartEventData,
    StreamEvent,
    StreamEventType,
)
from .validation import (
    EventSequenceValidator,
    EventValidationError,
    validate_citations_event,
    validate_delta_event,
    validate_done_event,
    validate_error_event,
    validate_start_event,
)

__all__ = [
    # Event types and models
    "StreamEventType",
    "StreamEvent",
    "StartEventData",
    "DeltaEventData",
    "CitationsEventData",
    "DoneEventData",
    "ErrorEventData",
    # Buffer
    "TokenBuffer",
    # Manager
    "StreamManager",
    # Validation
    "EventValidationError",
    "EventSequenceValidator",
    "validate_start_event",
    "validate_delta_event",
    "validate_citations_event",
    "validate_done_event",
    "validate_error_event",
    # Metrics
    "TTFTTracker",
    "StreamMetricsRecorder",
    "ttft_histogram",
    "stream_completions",
    "stream_duration_histogram",
    "record_stream_success",
    "record_stream_error",
]
