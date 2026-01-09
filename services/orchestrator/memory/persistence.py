"""PostgreSQL-backed conversation persistence for durable storage."""

import json
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg

from .models import ConversationSession, Message, MessageRole

logger = logging.getLogger(__name__)


class PostgresConversationStore:
    """
    PostgreSQL-backed conversation persistence.

    Provides durable storage for conversation sessions and messages.
    Designed to work alongside RedisSessionStore in a write-through pattern:
    - Redis: Fast access cache for active sessions
    - Postgres: Durable storage for persistence and recovery

    Database Tables (created by migration):
    - conversations: id, tenant_id, user_id, created_at, updated_at, metadata (JSONB)
    - messages: id, conversation_id, role, content, citations (JSONB), token_count, created_at
    """

    def __init__(self, database_url: str):
        """Initialize the Postgres conversation store.

        Args:
            database_url: PostgreSQL connection URL (asyncpg format).
                         Example: postgresql://user:pass@localhost:5432/dbname
        """
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Initialize database connection pool."""
        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("PostgresConversationStore connected to database")

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgresConversationStore disconnected from database")

    def _ensure_connected(self) -> None:
        """Ensure database pool is connected.

        Raises:
            RuntimeError: If pool is not connected.
        """
        if self._pool is None:
            raise RuntimeError(
                "Database not connected. Call connect() first."
            )

    async def save_conversation(self, session: ConversationSession) -> None:
        """Persist conversation to Postgres.

        Saves the conversation metadata and all messages. Uses UPSERT
        to handle both new conversations and updates to existing ones.

        Args:
            session: The conversation session to persist.
        """
        self._ensure_connected()

        # Prepare metadata JSONB
        metadata = {
            "summary": session.summary,
            "summarized_count": session.summarized_count,
            "total_messages": session.total_messages,
            "total_tokens": session.total_tokens,
            "system_prompt": session.system_prompt,
        }

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Upsert conversation
                await conn.execute(
                    """
                    INSERT INTO conversations (
                        id, tenant_id, user_id, created_at, updated_at, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO UPDATE SET
                        updated_at = EXCLUDED.updated_at,
                        metadata = EXCLUDED.metadata
                    """,
                    session.id,
                    session.tenant_id,
                    session.user_id,
                    session.created_at,
                    session.updated_at,
                    json.dumps(metadata),
                )

                # Delete existing messages and re-insert all
                # This ensures consistency with the in-memory state
                await conn.execute(
                    "DELETE FROM messages WHERE conversation_id = $1",
                    session.id,
                )

                # Insert all messages
                if session.messages:
                    message_records = [
                        (
                            msg.id,
                            session.id,
                            msg.role.value,
                            msg.content,
                            json.dumps(msg.sources) if msg.sources else None,
                            msg.token_count,
                            msg.timestamp,
                        )
                        for msg in session.messages
                    ]

                    await conn.executemany(
                        """
                        INSERT INTO messages (
                            id, conversation_id, role, content, citations,
                            token_count, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        message_records,
                    )

        logger.debug(
            "Saved conversation %s with %d messages",
            session.id,
            len(session.messages),
        )

    async def save_message(self, session_id: str, message: Message) -> None:
        """Persist single message.

        Efficiently saves a single message without re-saving the entire
        conversation. Use this for incremental updates.

        Args:
            session_id: The conversation session ID.
            message: The message to persist.
        """
        self._ensure_connected()

        # Convert session_id to UUID if string
        if isinstance(session_id, str):
            session_id = UUID(session_id)

        async with self._pool.acquire() as conn:
            # First, update the conversation's updated_at timestamp
            await conn.execute(
                """
                UPDATE conversations SET updated_at = $1 WHERE id = $2
                """,
                datetime.utcnow(),
                session_id,
            )

            # Insert the message
            await conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, citations,
                    token_count, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    citations = EXCLUDED.citations,
                    token_count = EXCLUDED.token_count
                """,
                message.id,
                session_id,
                message.role.value,
                message.content,
                json.dumps(message.sources) if message.sources else None,
                message.token_count,
                message.timestamp,
            )

        logger.debug(
            "Saved message %s to conversation %s",
            message.id,
            session_id,
        )

    async def load_conversation(
        self, session_id: str
    ) -> Optional[ConversationSession]:
        """Load conversation from Postgres.

        Loads the conversation metadata and all associated messages,
        reconstructing a full ConversationSession object.

        Args:
            session_id: The conversation session ID to load.

        Returns:
            ConversationSession if found, None otherwise.
        """
        self._ensure_connected()

        # Convert session_id to UUID if string
        if isinstance(session_id, str):
            session_id = UUID(session_id)

        async with self._pool.acquire() as conn:
            # Load conversation
            conv_row = await conn.fetchrow(
                """
                SELECT id, tenant_id, user_id, created_at, updated_at, metadata
                FROM conversations
                WHERE id = $1
                """,
                session_id,
            )

            if not conv_row:
                return None

            # Load messages ordered by creation time
            msg_rows = await conn.fetch(
                """
                SELECT id, role, content, citations, token_count, created_at
                FROM messages
                WHERE conversation_id = $1
                ORDER BY created_at ASC
                """,
                session_id,
            )

        # Parse metadata
        metadata = json.loads(conv_row["metadata"]) if conv_row["metadata"] else {}

        # Reconstruct messages
        messages = []
        for row in msg_rows:
            citations = json.loads(row["citations"]) if row["citations"] else None
            messages.append(
                Message(
                    id=row["id"],
                    role=MessageRole(row["role"]),
                    content=row["content"],
                    sources=citations,
                    token_count=row["token_count"],
                    timestamp=row["created_at"],
                )
            )

        # Reconstruct session
        session = ConversationSession(
            id=conv_row["id"],
            tenant_id=conv_row["tenant_id"],
            user_id=conv_row["user_id"],
            messages=messages,
            summary=metadata.get("summary"),
            summarized_count=metadata.get("summarized_count", 0),
            created_at=conv_row["created_at"],
            updated_at=conv_row["updated_at"],
            last_activity=conv_row["updated_at"],
            total_messages=metadata.get("total_messages", len(messages)),
            total_tokens=metadata.get("total_tokens", 0),
            system_prompt=metadata.get("system_prompt"),
        )

        logger.debug(
            "Loaded conversation %s with %d messages",
            session_id,
            len(messages),
        )

        return session

    async def delete_conversation(self, session_id: str) -> bool:
        """Delete conversation from Postgres.

        Deletes the conversation and all associated messages.

        Args:
            session_id: The conversation session ID to delete.

        Returns:
            True if conversation was deleted, False if not found.
        """
        self._ensure_connected()

        # Convert session_id to UUID if string
        if isinstance(session_id, str):
            session_id = UUID(session_id)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Delete messages first (foreign key constraint)
                await conn.execute(
                    "DELETE FROM messages WHERE conversation_id = $1",
                    session_id,
                )

                # Delete conversation
                result = await conn.execute(
                    "DELETE FROM conversations WHERE id = $1",
                    session_id,
                )

        # Check if any row was deleted
        deleted = result.split()[-1] != "0"

        if deleted:
            logger.debug("Deleted conversation %s", session_id)
        else:
            logger.debug("Conversation %s not found for deletion", session_id)

        return deleted

    async def list_conversations(
        self,
        tenant_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationSession]:
        """List conversations with optional filtering.

        Args:
            tenant_id: Optional tenant ID filter.
            user_id: Optional user ID filter.
            limit: Maximum number of conversations to return.
            offset: Number of conversations to skip.

        Returns:
            List of ConversationSession objects (without messages loaded).
        """
        self._ensure_connected()

        # Build query with filters
        query = """
            SELECT id, tenant_id, user_id, created_at, updated_at, metadata
            FROM conversations
            WHERE 1=1
        """
        params = []
        param_idx = 1

        if tenant_id:
            query += f" AND tenant_id = ${param_idx}"
            params.append(tenant_id)
            param_idx += 1

        if user_id:
            query += f" AND user_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1

        query += f" ORDER BY updated_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        sessions = []
        for row in rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            sessions.append(
                ConversationSession(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    messages=[],  # Don't load messages for listing
                    summary=metadata.get("summary"),
                    summarized_count=metadata.get("summarized_count", 0),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    last_activity=row["updated_at"],
                    total_messages=metadata.get("total_messages", 0),
                    total_tokens=metadata.get("total_tokens", 0),
                    system_prompt=metadata.get("system_prompt"),
                )
            )

        return sessions
