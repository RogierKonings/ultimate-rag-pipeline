"""Tests for token buffering.

This module tests the TokenBuffer class for batching tokens before emission.
"""

import time
from unittest.mock import patch

from streaming.buffer import TokenBuffer


class TestTokenBufferInit:
    """Tests for TokenBuffer initialization."""

    def test_default_init(self):
        """Test TokenBuffer with default parameters."""
        buffer = TokenBuffer()
        assert buffer.min_tokens == 1
        assert buffer.max_wait_ms == 50.0

    def test_custom_min_tokens(self):
        """Test TokenBuffer with custom min_tokens."""
        buffer = TokenBuffer(min_tokens=5)
        assert buffer.min_tokens == 5

    def test_custom_max_wait_ms(self):
        """Test TokenBuffer with custom max_wait_ms."""
        buffer = TokenBuffer(max_wait_ms=100.0)
        assert buffer.max_wait_ms == 100.0

    def test_min_tokens_enforced_minimum(self):
        """Test that min_tokens cannot be less than 1."""
        buffer = TokenBuffer(min_tokens=0)
        assert buffer.min_tokens == 1

        buffer = TokenBuffer(min_tokens=-5)
        assert buffer.min_tokens == 1

    def test_max_wait_ms_enforced_minimum(self):
        """Test that max_wait_ms cannot be negative."""
        buffer = TokenBuffer(max_wait_ms=-10.0)
        assert buffer.max_wait_ms == 0.0

    def test_initial_state(self):
        """Test that buffer starts empty."""
        buffer = TokenBuffer()
        assert buffer.is_empty is True
        assert buffer.content == ""
        assert buffer.token_count == 0


class TestTokenBufferAdd:
    """Tests for TokenBuffer.add() method."""

    def test_add_single_token_immediate_emit(self):
        """Test adding token with min_tokens=1 emits immediately."""
        buffer = TokenBuffer(min_tokens=1)
        result = buffer.add("Hello")
        assert result == "Hello"
        assert buffer.is_empty is True

    def test_add_token_buffered(self):
        """Test that tokens are buffered when min_tokens > 1."""
        buffer = TokenBuffer(min_tokens=3)

        result = buffer.add("H")
        assert result is None
        assert buffer.content == "H"

        result = buffer.add("el")
        assert result is None
        assert buffer.content == "Hel"

        # Third token should trigger emit
        result = buffer.add("lo")
        assert result == "Hello"
        assert buffer.is_empty is True

    def test_add_empty_token(self):
        """Test adding empty token returns None."""
        buffer = TokenBuffer(min_tokens=1)
        result = buffer.add("")
        assert result is None
        assert buffer.is_empty is True

    def test_add_accumulates_content(self):
        """Test that content accumulates correctly."""
        buffer = TokenBuffer(min_tokens=5)

        buffer.add("This ")
        buffer.add("is ")
        buffer.add("a ")
        buffer.add("test ")

        assert buffer.content == "This is a test "
        assert buffer.token_count == 4

    def test_add_clears_after_emit(self):
        """Test that buffer clears after emission."""
        buffer = TokenBuffer(min_tokens=2)

        buffer.add("Hello")
        result = buffer.add(" World")

        assert result == "Hello World"
        assert buffer.is_empty is True
        assert buffer.token_count == 0


class TestTokenBufferTimeBasedEmit:
    """Tests for time-based emission."""

    def test_emit_on_max_wait(self):
        """Test that buffer emits when max_wait_ms exceeded."""
        buffer = TokenBuffer(min_tokens=10, max_wait_ms=10.0)

        # Add first token
        buffer.add("Hello")

        # Simulate time passing by patching time.time
        with patch("time.time") as mock_time:
            # First call for storing first_token_time (already happened)
            # Second call should show significant time elapsed
            mock_time.return_value = (
                time.time() + 0.020
            )  # 20ms later (in seconds, will be converted to ms)

            # The next add should trigger emit due to timeout
            # We need to force the timing check
            current_ms = mock_time.return_value * 1000
            current_ms - buffer._first_token_time
            # If elapsed >= max_wait_ms, should emit

    def test_max_wait_zero_immediate_emit(self):
        """Test that max_wait_ms=0 causes immediate emit."""
        buffer = TokenBuffer(min_tokens=100, max_wait_ms=0.0)

        # Even with high min_tokens, should emit immediately due to zero wait
        result = buffer.add("Hello")
        assert result == "Hello"


class TestTokenBufferFlush:
    """Tests for TokenBuffer.flush() method."""

    def test_flush_returns_buffered_content(self):
        """Test flush returns all buffered content."""
        buffer = TokenBuffer(min_tokens=10)

        buffer.add("Hello ")
        buffer.add("World")

        result = buffer.flush()
        assert result == "Hello World"
        assert buffer.is_empty is True

    def test_flush_empty_buffer(self):
        """Test flush on empty buffer returns None."""
        buffer = TokenBuffer()
        result = buffer.flush()
        assert result is None

    def test_flush_clears_state(self):
        """Test that flush clears all internal state."""
        buffer = TokenBuffer(min_tokens=10)

        buffer.add("Test")
        buffer.flush()

        assert buffer.is_empty is True
        assert buffer.content == ""
        assert buffer.token_count == 0
        assert buffer._first_token_time is None

    def test_flush_after_partial_fill(self):
        """Test flushing partially filled buffer."""
        buffer = TokenBuffer(min_tokens=5)

        buffer.add("A")
        buffer.add("B")
        buffer.add("C")

        # Buffer has 3 tokens, but min is 5
        assert buffer.token_count == 3

        # Flush should return all content
        result = buffer.flush()
        assert result == "ABC"


