"""Unit tests for RedisSessionStore."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from memory.models import ConversationSession, MemoryConfig
from memory.store import RedisSessionStore

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
        redis_prefix="test:session:",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
def redis_store(memory_config, mock_redis):
    """Create RedisSessionStore with mocked Redis."""
    store = RedisSessionStore(memory_config)
    store._redis = mock_redis
    return store


# ============================================================================
# Session Key Tests
# ============================================================================


def test_session_key(redis_store):
    """Test session key generation."""
    session_id = uuid4()
    key = redis_store._session_key(session_id)

    assert key == f"test:session:{session_id}"


def test_user_sessions_key(redis_store):
    """Test user sessions key generation."""
    user_id = uuid4()
    key = redis_store._user_sessions_key(user_id)

    assert key == f"test:session:user:{user_id}:sessions"


# ============================================================================
# Create Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_session(redis_store, mock_redis):
    """Test session creation."""
    user_id = uuid4()
    tenant_id = uuid4()
    system_prompt = "You are a helpful assistant."

    session = await redis_store.create_session(
        user_id=user_id,
        tenant_id=tenant_id,
        system_prompt=system_prompt,
    )

    assert session.user_id == user_id
    assert session.tenant_id == tenant_id
    assert session.system_prompt == system_prompt
    assert session.id is not None
    assert len(session.messages) == 0

    # Verify Redis set was called
    mock_redis.set.assert_called()


@pytest.mark.asyncio
async def test_create_session_without_user(redis_store, mock_redis):
    """Test session creation without user."""
    session = await redis_store.create_session()

    assert session.user_id is None
    assert session.tenant_id is None
    assert session.id is not None

    # Verify sadd was NOT called (no user to track)
    mock_redis.sadd.assert_not_called()


@pytest.mark.asyncio
async def test_create_session_tracks_user_sessions(redis_store, mock_redis):
    """Test that session is added to user's session set."""
    user_id = uuid4()

    await redis_store.create_session(user_id=user_id)

    # Verify session was added to user's set
    mock_redis.sadd.assert_called()
    call_args = mock_redis.sadd.call_args
    assert str(user_id) in call_args[0][0]


# ============================================================================
# Get Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_session(redis_store, mock_redis):
    """Test session retrieval."""
    session_id = uuid4()
    session_data = ConversationSession(id=session_id)

    mock_redis.get.return_value = session_data.model_dump_json()

    result = await redis_store.get_session(session_id)

    assert result is not None
    assert result.id == session_id
    mock_redis.get.assert_called_with(redis_store._session_key(session_id))


@pytest.mark.asyncio
async def test_get_session_not_found(redis_store, mock_redis):
    """Test session not found."""
    mock_redis.get.return_value = None

    result = await redis_store.get_session(uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_get_session_invalid_json(redis_store, mock_redis):
    """Test handling of invalid JSON in Redis."""
    mock_redis.get.return_value = "invalid json"

    result = await redis_store.get_session(uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_get_session_with_messages(redis_store, mock_redis):
    """Test retrieving session with messages."""
    from memory.models import Message, MessageRole

    session_id = uuid4()
    session_data = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content="Hello"),
            Message(role=MessageRole.ASSISTANT, content="Hi there!"),
        ],
    )

    mock_redis.get.return_value = session_data.model_dump_json()

    result = await redis_store.get_session(session_id)

    assert result is not None
    assert len(result.messages) == 2
    assert result.messages[0].role == MessageRole.USER


# ============================================================================
# Update Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_update_session(redis_store, mock_redis):
    """Test session update."""
    session = ConversationSession()
    original_updated_at = session.updated_at

    await redis_store.update_session(session)

    # Verify updated_at was changed
    assert session.updated_at >= original_updated_at

    # Verify Redis set was called
    mock_redis.set.assert_called()


@pytest.mark.asyncio
async def test_update_session_with_ttl(redis_store, mock_redis):
    """Test that session update includes TTL."""
    session = ConversationSession()

    await redis_store.update_session(session)

    # Check that set was called with expiration
    call_kwargs = mock_redis.set.call_args[1]
    assert "ex" in call_kwargs
    assert call_kwargs["ex"] == redis_store.config.session_ttl


# ============================================================================
# Delete Session Tests
# ============================================================================


@pytest.mark.asyncio
async def test_delete_session(redis_store, mock_redis):
    """Test session deletion."""
    session_id = uuid4()
    user_id = uuid4()
    session = ConversationSession(id=session_id, user_id=user_id)

    mock_redis.get.return_value = session.model_dump_json()
    mock_redis.delete.return_value = 1

    result = await redis_store.delete_session(session_id)

    assert result is True
    mock_redis.delete.assert_called()


