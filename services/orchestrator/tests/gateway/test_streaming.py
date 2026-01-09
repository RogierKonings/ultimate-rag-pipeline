"""Unit tests for SSE stream parsing utilities."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.streaming import (
    parse_sse_stream,
    parse_sse_lines,
    format_sse_event,
    format_sse_done,
    SSEBuffer,
)


# ============================================================================
# parse_sse_stream Tests
# ============================================================================


@pytest.mark.asyncio
async def test_parse_sse_stream_basic():
    """Test basic SSE stream parsing."""
    sse_data = [
        'data: {"id": "1", "content": "Hello"}\n\n',
        'data: {"id": "2", "content": "World"}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0]["id"] == "1"
    assert chunks[0]["content"] == "Hello"
    assert chunks[1]["id"] == "2"
    assert chunks[1]["content"] == "World"


@pytest.mark.asyncio
async def test_parse_sse_stream_with_newlines_in_data():
    """Test SSE parsing when chunks arrive split across newlines."""
    # Simulate data arriving in smaller pieces
    sse_data = [
        'data: {"id": "1"',
        ', "content": "Hello"}\n',
        "\n",
        'data: {"id": "2", "content": "World"}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_parse_sse_stream_empty_lines():
    """Test that empty lines are handled correctly."""
    sse_data = [
        "\n",
        "\n",
        'data: {"id": "1"}\n\n',
        "\n",
        'data: {"id": "2"}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_parse_sse_stream_comments():
    """Test that SSE comments (lines starting with :) are ignored."""
    sse_data = [
        ": This is a comment\n",
        'data: {"id": "1"}\n\n',
        ": Another comment\n",
        'data: {"id": "2"}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_parse_sse_stream_invalid_json():
    """Test that invalid JSON is skipped."""
    sse_data = [
        'data: {"id": "1"}\n\n',
        "data: not valid json\n\n",
        'data: {"id": "2"}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    # Invalid JSON should be skipped
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_parse_sse_stream_openai_format():
    """Test parsing OpenAI-style streaming response."""
    sse_data = [
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 4
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[1]["choices"][0]["delta"]["content"] == "Hello"
    assert chunks[2]["choices"][0]["delta"]["content"] == "!"
    assert chunks[3]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_parse_sse_stream_no_done_marker():
    """Test parsing stream that ends without [DONE] marker."""
    sse_data = [
        'data: {"id": "1"}\n\n',
        'data: {"id": "2"}\n\n',
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    chunks = []
    async for chunk in parse_sse_stream(mock_response):
        chunks.append(chunk)

    assert len(chunks) == 2


# ============================================================================
# parse_sse_lines Tests
# ============================================================================


@pytest.mark.asyncio
async def test_parse_sse_lines_basic():
    """Test basic line-based SSE parsing."""

    async def mock_lines():
        lines = [
            'data: {"id": "1"}',
            "",
            'data: {"id": "2"}',
            "",
            "data: [DONE]",
        ]
        for line in lines:
            yield line

    chunks = []
    async for chunk in parse_sse_lines(mock_lines()):
        chunks.append(chunk)

    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_parse_sse_lines_with_comments():
    """Test line-based parsing with comments."""

    async def mock_lines():
        lines = [
            ": comment",
            'data: {"id": "1"}',
            ": another comment",
            'data: {"id": "2"}',
            "data: [DONE]",
        ]
        for line in lines:
            yield line

    chunks = []
    async for chunk in parse_sse_lines(mock_lines()):
        chunks.append(chunk)

    assert len(chunks) == 2


# ============================================================================
# format_sse_event Tests
# ============================================================================


def test_format_sse_event_basic():
    """Test basic SSE event formatting."""
    data = {"content": "Hello"}
    result = format_sse_event(data)

    assert "data: " in result
    assert '{"content": "Hello"}' in result
    assert result.endswith("\n\n")


def test_format_sse_event_with_event_type():
    """Test SSE event formatting with event type."""
    data = {"content": "Hello"}
    result = format_sse_event(data, event="delta")

    assert "event: delta\n" in result
    assert '{"content": "Hello"}' in result


def test_format_sse_event_complex_data():
    """Test SSE event formatting with complex data."""
    data = {
        "choices": [
            {
                "index": 0,
                "delta": {"content": "Hello"},
                "finish_reason": None,
            }
        ]
    }
    result = format_sse_event(data)

    # Parse the data line to verify JSON
    for line in result.split("\n"):
        if line.startswith("data: "):
            parsed = json.loads(line[6:])
            assert parsed == data


def test_format_sse_done():
    """Test SSE done marker formatting."""
    result = format_sse_done()

    assert result == "data: [DONE]\n\n"


# ============================================================================
# SSEBuffer Tests
# ============================================================================


def test_sse_buffer_init():
    """Test SSEBuffer initialization."""
    buffer = SSEBuffer()

    assert buffer.content == ""
    assert buffer.chunks == []
    assert buffer.is_complete is False


def test_sse_buffer_append_content():
    """Test appending content chunks to buffer."""
    buffer = SSEBuffer()

    chunk1 = {"choices": [{"delta": {"content": "Hello"}}]}
    chunk2 = {"choices": [{"delta": {"content": " world"}}]}

    result1 = buffer.append(chunk1)
    result2 = buffer.append(chunk2)

    assert result1 == "Hello"
    assert result2 == " world"
    assert buffer.content == "Hello world"
    assert len(buffer.chunks) == 2


def test_sse_buffer_append_no_content():
    """Test appending chunks without content."""
    buffer = SSEBuffer()

    # First chunk might have role but no content
    chunk = {"choices": [{"delta": {"role": "assistant"}}]}
    result = buffer.append(chunk)

    assert result is None
    assert buffer.content == ""
    assert len(buffer.chunks) == 1


def test_sse_buffer_finish_reason():
    """Test detecting finish reason."""
    buffer = SSEBuffer()

    chunk1 = {"choices": [{"delta": {"content": "Hello"}}]}
    chunk2 = {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    buffer.append(chunk1)
    buffer.append(chunk2)

    assert buffer.is_complete is True


def test_sse_buffer_get_full_content():
    """Test getting full accumulated content."""
    buffer = SSEBuffer()

    chunks = [
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " "}}]},
        {"choices": [{"delta": {"content": "world"}}]},
        {"choices": [{"delta": {"content": "!"}}]},
    ]

    for chunk in chunks:
        buffer.append(chunk)

    assert buffer.get_full_content() == "Hello world!"


def test_sse_buffer_reset():
    """Test resetting the buffer."""
    buffer = SSEBuffer()

    buffer.append({"choices": [{"delta": {"content": "Test"}}]})
    buffer.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})

    assert buffer.content == "Test"
    assert buffer.is_complete is True

    buffer.reset()

    assert buffer.content == ""
    assert buffer.chunks == []
    assert buffer.is_complete is False


def test_sse_buffer_empty_choices():
    """Test handling chunks with empty choices."""
    buffer = SSEBuffer()

    chunk = {"choices": []}
    result = buffer.append(chunk)

    assert result is None
    assert buffer.content == ""


def test_sse_buffer_no_choices():
    """Test handling chunks without choices key."""
    buffer = SSEBuffer()

    chunk = {"id": "test", "object": "chat.completion.chunk"}
    result = buffer.append(chunk)

    assert result is None
    assert buffer.content == ""


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_parse_and_buffer_integration():
    """Test integration of parsing and buffering."""
    sse_data = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" "}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"world!"}}]}\n\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    buffer = SSEBuffer()

    async for chunk in parse_sse_stream(mock_response):
        buffer.append(chunk)

    assert buffer.get_full_content() == "Hello world!"
    assert buffer.is_complete is True
    assert len(buffer.chunks) == 5


@pytest.mark.asyncio
async def test_streaming_tokens_collected():
    """Test collecting individual tokens from stream."""
    sse_data = [
        'data: {"choices":[{"delta":{"content":"The"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" quick"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" brown"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" fox"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text

    tokens = []
    async for chunk in parse_sse_stream(mock_response):
        if "choices" in chunk and chunk["choices"]:
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                tokens.append(content)

    assert tokens == ["The", " quick", " brown", " fox"]
    assert "".join(tokens) == "The quick brown fox"
