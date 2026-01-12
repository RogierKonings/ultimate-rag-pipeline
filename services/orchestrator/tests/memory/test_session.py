"""Unit tests for SessionManager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from memory.models import (
    ConversationSession,
    MemoryConfig,
    Message,
    MessageRole,
)
from memory.session import SessionManager
from memory.store import RedisSessionStore
from memory.summarizer import HistorySummarizer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def memory_config():
    """Create test memory configuration."""
    return MemoryConfig(
        session_ttl=3600,
        max_sessions_per_user=10,
        max_messages=50,
        max_tokens=4096,
        enable_summarization=True,
        summarize_after_messages=20,
        redis_prefix="test:session:",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
def mock_tokenizer():
    """Create a mock tokenizer."""
    tokenizer = MagicMock()
    # Simple tokenizer: count words
    tokenizer.count = lambda x: len(x.split())
    return tokenizer


@pytest.fixture
def mock_store(mock_redis):
    """Create a mock RedisSessionStore."""
    store = AsyncMock(spec=RedisSessionStore)
    store._redis = mock_redis
    return store


@pytest.fixture
def session_manager(mock_store, memory_config, mock_tokenizer):
    """Create SessionManager with mocked dependencies."""
    return SessionManager(
        store=mock_store,
        config=memory_config,
        tokenizer=mock_tokenizer,
    )


# ============================================================================
# Create Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_session(session_manager, mock_store):
    """Test session creation."""
    user_id = uuid4()
    tenant_id = uuid4()
    system_prompt = "You are helpful."

    expected_session = ConversationSession(
        user_id=user_id,
        tenant_id=tenant_id,
        system_prompt=system_prompt,
    )
    mock_store.create_session.return_value = expected_session

    session = await session_manager.create_session(
        user_id=user_id,
        tenant_id=tenant_id,
        system_prompt=system_prompt,
    )

    assert session.user_id == user_id
    assert session.tenant_id == tenant_id
    assert session.system_prompt == system_prompt
    mock_store.create_session.assert_called_once()


# ============================================================================
# Add Message Tests
# ============================================================================


@pytest.mark.asyncio
async def test_add_message(session_manager, mock_store):
    """Test adding a message."""
    session_id = uuid4()
    session = ConversationSession(id=session_id)

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    message = await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "Hello, how are you?",
    )

    assert message.role == MessageRole.USER
    assert message.content == "Hello, how are you?"
    assert message.token_count == 4  # "Hello, how are you?" -> 4 words
    mock_store.update_session.assert_called()
    mock_store.extend_ttl.assert_called_with(session_id)


@pytest.mark.asyncio
async def test_add_message_session_not_found(session_manager, mock_store):
    """Test adding message to non-existent session."""
    mock_store.get_session.return_value = None

    with pytest.raises(ValueError, match="Session not found"):
        await session_manager.add_message(
            uuid4(),
            MessageRole.USER,
            "Hello",
        )


@pytest.mark.asyncio
async def test_add_message_with_sources(session_manager, mock_store):
    """Test adding message with source references."""
    session_id = uuid4()
    session = ConversationSession(id=session_id)
    sources = ["doc1.pdf", "doc2.md"]

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    message = await session_manager.add_message(
        session_id,
        MessageRole.ASSISTANT,
        "Based on the documents...",
        sources=sources,
    )

    assert message.sources == sources


@pytest.mark.asyncio
async def test_add_user_message(session_manager, mock_store):
    """Test adding user message convenience method."""
    session_id = uuid4()
    session = ConversationSession(id=session_id)

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    message = await session_manager.add_user_message(session_id, "Hello!")

    assert message.role == MessageRole.USER
    assert message.content == "Hello!"


@pytest.mark.asyncio
async def test_add_assistant_message(session_manager, mock_store):
    """Test adding assistant message convenience method."""
    session_id = uuid4()
    session = ConversationSession(id=session_id)
    sources = ["source1.pdf"]

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    message = await session_manager.add_assistant_message(
        session_id,
        "Here is my response.",
        sources=sources,
    )

    assert message.role == MessageRole.ASSISTANT
    assert message.content == "Here is my response."
    assert message.sources == sources


@pytest.mark.asyncio
async def test_add_message_updates_session_stats(session_manager, mock_store):
    """Test that adding message updates session statistics."""
    session_id = uuid4()
    session = ConversationSession(id=session_id, total_messages=5, total_tokens=100)

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message",  # 2 words
    )

    # Check session was updated with new counts
    updated_session = mock_store.update_session.call_args[0][0]
    assert updated_session.total_messages == 6
    assert updated_session.total_tokens == 102  # 100 + 2


# ============================================================================
# Get History Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_history(session_manager, mock_store):
    """Test history retrieval."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        system_prompt="You are helpful.",
        messages=[
            Message(role=MessageRole.USER, content="Hi", token_count=1),
            Message(role=MessageRole.ASSISTANT, content="Hello!", token_count=1),
        ],
    )

    mock_store.get_session.return_value = session

    history = await session_manager.get_history(session_id)

    # Should include system prompt + messages
    assert len(history) == 3
    assert history[0].role == MessageRole.SYSTEM
    assert history[0].content == "You are helpful."