@pytest.mark.asyncio
async def test_delete_session_not_found(redis_store, mock_redis):
    """Test deleting non-existent session."""
    mock_redis.get.return_value = None

    result = await redis_store.delete_session(uuid4())

    assert result is False
    mock_redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_session_removes_from_user_sessions(redis_store, mock_redis):
    """Test that deleted session is removed from user's session set."""
    session_id = uuid4()
    user_id = uuid4()
    session = ConversationSession(id=session_id, user_id=user_id)

    mock_redis.get.return_value = session.model_dump_json()
    mock_redis.delete.return_value = 1

    await redis_store.delete_session(session_id)

    # Verify srem was called to remove from user's set
    mock_redis.srem.assert_called()


# ============================================================================
# TTL Extension Tests
# ============================================================================


@pytest.mark.asyncio
async def test_extend_ttl(redis_store, mock_redis):
    """Test TTL extension."""
    session_id = uuid4()

    await redis_store.extend_ttl(session_id)

    mock_redis.expire.assert_called_with(
        redis_store._session_key(session_id),
        redis_store.config.session_ttl,
    )


# ============================================================================
# Get User Sessions Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_user_sessions(redis_store, mock_redis):
    """Test retrieving user's sessions."""
    user_id = uuid4()
    session1 = ConversationSession(
        user_id=user_id,
        updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    session2 = ConversationSession(
        user_id=user_id,
        updated_at=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
    )

    mock_redis.smembers.return_value = {str(session1.id), str(session2.id)}

    # Return different sessions based on key
    async def mock_get(key):
        if str(session1.id) in key:
            return session1.model_dump_json()
        if str(session2.id) in key:
            return session2.model_dump_json()
        return None

    mock_redis.get.side_effect = mock_get

    sessions = await redis_store.get_user_sessions(user_id)

    assert len(sessions) == 2
    # Sessions should be sorted by updated_at (newest first)
    assert sessions[0].updated_at > sessions[1].updated_at


@pytest.mark.asyncio
async def test_get_user_sessions_empty(redis_store, mock_redis):
    """Test retrieving sessions for user with no sessions."""
    mock_redis.smembers.return_value = set()

    sessions = await redis_store.get_user_sessions(uuid4())

    assert sessions == []


@pytest.mark.asyncio
async def test_get_user_sessions_handles_expired(redis_store, mock_redis):
    """Test that expired sessions are handled gracefully."""
    user_id = uuid4()
    valid_session = ConversationSession(user_id=user_id)

    # One valid session, one expired (returns None)
    mock_redis.smembers.return_value = {str(valid_session.id), str(uuid4())}

    async def mock_get(key):
        if str(valid_session.id) in key:
            return valid_session.model_dump_json()
        return None

    mock_redis.get.side_effect = mock_get

    sessions = await redis_store.get_user_sessions(user_id)

    # Should only return the valid session
    assert len(sessions) == 1


# ============================================================================
# Session Limit Enforcement Tests
# ============================================================================


@pytest.mark.asyncio
async def test_enforce_session_limit(redis_store, mock_redis):
    """Test that max sessions per user is enforced."""
    redis_store.config.max_sessions_per_user = 2

    user_id = uuid4()

    # Create 3 sessions (one over limit)
    sessions = [
        ConversationSession(
            user_id=user_id,
            updated_at=datetime(2024, 1, i + 1, 12, 0, 0, tzinfo=UTC),
        )
        for i in range(3)
    ]

    mock_redis.smembers.return_value = {str(s.id) for s in sessions}

    # Return sessions based on ID
    async def mock_get(key):
        for s in sessions:
            if str(s.id) in key:
                return s.model_dump_json()
        return None

    mock_redis.get.side_effect = mock_get

    await redis_store._enforce_session_limit(user_id)

    # Should have called delete for the oldest session
    assert mock_redis.delete.call_count >= 1


# ============================================================================
# Connection Tests
# ============================================================================


@pytest.mark.asyncio
async def test_connect():
    """Test Redis connection."""
    config = MemoryConfig(redis_url="redis://localhost:6379/1")
    store = RedisSessionStore(config)

    # We can't actually connect in unit tests, but we can verify the method exists
    # In integration tests, this would actually connect
    assert hasattr(store, "connect")


@pytest.mark.asyncio
async def test_close(redis_store, mock_redis):
    """Test Redis connection close."""
    await redis_store.close()

    mock_redis.close.assert_called()


# ============================================================================
# Cleanup Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_expired(redis_store):
    """Test cleanup of expired sessions."""
    # Redis handles TTL-based expiration automatically
    result = await redis_store.cleanup_expired()

    assert result == 0
