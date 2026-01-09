"""Redis-backed session storage for conversation memory."""

import json
from typing import Optional
from uuid import UUID

import redis.asyncio as redis

from .models import ConversationSession, MemoryConfig


class RedisSessionStore:
    """
    Redis-backed session storage.

    Features:
    - Async Redis operations
    - Session serialization/deserialization
    - TTL-based expiration
    - Atomic operations for concurrency
    """

    def __init__(self, config: MemoryConfig):
        """Initialize the Redis session store.

        Args:
            config: Memory configuration with Redis settings.
        """
        self.config = config
        self._redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = await redis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    def _session_key(self, session_id: UUID) -> str:
        """Get Redis key for session.

        Args:
            session_id: The session identifier.

        Returns:
            Redis key string for the session.
        """
        return f"{self.config.redis_prefix}{session_id}"

    def _user_sessions_key(self, user_id: UUID) -> str:
        """Get Redis key for user's session list.

        Args:
            user_id: The user identifier.

        Returns:
            Redis key string for the user's session set.
        """
        return f"{self.config.redis_prefix}user:{user_id}:sessions"

    async def create_session(
        self,
        user_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        system_prompt: Optional[str] = None,
    ) -> ConversationSession:
        """
        Create a new conversation session.

        Args:
            user_id: Optional user identifier.
            tenant_id: Optional tenant identifier.
            system_prompt: Optional system prompt for this session.

        Returns:
            New ConversationSession.
        """
        session = ConversationSession(
            user_id=user_id,
            tenant_id=tenant_id,
            system_prompt=system_prompt,
        )

        # Store in Redis
        await self._save_session(session)

        # Track user's sessions
        if user_id:
            await self._add_user_session(user_id, session.id)

        return session

    async def get_session(self, session_id: UUID) -> Optional[ConversationSession]:
        """
        Get a session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            ConversationSession or None if not found.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._session_key(session_id)
        data = await self._redis.get(key)

        if not data:
            return None

        try:
            session_dict = json.loads(data)
            return ConversationSession(**session_dict)
        except (json.JSONDecodeError, ValueError):
            return None

    async def update_session(self, session: ConversationSession) -> None:
        """
        Update an existing session.

        Args:
            session: Session to update.
        """
        from datetime import datetime

        session.updated_at = datetime.utcnow()
        await self._save_session(session)

    async def delete_session(self, session_id: UUID) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session to delete.

        Returns:
            True if deleted, False if not found.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        session = await self.get_session(session_id)
        if not session:
            return False

        key = self._session_key(session_id)
        result = await self._redis.delete(key)

        # Remove from user's session list
        if session.user_id:
            await self._remove_user_session(session.user_id, session_id)

        return result > 0

    async def get_user_sessions(self, user_id: UUID) -> list[ConversationSession]:
        """
        Get all sessions for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of user's sessions sorted by updated_at (newest first).
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._user_sessions_key(user_id)
        session_ids = await self._redis.smembers(key)

        sessions = []
        for sid in session_ids:
            try:
                session = await self.get_session(UUID(sid))
                if session:
                    sessions.append(session)
            except ValueError:
                continue

        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    async def extend_ttl(self, session_id: UUID) -> None:
        """Extend session TTL on activity.

        Args:
            session_id: Session identifier.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._session_key(session_id)
        await self._redis.expire(key, self.config.session_ttl)

    async def cleanup_expired(self) -> int:
        """
        Clean up expired/inactive sessions.

        Note: Redis handles TTL-based expiration automatically.
        This method is for additional cleanup logic if needed.

        Returns:
            Number of sessions cleaned up.
        """
        # Redis handles TTL-based expiration automatically
        return 0

    async def _save_session(self, session: ConversationSession) -> None:
        """Save session to Redis.

        Args:
            session: Session to save.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._session_key(session.id)

        # Serialize session
        data = session.model_dump_json()

        # Store with TTL
        await self._redis.set(key, data, ex=self.config.session_ttl)

    async def _add_user_session(self, user_id: UUID, session_id: UUID) -> None:
        """Add session to user's session set.

        Args:
            user_id: User identifier.
            session_id: Session identifier.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._user_sessions_key(user_id)
        await self._redis.sadd(key, str(session_id))
        await self._redis.expire(key, self.config.session_ttl * 2)

        # Enforce max sessions per user
        await self._enforce_session_limit(user_id)

    async def _remove_user_session(self, user_id: UUID, session_id: UUID) -> None:
        """Remove session from user's session set.

        Args:
            user_id: User identifier.
            session_id: Session identifier.
        """
        if not self._redis:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = self._user_sessions_key(user_id)
        await self._redis.srem(key, str(session_id))

    async def _enforce_session_limit(self, user_id: UUID) -> None:
        """Enforce max sessions per user limit.

        Deletes oldest sessions if user has exceeded the limit.

        Args:
            user_id: User identifier.
        """
        sessions = await self.get_user_sessions(user_id)

        if len(sessions) > self.config.max_sessions_per_user:
            # Delete oldest sessions (already sorted newest first)
            sessions_to_delete = sessions[self.config.max_sessions_per_user :]
            for session in sessions_to_delete:
                await self.delete_session(session.id)
