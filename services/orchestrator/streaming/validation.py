"""Streaming event validation utilities.

This module provides validation utilities for ensuring SSE event sequences
conform to the streaming contract specification.

Contract Requirements:
    - Event order: start -> delta* -> citations -> done (or error at any point)
    - Start event: Must have request_id and model fields
    - Delta event: Must have token field
    - Citations event: Must have sources field
    - Done event: Must have usage and latency_ms fields
    - Error event: Must have error and code fields
"""

from .models import StreamEvent, StreamEventType


class EventValidationError(Exception):
    """Raised when event validation fails.

    Attributes:
        message: Human-readable error message describing the validation failure.
        event: The event that failed validation (if applicable).
        expected: What was expected (for sequence errors).
        actual: What was received (for sequence errors).
    """

    def __init__(
        self,
        message: str,
        event: StreamEvent | None = None,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        """Initialize the validation error.

        Args:
            message: Human-readable error message.
            event: The event that failed validation.
            expected: Expected value or state.
            actual: Actual value or state.
        """
        super().__init__(message)
        self.message = message
        self.event = event
        self.expected = expected
        self.actual = actual


class EventSequenceValidator:
    """Validates SSE event sequence matches contract.

    This validator ensures that streaming events follow the correct order
    as specified in the contract:
        1. Exactly one START event at the beginning
        2. Zero or more DELTA events
        3. Optional CITATIONS event (after all deltas)
        4. Exactly one DONE event at the end
        OR
        - ERROR event can occur at any point, terminating the sequence

    Attributes:
        events: List of validated events in sequence order.

    Example:
        ```python
        validator = EventSequenceValidator()

        # Add events as they arrive
        validator.add_event(start_event)
        validator.add_event(delta_event)
        validator.add_event(done_event)

        # Check if sequence is complete
        if validator.is_complete:
            validator.validate_sequence()
        ```
    """

    def __init__(self) -> None:
        """Initialize the sequence validator."""
        self._events: list[StreamEvent] = []
        self._has_start = False
        self._has_done = False
        self._has_error = False
        self._has_citations = False

    @property
    def events(self) -> list[StreamEvent]:
        """Get the list of events in sequence order."""
        return self._events.copy()

    @property
    def is_complete(self) -> bool:
        """Check if sequence is complete (has done or error).

        A sequence is complete when it has either:
        - A DONE event (successful completion)
        - An ERROR event (error termination)

        Returns:
            True if the sequence has a terminal event.
        """
        return self._has_done or self._has_error

    @property
    def has_start(self) -> bool:
        """Check if sequence has a start event."""
        return self._has_start

    @property
    def has_done(self) -> bool:
        """Check if sequence has a done event."""
        return self._has_done

    @property
    def has_error(self) -> bool:
        """Check if sequence has an error event."""
        return self._has_error

    @property
    def has_citations(self) -> bool:
        """Check if sequence has a citations event."""
        return self._has_citations

    @property
    def delta_count(self) -> int:
        """Get the number of delta events in the sequence."""
        return sum(1 for e in self._events if e.event == StreamEventType.DELTA)

    def add_event(self, event: StreamEvent) -> None:
        """Add event and validate sequence.

        This method validates that the event can be added at the current
        position in the sequence. It enforces the event ordering contract.

        Args:
            event: The event to add to the sequence.

        Raises:
            EventValidationError: If the event violates the sequence contract.

        Example:
            ```python
            validator = EventSequenceValidator()
            validator.add_event(StreamEvent.start("req-1", "llama"))
            validator.add_event(StreamEvent.delta("req-1", "Hello"))
            ```
        """
        # Validate the event structure first
        self._validate_event_structure(event)

        # Validate sequence ordering
        self._validate_sequence_position(event)

        # Update state and add event
        self._update_state(event)
        self._events.append(event)

    def _validate_event_structure(self, event: StreamEvent) -> None:
        """Validate event has required fields based on type.

        Args:
            event: The event to validate.

        Raises:
            EventValidationError: If required fields are missing.
        """
        if event.event == StreamEventType.START:
            if not validate_start_event(event):
                raise EventValidationError(
                    "Start event missing required fields: request_id, model",
                    event=event,
                )
        elif event.event == StreamEventType.DELTA:
            if not validate_delta_event(event):
                raise EventValidationError(
                    "Delta event missing required field: token",
                    event=event,
                )
        elif event.event == StreamEventType.CITATIONS:
            if not validate_citations_event(event):
                raise EventValidationError(
                    "Citations event missing required field: sources",
                    event=event,
                )
        elif event.event == StreamEventType.DONE:
            if not validate_done_event(event):
                raise EventValidationError(
                    "Done event missing required fields: usage, latency_ms",
                    event=event,
                )
        elif event.event == StreamEventType.ERROR and not validate_error_event(event):
            raise EventValidationError(
                "Error event missing required fields: error, code",
                event=event,
            )

    def _validate_sequence_position(self, event: StreamEvent) -> None:
        """Validate event can be added at current position.

        Args:
            event: The event to validate position for.

        Raises:
            EventValidationError: If event violates sequence ordering.
        """
        event_type = event.event

        # Cannot add events after sequence is complete
        if self.is_complete:
            raise EventValidationError(
                f"Cannot add {event_type.value} event after sequence is complete",
                event=event,
                expected="no more events",
                actual=event_type.value,
            )

        # ERROR can occur at any point (but not after completion)
        if event_type == StreamEventType.ERROR:
            return

        # START must be first
        if event_type == StreamEventType.START:
            if self._has_start:
                raise EventValidationError(
                    "Duplicate START event - sequence can only have one start",
                    event=event,
                )
            if len(self._events) > 0:
                raise EventValidationError(
                    "START event must be first in sequence",
                    event=event,
                    expected="start as first event",
                    actual=f"start after {len(self._events)} events",
                )
            return

        # All other events require START to have been received
        if not self._has_start:
            raise EventValidationError(
                f"{event_type.value} event received before START",
                event=event,
                expected="start event first",
                actual=event_type.value,
            )

        # DELTA can come after START or other DELTAs (but not after CITATIONS)
        if event_type == StreamEventType.DELTA:
            if self._has_citations:
                raise EventValidationError(
                    "DELTA event cannot come after CITATIONS",
                    event=event,
                    expected="delta before citations",
                    actual="delta after citations",
                )
            return

        # CITATIONS can only come once, after deltas
        if event_type == StreamEventType.CITATIONS:
            if self._has_citations:
                raise EventValidationError(
                    "Duplicate CITATIONS event - sequence can only have one",
                    event=event,
                )
            return

        # DONE must be last (after optional citations)
        if event_type == StreamEventType.DONE:
            return

    def _update_state(self, event: StreamEvent) -> None:
        """Update internal state based on event type.

        Args:
            event: The event that was validated.
        """
        event_type = event.event

        if event_type == StreamEventType.START:
            self._has_start = True
        elif event_type == StreamEventType.CITATIONS:
            self._has_citations = True
        elif event_type == StreamEventType.DONE:
            self._has_done = True
        elif event_type == StreamEventType.ERROR:
            self._has_error = True

    def validate_sequence(self) -> bool:
        """Validate complete sequence meets all requirements.

        This method should be called after all events have been added
        to verify the sequence is valid according to the contract.

        Returns:
            True if the sequence is valid.

        Raises:
            EventValidationError: If the sequence is invalid.

        Example:
            ```python
            validator = EventSequenceValidator()
            validator.add_event(start_event)
            validator.add_event(done_event)

            if validator.validate_sequence():
                print("Sequence is valid!")
            ```
        """
        # Must have at least one event
        if len(self._events) == 0:
            raise EventValidationError(
                "Empty sequence - must have at least start and done/error events",
                expected="start event",
                actual="empty sequence",
            )

        # Must start with START
        if not self._has_start:
            raise EventValidationError(
                "Sequence missing START event",
                expected="start event",
                actual="no start event",
            )

        # Must end with DONE or ERROR
        if not self.is_complete:
            raise EventValidationError(
                "Sequence incomplete - missing DONE or ERROR event",
                expected="done or error event",
                actual="incomplete sequence",
            )

        # Verify first event is START
        if self._events[0].event != StreamEventType.START:
            raise EventValidationError(
                "First event must be START",
                event=self._events[0],
                expected="start",
                actual=self._events[0].event.value,
            )

        # Verify last event is DONE or ERROR
        last_event = self._events[-1]
        if last_event.event not in (StreamEventType.DONE, StreamEventType.ERROR):
            raise EventValidationError(
                "Last event must be DONE or ERROR",
                event=last_event,
                expected="done or error",
                actual=last_event.event.value,
            )

        return True

    def reset(self) -> None:
        """Reset the validator state for reuse.

        This allows the same validator instance to be used for
        multiple sequences.

        Example:
            ```python
            validator = EventSequenceValidator()
            # ... validate first sequence ...
            validator.reset()
            # ... validate second sequence ...
            ```
        """
        self._events = []
        self._has_start = False
        self._has_done = False
        self._has_error = False
        self._has_citations = False


def validate_start_event(event: StreamEvent) -> bool:
    """Validate start event has required fields: request_id, model.

    Args:
        event: The start event to validate.

    Returns:
        True if the event has all required fields.

    Example:
        ```python
        event = StreamEvent.start("req-123", "llama")
        is_valid = validate_start_event(event)  # True
        ```
    """
    if event.event != StreamEventType.START:
        return False

    data = event.data
    has_request_id = "request_id" in data and bool(data["request_id"])
    has_model = "model" in data and bool(data["model"])

    return bool(has_request_id and has_model)


def validate_delta_event(event: StreamEvent) -> bool:
    """Validate delta event has required field: token.

    Note: Token can be an empty string, which is valid (e.g., for streaming
    whitespace or empty chunks).

    Args:
        event: The delta event to validate.

    Returns:
        True if the event has all required fields.

    Example:
        ```python
        event = StreamEvent.delta("req-123", "Hello")
        is_valid = validate_delta_event(event)  # True
        ```
    """
    if event.event != StreamEventType.DELTA:
        return False

    data = event.data
    # Token key must exist (empty string is valid)
    return "token" in data


def validate_citations_event(event: StreamEvent) -> bool:
    """Validate citations event has required field: sources.

    Args:
        event: The citations event to validate.

    Returns:
        True if the event has all required fields.

    Example:
        ```python
        event = StreamEvent.citations("req-123", [{"title": "Doc"}])
        is_valid = validate_citations_event(event)  # True
        ```
    """
    if event.event != StreamEventType.CITATIONS:
        return False

    data = event.data
    # Sources must exist (can be empty list)
    return "sources" in data and isinstance(data["sources"], list)


def validate_done_event(event: StreamEvent) -> bool:
    """Validate done event has required fields: usage, latency_ms.

    Args:
        event: The done event to validate.

    Returns:
        True if the event has all required fields.

    Example:
        ```python
        event = StreamEvent.done("req-123", {"total_tokens": 10}, 150.5)
        is_valid = validate_done_event(event)  # True
        ```
    """
    if event.event != StreamEventType.DONE:
        return False

    data = event.data
    has_usage = "usage" in data and isinstance(data["usage"], dict)
    has_latency = "latency_ms" in data

    return has_usage and has_latency


def validate_error_event(event: StreamEvent) -> bool:
    """Validate error event has required fields: error, code.

    Args:
        event: The error event to validate.

    Returns:
        True if the event has all required fields.

    Example:
        ```python
        event = StreamEvent.error("req-123", "Timeout", "TIMEOUT_ERROR")
        is_valid = validate_error_event(event)  # True
        ```
    """
    if event.event != StreamEventType.ERROR:
        return False

    data = event.data
    has_error = "error" in data and isinstance(data["error"], str)
    has_code = "code" in data and isinstance(data["code"], str)

    return has_error and has_code
