"""Unit tests for memory models."""

from datetime import UTC, datetime
from uuid import uuid4

from memory.models import (
    ConversationSession,
    MemoryConfig,
    Message,
    MessageRole,
    SessionStats,
)

# ============================================================================
# MessageRole Tests
# ============================================================================


def test_message_role_values():
    """Test MessageRole enum values."""
    assert MessageRole.SYSTEM.value == "system"
    assert MessageRole.USER.value == "user"
    assert MessageRole.ASSISTANT.value == "assistant"
    assert MessageRole.FUNCTION.value == "function"


def test_message_role_is_string():
    """Test that MessageRole is a string enum."""
    assert isinstance(MessageRole.USER, str)
    assert MessageRole.USER == "user"


# ============================================================================
# Message Tests
# ============================================================================


def test_message_creation():
    """Test basic message creation."""
    msg = Message(role=MessageRole.USER, content="Hello")

    assert msg.role == MessageRole.USER
    assert msg.content == "Hello"
    assert msg.id is not None
    assert isinstance(msg.timestamp, datetime)


def test_message_with_all_fields():
    """Test message with all optional fields."""
    msg = Message(
        role=MessageRole.FUNCTION,
        content="Result",
        name="search",
        token_count=10,
        sources=["doc1.pdf", "doc2.pdf"],
    )

    assert msg.name == "search"
    assert msg.token_count == 10
    assert msg.sources == ["doc1.pdf", "doc2.pdf"]


def test_message_to_dict():
    """Test message conversion to dict."""
    msg = Message(role=MessageRole.USER, content="Hello")

    d = msg.to_dict()

    assert d == {"role": "user", "content": "Hello"}


def test_message_to_dict_with_name():
    """Test function message conversion includes name."""
    msg = Message(role=MessageRole.FUNCTION, content="result", name="search")

    d = msg.to_dict()

    assert d == {"role": "function", "content": "result", "name": "search"}


def test_message_to_dict_excludes_none_name():
    """Test that None name is not included in dict."""
    msg = Message(role=MessageRole.USER, content="Hello", name=None)

    d = msg.to_dict()

    assert "name" not in d


def test_message_default_id_is_unique():
    """Test that default IDs are unique."""
    msg1 = Message(role=MessageRole.USER, content="Hello")
    msg2 = Message(role=MessageRole.USER, content="Hello")

    assert msg1.id != msg2.id


# ============================================================================
# ConversationSession Tests
# ============================================================================


def test_session_creation():
    """Test basic session creation."""
    session = ConversationSession()

    assert session.id is not None
    assert session.user_id is None
    assert session.tenant_id is None
    assert session.messages == []
    assert session.summary is None
    assert session.total_messages == 0
    assert session.total_tokens == 0


def test_session_with_user_and_tenant():
    """Test session with user and tenant IDs."""
    user_id = uuid4()
    tenant_id = uuid4()

    session = ConversationSession(
        user_id=user_id,
        tenant_id=tenant_id,
    )

    assert session.user_id == user_id
    assert session.tenant_id == tenant_id


def test_session_with_messages():
    """Test session with messages."""
    messages = [
        Message(role=MessageRole.USER, content="Hi"),
        Message(role=MessageRole.ASSISTANT, content="Hello!"),
    ]

    session = ConversationSession(messages=messages)

    assert len(session.messages) == 2
    assert session.messages[0].content == "Hi"


def test_session_with_system_prompt():
    """Test session with system prompt."""
    session = ConversationSession(
        system_prompt="You are a helpful assistant.",
    )

    assert session.system_prompt == "You are a helpful assistant."


def test_session_with_summary():
    """Test session with summary."""
    session = ConversationSession(
        summary="Discussion about Python.",
        summarized_count=5,
    )

    assert session.summary == "Discussion about Python."
    assert session.summarized_count == 5


def test_session_timestamps():
    """Test session has correct timestamps."""
    before = datetime.now(tz=UTC)
    session = ConversationSession()
    after = datetime.now(tz=UTC)

    assert before <= session.created_at <= after
    assert before <= session.updated_at <= after
    assert before <= session.last_activity <= after


def test_session_serialization():
    """Test session can be serialized to JSON."""
    session = ConversationSession(
        user_id=uuid4(),
        tenant_id=uuid4(),
        messages=[Message(role=MessageRole.USER, content="Hi")],
        system_prompt="You are helpful.",
        total_messages=1,
        total_tokens=1,
    )

    json_str = session.model_dump_json()

    # Should be valid JSON that can be parsed back
    from memory.models import ConversationSession as CS

    restored = CS.model_validate_json(json_str)

    assert restored.id == session.id
    assert restored.user_id == session.user_id
    assert len(restored.messages) == 1


# ============================================================================
# MemoryConfig Tests
# ============================================================================


def test_memory_config_defaults():
    """Test MemoryConfig default values."""
    config = MemoryConfig()

    assert config.session_ttl == 3600
    assert config.max_sessions_per_user == 10
    assert config.max_messages == 50
    assert config.max_tokens == 4096
    assert config.enable_summarization is True
    assert config.summarize_after_messages == 20
    assert config.redis_prefix == "session:"
    assert config.redis_url == "redis://localhost:6379/0"


def test_memory_config_custom_values():
    """Test MemoryConfig with custom values."""
    config = MemoryConfig(
        session_ttl=7200,
        max_messages=100,
        max_tokens=8192,
        enable_summarization=False,
        redis_url="redis://custom:6379/1",
    )

    assert config.session_ttl == 7200
    assert config.max_messages == 100
    assert config.max_tokens == 8192
    assert config.enable_summarization is False
    assert config.redis_url == "redis://custom:6379/1"


def test_memory_config_summarization_settings():
    """Test MemoryConfig summarization settings."""
    config = MemoryConfig(
        summarize_after_messages=10,
        summary_model="custom-model",
        summary_max_tokens=1000,
    )

    assert config.summarize_after_messages == 10
    assert config.summary_model == "custom-model"
    assert config.summary_max_tokens == 1000


def test_memory_config_cleanup_settings():
    """Test MemoryConfig cleanup settings."""
    config = MemoryConfig(
        cleanup_interval=600,
        inactive_threshold=3600,
    )

    assert config.cleanup_interval == 600
    assert config.inactive_threshold == 3600


# ============================================================================
# SessionStats Tests
# ============================================================================


def test_session_stats_creation():
    """Test SessionStats creation."""
    stats = SessionStats(
        message_count=10,
        total_tokens=500,
        summarized_messages=5,
        age_seconds=3600.0,
        last_activity_seconds=60.0,
    )

    assert stats.message_count == 10
    assert stats.total_tokens == 500
    assert stats.summarized_messages == 5
    assert stats.age_seconds == 3600.0
    assert stats.last_activity_seconds == 60.0


def test_session_stats_zero_values():
    """Test SessionStats with zero values."""
    stats = SessionStats(
        message_count=0,
        total_tokens=0,
        summarized_messages=0,
        age_seconds=0.0,
        last_activity_seconds=0.0,
    )

    assert stats.message_count == 0
    assert stats.total_tokens == 0


def test_session_stats_serialization():
    """Test SessionStats can be serialized."""
    stats = SessionStats(
        message_count=10,
        total_tokens=500,
        summarized_messages=5,
        age_seconds=3600.5,
        last_activity_seconds=60.25,
    )

    json_str = stats.model_dump_json()

    # Should be valid JSON
    restored = SessionStats.model_validate_json(json_str)

    assert restored.message_count == 10
    assert restored.age_seconds == 3600.5