@pytest.mark.asyncio
async def test_get_history_without_system(session_manager, mock_store):
    """Test history retrieval without system message."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        system_prompt="You are helpful.",
        messages=[
            Message(role=MessageRole.USER, content="Hi", token_count=1),
        ],
    )

    mock_store.get_session.return_value = session

    history = await session_manager.get_history(session_id, include_system=False)

    # Should not include system prompt
    assert len(history) == 1
    assert history[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_get_history_with_summary(session_manager, mock_store):
    """Test history retrieval with summary."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        summary="Previous discussion about Python.",
        messages=[
            Message(role=MessageRole.USER, content="Continue", token_count=1),
        ],
    )

    mock_store.get_session.return_value = session

    history = await session_manager.get_history(session_id)

    # Should include summary as system message
    assert len(history) == 2
    assert "Summary of earlier conversation" in history[0].content
    assert "Previous discussion about Python" in history[0].content


@pytest.mark.asyncio
async def test_get_history_with_token_limit(session_manager, mock_store):
    """Test history respects token limits."""
    session_id = uuid4()

    # Create many messages with token counts
    messages = [
        Message(
            role=MessageRole.USER,
            content="This is a message with many words to test token limits",
            token_count=10,
        )
        for _ in range(10)
    ]

    session = ConversationSession(id=session_id, messages=messages)
    mock_store.get_session.return_value = session

    # Request with low token limit
    history = await session_manager.get_history(session_id, max_tokens=25)

    # Should only include messages that fit within limit
    assert len(history) < len(messages)


@pytest.mark.asyncio
async def test_get_history_session_not_found(session_manager, mock_store):
    """Test history retrieval for non-existent session."""
    mock_store.get_session.return_value = None

    history = await session_manager.get_history(uuid4())

    assert history == []


@pytest.mark.asyncio
async def test_get_history_for_llm(session_manager, mock_store):
    """Test history formatted for LLM API."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content="Hello", token_count=1),
            Message(role=MessageRole.ASSISTANT, content="Hi!", token_count=1),
        ],
    )

    mock_store.get_session.return_value = session

    history = await session_manager.get_history_for_llm(session_id)

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Hello"}
    assert history[1] == {"role": "assistant", "content": "Hi!"}


# ============================================================================
# Clear Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_clear_session(session_manager, mock_store):
    """Test clearing session messages."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[Message(role=MessageRole.USER, content="Hi", token_count=1)],
        summary="Previous conversation",
        summarized_count=5,
        total_messages=5,
        total_tokens=50,
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()

    result = await session_manager.clear_session(session_id)

    assert result is True
    mock_store.update_session.assert_called()

    # Check session was cleared
    updated_session = mock_store.update_session.call_args[0][0]
    assert len(updated_session.messages) == 0
    assert updated_session.summary is None
    assert updated_session.summarized_count == 0
    assert updated_session.total_messages == 0
    assert updated_session.total_tokens == 0


@pytest.mark.asyncio
async def test_clear_session_not_found(session_manager, mock_store):
    """Test clearing non-existent session."""
    mock_store.get_session.return_value = None

    result = await session_manager.clear_session(uuid4())

    assert result is False


# ============================================================================
# Delete Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_delete_session(session_manager, mock_store):
    """Test deleting a session."""
    session_id = uuid4()
    mock_store.delete_session.return_value = True

    result = await session_manager.delete_session(session_id)

    assert result is True
    mock_store.delete_session.assert_called_with(session_id)


