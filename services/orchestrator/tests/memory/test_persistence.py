"""Unit tests for PostgresConversationStore."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from memory.models import ConversationSession, Message, MessageRole
from memory.persistence import PostgresConversationStore

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def database_url():
    """Test database URL."""
    return "postgresql://user:pass@localhost:5432/testdb"


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="DELETE 1")
    conn.executemany = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)

    # Mock transaction context manager
    transaction_cm = AsyncMock()
    transaction_cm.__aenter__ = AsyncMock(return_value=None)
    transaction_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=transaction_cm)

    return conn


@pytest.fixture
def mock_pool(mock_connection):
    """Create a mock asyncpg pool."""
    pool = AsyncMock()

    # Mock acquire context manager
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=mock_connection)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquire_cm)

    pool.close = AsyncMock()

    return pool


@pytest.fixture
def postgres_store(database_url, mock_pool):
    """Create PostgresConversationStore with mocked pool."""
    store = PostgresConversationStore(database_url)
    store._pool = mock_pool
    return store


@pytest.fixture
def sample_session():
    """Create a sample conversation session."""
    return ConversationSession(
        id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        messages=[
            Message(
                role=MessageRole.USER,
                content="Hello, how are you?",
                token_count=5,
            ),
            Message(
                role=MessageRole.ASSISTANT,
                content="I'm doing great! How can I help you?",
                sources=["doc-1", "doc-2"],
                token_count=10,
            ),
        ],
        summary="Greeting exchange",
        summarized_count=0,
        total_messages=2,
        total_tokens=15,
        system_prompt="You are a helpful assistant.",
    )


@pytest.fixture
def sample_message():
    """Create a sample message."""
    return Message(
        role=MessageRole.USER,
        content="What is Python?",
        token_count=4,
    )


# ============================================================================
# Connection Tests
# ============================================================================


@pytest.mark.asyncio
async def test_connect(database_url):
    """Test database connection initialization."""
    store = PostgresConversationStore(database_url)

    with patch("memory.persistence.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        mock_pool = AsyncMock()
        mock_create.return_value = mock_pool

        await store.connect()

        mock_create.assert_called_once_with(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        assert store._pool is mock_pool


@pytest.mark.asyncio
async def test_connect_already_connected(postgres_store, mock_pool):
    """Test that connect is idempotent."""
    with patch("memory.persistence.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        await postgres_store.connect()

        # Should not create a new pool if already connected
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_close(postgres_store, mock_pool):
    """Test database connection close."""
    await postgres_store.close()

    mock_pool.close.assert_called_once()
    assert postgres_store._pool is None


@pytest.mark.asyncio
async def test_close_not_connected(database_url):
    """Test close when not connected."""
    store = PostgresConversationStore(database_url)

    # Should not raise
    await store.close()


def test_ensure_connected_raises_when_not_connected(database_url):
    """Test that operations raise when not connected."""
    store = PostgresConversationStore(database_url)

    with pytest.raises(RuntimeError, match="Database not connected"):
        store._ensure_connected()


# ============================================================================
# Save Conversation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_save_conversation(postgres_store, mock_connection, sample_session):
    """Test saving a conversation with messages."""
    await postgres_store.save_conversation(sample_session)

    # Verify conversation upsert was called
    calls = mock_connection.execute.call_args_list
    assert len(calls) >= 2  # At least upsert + delete messages

    # Check the first call (upsert)
    first_call = calls[0]
    assert "INSERT INTO conversations" in first_call[0][0]
    assert "ON CONFLICT (id) DO UPDATE" in first_call[0][0]

    # Verify messages were inserted
    mock_connection.executemany.assert_called_once()
    executemany_call = mock_connection.executemany.call_args
    assert "INSERT INTO messages" in executemany_call[0][0]
    assert len(executemany_call[0][1]) == len(sample_session.messages)


@pytest.mark.asyncio
async def test_save_conversation_without_messages(postgres_store, mock_connection):
    """Test saving a conversation with no messages."""
    session = ConversationSession(id=uuid4())

    await postgres_store.save_conversation(session)

    # Should not call executemany for empty messages
    mock_connection.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_save_conversation_metadata_format(postgres_store, mock_connection, sample_session):
    """Test that metadata is properly serialized."""
    await postgres_store.save_conversation(sample_session)

    # Get the call arguments
    calls = mock_connection.execute.call_args_list
    upsert_call = calls[0]

    # The metadata should be the 6th parameter (index 5)
    metadata_json = upsert_call[0][6]
    metadata = json.loads(metadata_json)

    assert metadata["summary"] == sample_session.summary
    assert metadata["summarized_count"] == sample_session.summarized_count
    assert metadata["total_messages"] == sample_session.total_messages
    assert metadata["total_tokens"] == sample_session.total_tokens
    assert metadata["system_prompt"] == sample_session.system_prompt


@pytest.mark.asyncio
async def test_save_conversation_deletes_existing_messages(
    postgres_store,
    mock_connection,
    sample_session,
):
    """Test that existing messages are deleted before re-insert."""
    await postgres_store.save_conversation(sample_session)

    calls = mock_connection.execute.call_args_list

    # Find the delete call
    delete_calls = [c for c in calls if "DELETE FROM messages" in c[0][0]]
    assert len(delete_calls) == 1


# ============================================================================
# Save Message Tests
# ============================================================================


@pytest.mark.asyncio
async def test_save_message(postgres_store, mock_connection, sample_message):
    """Test saving a single message."""
    session_id = str(uuid4())

    await postgres_store.save_message(session_id, sample_message)

    calls = mock_connection.execute.call_args_list

    # Should update conversation timestamp
    update_calls = [c for c in calls if "UPDATE conversations" in c[0][0]]
    assert len(update_calls) == 1

    # Should insert message
    insert_calls = [c for c in calls if "INSERT INTO messages" in c[0][0]]
    assert len(insert_calls) == 1


@pytest.mark.asyncio
async def test_save_message_with_citations(postgres_store, mock_connection):
    """Test saving a message with citations."""
    session_id = str(uuid4())
    message = Message(
        role=MessageRole.ASSISTANT,
        content="Python is a programming language.",
        sources=["doc-1", "doc-2", "doc-3"],
        token_count=6,
    )

    await postgres_store.save_message(session_id, message)

    # Verify citations are JSON serialized
    insert_call = [
        c for c in mock_connection.execute.call_args_list if "INSERT INTO messages" in c[0][0]
    ][0]

    # Citations should be the 5th parameter (index 4)
    citations_param = insert_call[0][5]
    assert citations_param is not None
    assert json.loads(citations_param) == ["doc-1", "doc-2", "doc-3"]


@pytest.mark.asyncio
async def test_save_message_without_citations(postgres_store, mock_connection, sample_message):
    """Test saving a message without citations."""
    session_id = str(uuid4())
    sample_message.sources = None

    await postgres_store.save_message(session_id, sample_message)

    insert_call = [
        c for c in mock_connection.execute.call_args_list if "INSERT INTO messages" in c[0][0]
    ][0]

    # Citations should be None
    citations_param = insert_call[0][5]
    assert citations_param is None


@pytest.mark.asyncio
async def test_save_message_uuid_conversion(postgres_store, mock_connection, sample_message):
    """Test that string session_id is converted to UUID."""
    session_id = uuid4()

    await postgres_store.save_message(str(session_id), sample_message)

    # The update call should have UUID, not string
    update_call = [
        c for c in mock_connection.execute.call_args_list if "UPDATE conversations" in c[0][0]
    ][0]

    # Second parameter should be UUID
    assert update_call[0][2] == session_id


# ============================================================================
# Load Conversation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_load_conversation(postgres_store, mock_connection):
    """Test loading a conversation with messages."""
    session_id = uuid4()
    user_id = uuid4()
    tenant_id = uuid4()
    now = datetime.now(tz=UTC)

    # Mock conversation row
    conv_row = {
        "id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "metadata": json.dumps(
            {
                "summary": "Test summary",
                "summarized_count": 5,
                "total_messages": 10,
                "total_tokens": 100,
                "system_prompt": "Be helpful",
            },
        ),
    }
    mock_connection.fetchrow.return_value = conv_row

    # Mock message rows
    msg_rows = [
        {
            "id": uuid4(),
            "role": "user",
            "content": "Hello",
            "citations": None,
            "token_count": 1,
            "created_at": now,
        },
        {
            "id": uuid4(),
            "role": "assistant",
            "content": "Hi there!",
            "citations": json.dumps(["doc-1"]),
            "token_count": 2,
            "created_at": now,
        },
    ]
    mock_connection.fetch.return_value = msg_rows

    result = await postgres_store.load_conversation(str(session_id))

    assert result is not None
    assert result.id == session_id
    assert result.user_id == user_id
    assert result.tenant_id == tenant_id
    assert result.summary == "Test summary"
    assert result.summarized_count == 5
    assert result.total_messages == 10
    assert result.total_tokens == 100
    assert result.system_prompt == "Be helpful"

    # Verify messages
    assert len(result.messages) == 2
    assert result.messages[0].role == MessageRole.USER
    assert result.messages[0].content == "Hello"
    assert result.messages[1].sources == ["doc-1"]


@pytest.mark.asyncio
async def test_load_conversation_not_found(postgres_store, mock_connection):
    """Test loading a non-existent conversation."""
    mock_connection.fetchrow.return_value = None

    result = await postgres_store.load_conversation(str(uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_load_conversation_with_null_metadata(postgres_store, mock_connection):
    """Test loading conversation with null metadata."""
    session_id = uuid4()
    now = datetime.now(tz=UTC)

    conv_row = {
        "id": session_id,
        "tenant_id": None,
        "user_id": None,
        "created_at": now,
        "updated_at": now,
        "metadata": None,
    }
    mock_connection.fetchrow.return_value = conv_row
    mock_connection.fetch.return_value = []

    result = await postgres_store.load_conversation(str(session_id))

    assert result is not None
    assert result.summary is None
    assert result.summarized_count == 0
    assert result.total_messages == 0
    assert result.system_prompt is None


@pytest.mark.asyncio
async def test_load_conversation_messages_ordered(postgres_store, mock_connection):
    """Test that messages are loaded in chronological order."""
    session_id = uuid4()
    now = datetime.now(tz=UTC)

    conv_row = {
        "id": session_id,
        "tenant_id": None,
        "user_id": None,
        "created_at": now,
        "updated_at": now,
        "metadata": json.dumps({}),
    }
    mock_connection.fetchrow.return_value = conv_row
    mock_connection.fetch.return_value = []

    await postgres_store.load_conversation(str(session_id))

    # Verify ORDER BY clause is used
    fetch_call = mock_connection.fetch.call_args
    assert "ORDER BY created_at ASC" in fetch_call[0][0]


# ============================================================================
# Delete Conversation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_delete_conversation(postgres_store, mock_connection):
    """Test deleting a conversation."""
    session_id = uuid4()
    mock_connection.execute.return_value = "DELETE 1"

    result = await postgres_store.delete_conversation(str(session_id))

    assert result is True

    calls = mock_connection.execute.call_args_list

    # Should delete messages first
    delete_msg_calls = [c for c in calls if "DELETE FROM messages" in c[0][0]]
    assert len(delete_msg_calls) == 1

    # Should delete conversation
    delete_conv_calls = [c for c in calls if "DELETE FROM conversations" in c[0][0]]
    assert len(delete_conv_calls) == 1


@pytest.mark.asyncio
async def test_delete_conversation_not_found(postgres_store, mock_connection):
    """Test deleting a non-existent conversation."""
    mock_connection.execute.return_value = "DELETE 0"

    result = await postgres_store.delete_conversation(str(uuid4()))

    assert result is False


@pytest.mark.asyncio
async def test_delete_conversation_cascade(postgres_store, mock_connection):
    """Test that messages are deleted before conversation."""
    session_id = uuid4()
    mock_connection.execute.return_value = "DELETE 1"

    await postgres_store.delete_conversation(str(session_id))

    calls = mock_connection.execute.call_args_list

    # Find indices
    msg_delete_idx = None
    conv_delete_idx = None
    for i, call in enumerate(calls):
        if "DELETE FROM messages" in call[0][0]:
            msg_delete_idx = i
        if "DELETE FROM conversations" in call[0][0]:
            conv_delete_idx = i

    # Messages should be deleted before conversation
    assert msg_delete_idx is not None
    assert conv_delete_idx is not None
    assert msg_delete_idx < conv_delete_idx


# ============================================================================
# List Conversations Tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_conversations(postgres_store, mock_connection):
    """Test listing conversations."""
    now = datetime.now(tz=UTC)

    rows = [
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "user_id": uuid4(),
            "created_at": now,
            "updated_at": now,
            "metadata": json.dumps({"total_messages": 5}),
        },
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "user_id": uuid4(),
            "created_at": now,
            "updated_at": now,
            "metadata": json.dumps({"total_messages": 10}),
        },
    ]
    mock_connection.fetch.return_value = rows

    result = await postgres_store.list_conversations()

    assert len(result) == 2
    assert result[0].total_messages == 5
    assert result[1].total_messages == 10

    # Messages should not be loaded
    assert len(result[0].messages) == 0
    assert len(result[1].messages) == 0


@pytest.mark.asyncio
async def test_list_conversations_with_tenant_filter(postgres_store, mock_connection):
    """Test listing conversations filtered by tenant."""
    tenant_id = uuid4()
    mock_connection.fetch.return_value = []

    await postgres_store.list_conversations(tenant_id=tenant_id)

    fetch_call = mock_connection.fetch.call_args
    assert "tenant_id = $1" in fetch_call[0][0]
    assert tenant_id in fetch_call[0]


@pytest.mark.asyncio
async def test_list_conversations_with_user_filter(postgres_store, mock_connection):
    """Test listing conversations filtered by user."""
    user_id = uuid4()
    mock_connection.fetch.return_value = []

    await postgres_store.list_conversations(user_id=user_id)

    fetch_call = mock_connection.fetch.call_args
    assert "user_id = $1" in fetch_call[0][0]
    assert user_id in fetch_call[0]


@pytest.mark.asyncio
async def test_list_conversations_with_both_filters(postgres_store, mock_connection):
    """Test listing conversations filtered by both tenant and user."""
    tenant_id = uuid4()
    user_id = uuid4()
    mock_connection.fetch.return_value = []

    await postgres_store.list_conversations(tenant_id=tenant_id, user_id=user_id)

    fetch_call = mock_connection.fetch.call_args
    assert "tenant_id = $1" in fetch_call[0][0]
    assert "user_id = $2" in fetch_call[0][0]


@pytest.mark.asyncio
async def test_list_conversations_pagination(postgres_store, mock_connection):
    """Test listing conversations with pagination."""
    mock_connection.fetch.return_value = []

    await postgres_store.list_conversations(limit=10, offset=20)

    fetch_call = mock_connection.fetch.call_args
    assert "LIMIT" in fetch_call[0][0]
    assert "OFFSET" in fetch_call[0][0]
    # Limit and offset should be in params
    assert 10 in fetch_call[0]
    assert 20 in fetch_call[0]


@pytest.mark.asyncio
async def test_list_conversations_ordered_by_updated_at(postgres_store, mock_connection):
    """Test that conversations are ordered by updated_at descending."""
    mock_connection.fetch.return_value = []

    await postgres_store.list_conversations()

    fetch_call = mock_connection.fetch.call_args
    assert "ORDER BY updated_at DESC" in fetch_call[0][0]


# ============================================================================
# Integration-style Tests (with full flow)
# ============================================================================


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(postgres_store, mock_connection, sample_session):
    """Test save and load cycle preserves data."""

    # Setup mock for load
    def mock_fetchrow_impl(*args):
        return {
            "id": sample_session.id,
            "tenant_id": sample_session.tenant_id,
            "user_id": sample_session.user_id,
            "created_at": sample_session.created_at,
            "updated_at": sample_session.updated_at,
            "metadata": json.dumps(
                {
                    "summary": sample_session.summary,
                    "summarized_count": sample_session.summarized_count,
                    "total_messages": sample_session.total_messages,
                    "total_tokens": sample_session.total_tokens,
                    "system_prompt": sample_session.system_prompt,
                },
            ),
        }

    def mock_fetch_impl(*args):
        return [
            {
                "id": msg.id,
                "role": msg.role.value,
                "content": msg.content,
                "citations": json.dumps(msg.sources) if msg.sources else None,
                "token_count": msg.token_count,
                "created_at": msg.timestamp,
            }
            for msg in sample_session.messages
        ]

    mock_connection.fetchrow.side_effect = mock_fetchrow_impl
    mock_connection.fetch.side_effect = mock_fetch_impl

    # Save and load
    await postgres_store.save_conversation(sample_session)
    loaded = await postgres_store.load_conversation(str(sample_session.id))

    # Verify key fields
    assert loaded is not None
    assert loaded.id == sample_session.id
    assert loaded.user_id == sample_session.user_id
    assert loaded.tenant_id == sample_session.tenant_id
    assert loaded.summary == sample_session.summary
    assert loaded.system_prompt == sample_session.system_prompt
    assert len(loaded.messages) == len(sample_session.messages)


@pytest.mark.asyncio
async def test_error_handling_not_connected(database_url):
    """Test that operations fail gracefully when not connected."""
    store = PostgresConversationStore(database_url)

    with pytest.raises(RuntimeError, match="Database not connected"):
        await store.save_conversation(ConversationSession())

    with pytest.raises(RuntimeError, match="Database not connected"):
        await store.save_message(str(uuid4()), Message(role=MessageRole.USER, content="test"))

    with pytest.raises(RuntimeError, match="Database not connected"):
        await store.load_conversation(str(uuid4()))

    with pytest.raises(RuntimeError, match="Database not connected"):
        await store.delete_conversation(str(uuid4()))

    with pytest.raises(RuntimeError, match="Database not connected"):
        await store.list_conversations()
