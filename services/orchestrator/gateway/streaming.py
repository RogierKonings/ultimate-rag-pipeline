"""SSE stream parsing for the Model Gateway.

This module provides utilities for parsing Server-Sent Events (SSE) streams
from LLM providers.
"""

import json
from typing import Any, AsyncGenerator

import httpx


async def parse_sse_stream(
    response: httpx.Response,
) -> AsyncGenerator[dict[str, Any], None]:
    """Parse an SSE stream from an HTTP response.

    This function handles the SSE format used by OpenAI-compatible APIs:
    - Each event starts with "data: " prefix
    - Events are separated by double newlines
    - Stream ends with "data: [DONE]"

    Args:
        response: The httpx Response object with streaming enabled.

    Yields:
        Parsed JSON objects from each SSE data line.

    Raises:
        json.JSONDecodeError: If a data line contains invalid JSON.

    Example:
        ```python
        async with client.stream("POST", "/chat/completions", json=request) as resp:
            async for chunk in parse_sse_stream(resp):
                print(chunk)
        ```
    """
    buffer = ""

    async for chunk in response.aiter_text():
        buffer += chunk

        # Process complete lines
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()

            # Skip empty lines (SSE format uses double newlines as separators)
            if not line:
                continue

            # Skip comments (lines starting with :)
            if line.startswith(":"):
                continue

            # Handle SSE data lines
            if line.startswith("data:"):
                data = line[5:].strip()

                # Check for stream end marker
                if data == "[DONE]":
                    return

                # Parse and yield JSON data
                if data:
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        # Log and continue on invalid JSON
                        continue


async def parse_sse_lines(
    lines: AsyncGenerator[str, None],
) -> AsyncGenerator[dict[str, Any], None]:
    """Parse SSE data from an async generator of lines.

    Alternative parser that works with pre-split lines.

    Args:
        lines: Async generator yielding individual lines.

    Yields:
        Parsed JSON objects from SSE data lines.
    """
    async for line in lines:
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith(":"):
            continue

        # Handle SSE data lines
        if line.startswith("data:"):
            data = line[5:].strip()

            # Check for stream end marker
            if data == "[DONE]":
                return

            # Parse and yield JSON data
            if data:
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue


def format_sse_event(data: dict[str, Any], event: str | None = None) -> str:
    """Format data as an SSE event string.

    Utility function for creating SSE-formatted strings.

    Args:
        data: The data to serialize as JSON.
        event: Optional event type.

    Returns:
        SSE-formatted string.

    Example:
        ```python
        sse_str = format_sse_event({"content": "Hello"}, event="delta")
        # Returns: "event: delta\ndata: {\"content\": \"Hello\"}\n\n"
        ```
    """
    lines = []

    if event:
        lines.append(f"event: {event}")

    lines.append(f"data: {json.dumps(data)}")
    lines.append("")  # Empty line for SSE format
    lines.append("")  # Double newline separator

    return "\n".join(lines)


def format_sse_done() -> str:
    """Format the SSE done marker.

    Returns:
        SSE-formatted done marker string.
    """
    return "data: [DONE]\n\n"


class SSEBuffer:
    """Buffer for accumulating SSE stream content.

    This class helps accumulate streaming content and track
    the complete response as it builds up.

    Attributes:
        content: The accumulated content string.
        chunks: List of individual chunks received.
        is_complete: Whether the stream has finished.
    """

    def __init__(self) -> None:
        """Initialize an empty buffer."""
        self.content: str = ""
        self.chunks: list[dict[str, Any]] = []
        self.is_complete: bool = False

    def append(self, chunk: dict[str, Any]) -> str | None:
        """Append a chunk to the buffer and extract content.

        Args:
            chunk: The parsed SSE chunk.

        Returns:
            The content delta from this chunk, or None if no content.
        """
        self.chunks.append(chunk)

        # Extract content from OpenAI-format chunk
        if "choices" in chunk and chunk["choices"]:
            choice = chunk["choices"][0]

            # Check for finish reason
            if choice.get("finish_reason"):
                self.is_complete = True

            # Extract delta content
            delta = choice.get("delta", {})
            content = delta.get("content")

            if content:
                self.content += content
                return content

        return None

    def get_full_content(self) -> str:
        """Get the complete accumulated content.

        Returns:
            The full content string.
        """
        return self.content

    def reset(self) -> None:
        """Reset the buffer to empty state."""
        self.content = ""
        self.chunks = []
        self.is_complete = False