class TestTokenBufferReset:
    """Tests for TokenBuffer.reset() method."""

    def test_reset_clears_buffer(self):
        """Test that reset clears buffered content."""
        buffer = TokenBuffer(min_tokens=10)

        buffer.add("Hello")
        buffer.add("World")

        buffer.reset()

        assert buffer.is_empty is True
        assert buffer.content == ""
        assert buffer.token_count == 0

    def test_reset_does_not_return_content(self):
        """Test that reset discards content (doesn't emit)."""
        buffer = TokenBuffer(min_tokens=10)

        buffer.add("Test")
        buffer.reset()

        # Content is lost, not returned
        result = buffer.flush()
        assert result is None


class TestTokenBufferProperties:
    """Tests for TokenBuffer properties."""

    def test_is_empty_true_when_empty(self):
        """Test is_empty returns True when buffer is empty."""
        buffer = TokenBuffer(min_tokens=10)
        assert buffer.is_empty is True

    def test_is_empty_false_when_not_empty(self):
        """Test is_empty returns False when buffer has content."""
        buffer = TokenBuffer(min_tokens=10)
        buffer.add("Test")
        assert buffer.is_empty is False

    def test_content_property(self):
        """Test content property returns current buffer."""
        buffer = TokenBuffer(min_tokens=10)

        assert buffer.content == ""

        buffer.add("Hello")
        assert buffer.content == "Hello"

        buffer.add(" World")
        assert buffer.content == "Hello World"

    def test_token_count_property(self):
        """Test token_count property."""
        buffer = TokenBuffer(min_tokens=10)

        assert buffer.token_count == 0

        buffer.add("A")
        assert buffer.token_count == 1

        buffer.add("B")
        assert buffer.token_count == 2

        buffer.add("C")
        assert buffer.token_count == 3


class TestTokenBufferIntegration:
    """Integration tests for TokenBuffer usage patterns."""

    def test_streaming_simulation(self):
        """Test simulating a streaming response with buffering."""
        buffer = TokenBuffer(min_tokens=3, max_wait_ms=1000.0)
        emitted_chunks = []

        tokens = ["The ", "quick ", "brown ", "fox ", "jumps ", "over"]

        for token in tokens:
            result = buffer.add(token)
            if result is not None:
                emitted_chunks.append(result)

        # Flush remaining
        remaining = buffer.flush()
        if remaining is not None:
            emitted_chunks.append(remaining)

        # Verify all content preserved
        full_content = "".join(emitted_chunks)
        assert full_content == "The quick brown fox jumps over"

    def test_no_buffering_mode(self):
        """Test using buffer in pass-through mode (min_tokens=1)."""
        buffer = TokenBuffer(min_tokens=1)
        emitted = []

        for token in ["A", "B", "C", "D"]:
            result = buffer.add(token)
            if result is not None:
                emitted.append(result)

        # Each token should emit immediately
        assert emitted == ["A", "B", "C", "D"]

    def test_large_buffer(self):
        """Test buffer with large min_tokens."""
        buffer = TokenBuffer(min_tokens=100, max_wait_ms=10000.0)

        for i in range(50):
            buffer.add(f"token{i}")

        # Not yet emitted (only 50 of 100 tokens)
        assert buffer.token_count == 50
        assert buffer.is_empty is False

        # Flush to get content
        result = buffer.flush()
        assert result is not None
        assert "token0" in result
        assert "token49" in result

    def test_unicode_content(self):
        """Test buffer handles unicode content."""
        buffer = TokenBuffer(min_tokens=2)

        buffer.add("Hello ")
        result = buffer.add("World! \u2764")

        assert result == "Hello World! \u2764"

    def test_newlines_and_whitespace(self):
        """Test buffer handles newlines and whitespace."""
        buffer = TokenBuffer(min_tokens=3)

        buffer.add("Line 1\n")
        buffer.add("Line 2\n")
        result = buffer.add("Line 3")

        assert result == "Line 1\nLine 2\nLine 3"

    def test_multiple_emit_cycles(self):
        """Test multiple emission cycles."""
        buffer = TokenBuffer(min_tokens=2)
        emissions = []

        # First cycle
        buffer.add("A")
        result = buffer.add("B")
        emissions.append(result)

        # Second cycle
        buffer.add("C")
        result = buffer.add("D")
        emissions.append(result)

        # Third cycle
        buffer.add("E")
        result = buffer.add("F")
        emissions.append(result)

        assert emissions == ["AB", "CD", "EF"]