# ============================================================================
# Session Stats Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_session_stats(session_manager, mock_store):
    """Test session statistics."""
    session_id = uuid4()
    now = datetime.now(tz=UTC)
    session = ConversationSession(
        id=session_id,
        messages=[Message(role=MessageRole.USER, content="Hi", token_count=1)],
        total_tokens=100,
        summarized_count=5,
        created_at=now - timedelta(hours=1),
        last_activity=now - timedelta(minutes=5),
    )

    mock_store.get_session.return_value = session

    stats = await session_manager.get_session_stats(session_id)

    assert stats is not None
    assert stats.message_count == 1
    assert stats.total_tokens == 100
    assert stats.summarized_messages == 5
    assert stats.age_seconds > 0
    assert stats.last_activity_seconds > 0


@pytest.mark.asyncio
async def test_get_session_stats_not_found(session_manager, mock_store):
    """Test stats for non-existent session."""
    mock_store.get_session.return_value = None

    stats = await session_manager.get_session_stats(uuid4())

    assert stats is None


# ============================================================================
# Message Limit Enforcement Tests
# ============================================================================


@pytest.mark.asyncio
async def test_message_limit_enforcement(session_manager, mock_store, memory_config):
    """Test that old messages are removed when limit exceeded."""
    memory_config.max_messages = 5
    session_manager.config = memory_config

    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content=f"Msg {i}", token_count=10)
            for i in range(5)
        ],
        total_tokens=50,
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    # Add one more message (exceeds limit)
    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message",
    )

    # Check oldest was removed
    updated = mock_store.update_session.call_args[0][0]
    assert len(updated.messages) == 5


@pytest.mark.asyncio
async def test_message_limit_updates_token_count(
    session_manager, mock_store, memory_config,
):
    """Test that token count is updated when messages are removed."""
    memory_config.max_messages = 2
    session_manager.config = memory_config

    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content="First message", token_count=2),
            Message(role=MessageRole.USER, content="Second message", token_count=2),
        ],
        total_tokens=4,
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    # Add new message
    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "Third message",  # 2 words
    )

    updated = mock_store.update_session.call_args[0][0]
    # First message should be removed, its tokens subtracted
    # New total = 4 - 2 (removed) + 2 (added) = 4
    assert updated.total_tokens == 4


# ============================================================================
# Summarization Tests
# ============================================================================


@pytest.mark.asyncio
async def test_should_summarize_when_threshold_reached(
    mock_store, memory_config, mock_tokenizer,
):
    """Test that summarization is triggered when threshold is reached."""
    memory_config.enable_summarization = True
    memory_config.summarize_after_messages = 3

    mock_summarizer = AsyncMock(spec=HistorySummarizer)
    mock_summarizer.summarize.return_value = "Summary of conversation."

    session_manager = SessionManager(
        store=mock_store,
        config=memory_config,
        summarizer=mock_summarizer,
        tokenizer=mock_tokenizer,
    )

    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content=f"Msg {i}", token_count=1)
            for i in range(3)
        ],
        summarized_count=0,
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    # Adding one more should trigger summarization
    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message",
    )

    # Summarizer should have been called
    mock_summarizer.summarize.assert_called()


@pytest.mark.asyncio
async def test_no_summarization_without_summarizer(session_manager, mock_store):
    """Test that summarization is skipped without summarizer."""
    session_manager.config.enable_summarization = True
    session_manager.config.summarize_after_messages = 1
    session_manager.summarizer = None

    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content="Msg", token_count=1),
        ],
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    # Should not raise error even without summarizer
    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message",
    )

    updated = mock_store.update_session.call_args[0][0]
    assert updated.summary is None


@pytest.mark.asyncio
async def test_no_summarization_when_disabled(
    mock_store, memory_config, mock_tokenizer,
):
    """Test that summarization is skipped when disabled."""
    memory_config.enable_summarization = False

    mock_summarizer = AsyncMock(spec=HistorySummarizer)

    session_manager = SessionManager(
        store=mock_store,
        config=memory_config,
        summarizer=mock_summarizer,
        tokenizer=mock_tokenizer,
    )

    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content=f"Msg {i}", token_count=1)
            for i in range(100)
        ],
    )

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message",
    )

    # Summarizer should not have been called
    mock_summarizer.summarize.assert_not_called()


# ============================================================================
# Token Counter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_token_counting_without_tokenizer(mock_store, memory_config):
    """Test that token counting works without tokenizer."""
    session_manager = SessionManager(
        store=mock_store,
        config=memory_config,
        tokenizer=None,
    )

    session_id = uuid4()
    session = ConversationSession(id=session_id)

    mock_store.get_session.return_value = session
    mock_store.update_session = AsyncMock()
    mock_store.extend_ttl = AsyncMock()

    message = await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "Hello world",
    )

    # Token count should be 0 without tokenizer
    assert message.token_count == 0
