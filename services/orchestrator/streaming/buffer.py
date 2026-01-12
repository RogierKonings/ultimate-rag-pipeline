"""Token buffering for streaming responses.

This module provides a buffer for batching small tokens before emission,
which can improve client-side rendering performance by reducing the
number of small updates.
"""

import time


class TokenBuffer:
    """Buffer for batching tokens before emission.

    This class accumulates tokens and releases them in batches based on
    either token count or time elapsed, whichever threshold is reached first.

    This is useful for:
    - Reducing client render overhead from very small token updates
    - Batching subword tokens into more readable chunks
    - Smoothing out bursty token delivery

    Attributes:
        min_tokens: Minimum tokens to accumulate before emitting.
        max_wait_ms: Maximum time to wait before forcing emission.

    Example:
        ```python
        buffer = TokenBuffer(min_tokens=3, max_wait_ms=50.0)

        # Small tokens get buffered
        result = buffer.add("H")  # None
        result = buffer.add("el")  # None
        result = buffer.add("lo")  # "Hello" (3 tokens reached)

        # Or force flush remaining content
        buffer.add(" wor")
        remaining = buffer.flush()  # " wor"
        ```
    """

    def __init__(
        self,
        min_tokens: int = 1,
        max_wait_ms: float = 50.0,
    ) -> None:
        """Initialize the token buffer.

        Args:
            min_tokens: Minimum number of tokens to buffer before emitting.
                Set to 1 to emit immediately (no buffering).
            max_wait_ms: Maximum time in milliseconds to wait before
                emitting buffered content, regardless of token count.
        """
        self.min_tokens = max(1, min_tokens)
        self.max_wait_ms = max(0.0, max_wait_ms)

        self._buffer: str = ""
        self._token_count: int = 0
        self._first_token_time: float | None = None

    def add(self, token: str) -> str | None:
        """Add a token to the buffer.

        If the buffer reaches the minimum token count or max wait time,
        the accumulated content is returned and the buffer is cleared.

        Args:
            token: The token to add to the buffer.

        Returns:
            The accumulated content if ready to emit, None otherwise.
        """
        if not token:
            return None

        # Track first token time for timeout calculation
        current_time = time.time() * 1000  # Convert to ms
        if self._first_token_time is None:
            self._first_token_time = current_time

        self._buffer += token
        self._token_count += 1

        # Check if we should emit
        if self._should_emit(current_time):
            return self._emit()

        return None

    def _should_emit(self, current_time: float) -> bool:
        """Check if the buffer should emit its content.

        Args:
            current_time: Current time in milliseconds.

        Returns:
            True if the buffer should emit, False otherwise.
        """
        # Emit if we have enough tokens
        if self._token_count >= self.min_tokens:
            return True

        # Emit if we've waited too long
        if self._first_token_time is not None:
            elapsed = current_time - self._first_token_time
            if elapsed >= self.max_wait_ms:
                return True

        return False

    def _emit(self) -> str:
        """Emit buffered content and reset state.

        Returns:
            The accumulated content.
        """
        content = self._buffer
        self._buffer = ""
        self._token_count = 0
        self._first_token_time = None
        return content

    def flush(self) -> str | None:
        """Force flush any remaining buffered content.

        This should be called at the end of streaming to ensure
        no content is left in the buffer.

        Returns:
            The remaining content, or None if buffer is empty.
        """
        if self._buffer:
            return self._emit()
        return None

    def reset(self) -> None:
        """Reset the buffer to its initial state.

        Discards any buffered content without emitting it.
        """
        self._buffer = ""
        self._token_count = 0
        self._first_token_time = None

    @property
    def is_empty(self) -> bool:
        """Check if the buffer is empty.

        Returns:
            True if the buffer contains no content.
        """
        return len(self._buffer) == 0

    @property
    def content(self) -> str:
        """Get the current buffer content without emitting.

        Returns:
            The current buffered content.
        """
        return self._buffer

    @property
    def token_count(self) -> int:
        """Get the current token count.

        Returns:
            Number of tokens currently buffered.
        """
        return self._token_count
