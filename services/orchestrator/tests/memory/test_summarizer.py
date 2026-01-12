"""Unit tests for HistorySummarizer."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from memory.models import MemoryConfig, Message, MessageRole
from memory.summarizer import HistorySummarizer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def memory_config():
    """Create test memory configuration."""
    return MemoryConfig(
        summary_model="test-model",
        summary_max_tokens=500,
    )


@pytest.fixture
def sample_messages():
    """Create sample messages for testing."""
    return [
        Message(role=MessageRole.USER, content="What is Python?"),
        Message(
            role=MessageRole.ASSISTANT,
            content="Python is a high-level programming language.",
        ),
        Message(role=MessageRole.USER, content="How do I learn it?"),
        Message(
            role=MessageRole.ASSISTANT,
            content="You can start with online tutorials and practice.",
        ),
    ]


# ============================================================================
# Simple Summary Tests (Fallback)
# ============================================================================


@pytest.mark.asyncio
async def test_summarizer_simple_fallback(memory_config, sample_messages):
    """Test simple summary without LLM."""
    summarizer = HistorySummarizer(memory_config)

    summary = await summarizer.summarize(sample_messages)

    assert len(summary) > 0
    # Should contain topics from user messages
    assert "Topics discussed" in summary


@pytest.mark.asyncio
async def test_summarizer_empty_messages(memory_config):
    """Test summarization with no messages."""
    summarizer = HistorySummarizer(memory_config)

    summary = await summarizer.summarize([])

    assert summary == ""


@pytest.mark.asyncio
async def test_summarizer_only_assistant_messages(memory_config):
    """Test summarization with only assistant messages."""
    messages = [
        Message(role=MessageRole.ASSISTANT, content="Hello!"),
        Message(role=MessageRole.ASSISTANT, content="How can I help?"),
    ]

    summarizer = HistorySummarizer(memory_config)

    summary = await summarizer.summarize(messages)

    assert summary == "Previous conversation context."


@pytest.mark.asyncio
async def test_summarizer_truncates_long_topics(memory_config):
    """Test that long messages are truncated in summary."""
    long_content = "This is a very long message " * 50  # Much longer than 100 chars
    messages = [
        Message(role=MessageRole.USER, content=long_content),
    ]

    summarizer = HistorySummarizer(memory_config)

    summary = await summarizer.summarize(messages)

    # Summary should not contain the full long message
    assert len(summary) < len(long_content)


@pytest.mark.asyncio
async def test_summarizer_uses_last_five_messages(memory_config):
    """Test that summary uses last 5 user messages."""
    messages = [
        Message(role=MessageRole.USER, content=f"Topic {i}")
        for i in range(10)
    ]

    summarizer = HistorySummarizer(memory_config)

    summary = await summarizer.summarize(messages)

    # Should contain topics from later messages
    assert "Topic 9" in summary or "Topic 8" in summary


# ============================================================================
# LLM-based Summary Tests
# ============================================================================


@pytest.mark.asyncio
async def test_summarizer_with_gateway(memory_config, sample_messages):
    """Test LLM-based summarization."""
    gateway = AsyncMock()
    gateway.chat_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Summary of discussion."))],
    )

    summarizer = HistorySummarizer(memory_config, gateway)

    summary = await summarizer.summarize(sample_messages)

    assert summary == "Summary of discussion."
    gateway.chat_completion.assert_called()


@pytest.mark.asyncio
async def test_summarizer_with_existing_summary(memory_config, sample_messages):
    """Test summarization with existing summary."""
    gateway = AsyncMock()
    gateway.chat_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Updated summary."))],
    )

    summarizer = HistorySummarizer(memory_config, gateway)

    existing_summary = "Previous topics included Python basics."

    summary = await summarizer.summarize(sample_messages, existing_summary)

    assert summary == "Updated summary."

    # Check that existing summary was included in the prompt
    call_args = gateway.chat_completion.call_args[0][0]
    # The prompt should include the existing summary
    assert hasattr(call_args, "messages")


@pytest.mark.asyncio
async def test_summarizer_gateway_error_fallback(memory_config, sample_messages):
    """Test fallback when gateway fails."""
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = Exception("Gateway error")

    summarizer = HistorySummarizer(memory_config, gateway)

    summary = await summarizer.summarize(sample_messages)

    # Should fall back to simple summary
    assert len(summary) > 0
    assert "Topics discussed" in summary or "Python" in summary


# ============================================================================
# Message Formatting Tests
# ============================================================================


def test_format_messages(memory_config, sample_messages):
    """Test message formatting for prompt."""
    summarizer = HistorySummarizer(memory_config)

    formatted = summarizer._format_messages(sample_messages)

    assert "User:" in formatted
    assert "Assistant:" in formatted
    assert "Python" in formatted


def test_format_messages_truncates_long_content(memory_config):
    """Test that long message content is truncated."""
    long_content = "A" * 600  # Longer than 500 chars
    messages = [
        Message(role=MessageRole.USER, content=long_content),
    ]

    summarizer = HistorySummarizer(memory_config)

    formatted = summarizer._format_messages(messages)

    # Should be truncated with ellipsis
    assert "..." in formatted
    assert len(formatted) < len(long_content)


def test_format_messages_empty(memory_config):
    """Test formatting empty message list."""
    summarizer = HistorySummarizer(memory_config)

    formatted = summarizer._format_messages([])

    assert formatted == ""


def test_format_messages_all_roles(memory_config):
    """Test formatting all message roles."""
    messages = [
        Message(role=MessageRole.SYSTEM, content="System message"),
        Message(role=MessageRole.USER, content="User message"),
        Message(role=MessageRole.ASSISTANT, content="Assistant message"),
        Message(role=MessageRole.FUNCTION, content="Function result"),
    ]

    summarizer = HistorySummarizer(memory_config)

    formatted = summarizer._format_messages(messages)

    assert "System:" in formatted
    assert "User:" in formatted
    assert "Assistant:" in formatted
    assert "Function:" in formatted
