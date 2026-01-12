"""Session management for conversation memory."""

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from .models import (
    ConversationSession,
    MemoryConfig,
    Message,
    MessageRole,
    SessionStats,
)
from .store import RedisSessionStore


class TokenCounter(Protocol):
    """Protocol for token counting."""

    def count(self, text: str) -> int:
        """Count tokens in text."""
        ...


class HistorySummarizerProtocol(Protocol):
    """Protocol for history summarization."""

    async def summarize(
        self,
        messages: list[Message],
        existing_summary: str | None = None,
    ) -> str:
        """Summarize messages."""
        ...


class SessionManager:
    """
    High-level session management.

    Features:
    - Message addition with token tracking
    - History retrieval with context window management
    - Automatic summarization
    - Session lifecycle management
    """

    def __init__(
        self,
        store: RedisSessionStore,
        config: MemoryConfig,
        summarizer: HistorySummarizerProtocol | None = None,
        tokenizer: TokenCounter | None = None,
    ):
        """Initialize the session manager.

        Args:
            store: Redis session store.
            config: Memory configuration.
            summarizer: Optional history summarizer.
            tokenizer: Optional token counter.
        """
        self.store = store
        self.config = config
        self.summarizer = summarizer
        self.tokenizer = tokenizer

    async def create_session(
        self,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        system_prompt: str | None = None,
    ) -> ConversationSession:
        """Create a new conversation session.

        Args:
            user_id: Optional user identifier.
            tenant_id: Optional tenant identifier.
            system_prompt: Optional system prompt.

        Returns:
            New ConversationSession.
        """
        return await self.store.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            system_prompt=system_prompt,
        )

    async def get_session(self, session_id: UUID) -> ConversationSession | None:
        """Get a session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            ConversationSession or None if not found.
        """
        return await self.store.get_session(session_id)

    async def add_message(
        self,
        session_id: UUID,
        role: MessageRole,
        content: str,
        sources: list[str] | None = None,
    ) -> Message:
        """
        Add a message to the session.

        Args:
            session_id: Session identifier.
            role: Message role.
            content: Message content.
            sources: Optional source references.

        Returns:
            Created Message.

        Raises:
            ValueError: If session not found.
        """
        session = await self.store.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        # Count tokens
        token_count = 0
        if self.tokenizer:
            token_count = self.tokenizer.count(content)

        # Create message
        message = Message(
            role=role,
            content=content,
            sources=sources,
            token_count=token_count,
        )

        # Add to session
        session.messages.append(message)
        session.total_messages += 1
        session.total_tokens += token_count
        session.last_activity = datetime.now(tz=UTC)

        # Check if summarization is needed
        if await self._should_summarize(session):
            await self._summarize_history(session)

        # Check message limit
        await self._enforce_message_limit(session)

        # Save session
        await self.store.update_session(session)

        # Extend TTL
        await self.store.extend_ttl(session_id)

        return message

    async def add_user_message(
        self,
        session_id: UUID,
        content: str,
    ) -> Message:
        """Convenience method to add a user message.

        Args:
            session_id: Session identifier.
            content: Message content.

        Returns:
            Created Message.
        """
        return await self.add_message(session_id, MessageRole.USER, content)

    async def add_assistant_message(
        self,
        session_id: UUID,
        content: str,
        sources: list[str] | None = None,
    ) -> Message:
        """Convenience method to add an assistant message.

        Args:
            session_id: Session identifier.
            content: Message content.
            sources: Optional source references.

        Returns:
            Created Message.
        """
        return await self.add_message(
            session_id,
            MessageRole.ASSISTANT,
            content,
            sources,
        )

    async def get_history(
        self,
        session_id: UUID,
        max_tokens: int | None = None,
        include_system: bool = True,
    ) -> list[Message]:
        """
        Get conversation history for context.

        Args:
            session_id: Session identifier.
            max_tokens: Max tokens to include.
            include_system: Whether to include system message.

        Returns:
            List of messages for context window.
        """
        session = await self.store.get_session(session_id)
        if not session:
            return []

        max_tokens = max_tokens or self.config.max_tokens
        messages: list[Message] = []
        token_count = 0

        # Add system prompt first
        if include_system and session.system_prompt:
            system_msg = Message(
                role=MessageRole.SYSTEM,
                content=session.system_prompt,
            )
            if self.tokenizer:
                system_msg.token_count = self.tokenizer.count(session.system_prompt)
            messages.append(system_msg)
            token_count += system_msg.token_count or 0

        # Add summary if exists
        if session.summary:
            summary_content = f"Summary of earlier conversation:\n{session.summary}"
            summary_msg = Message(
                role=MessageRole.SYSTEM,
                content=summary_content,
            )
            if self.tokenizer:
                summary_msg.token_count = self.tokenizer.count(summary_content)
            messages.append(summary_msg)
            token_count += summary_msg.token_count or 0

        # Collect recent messages that fit within token limit
        # Process from newest to oldest
        messages_to_add: list[Message] = []
        for msg in reversed(session.messages):
            msg_tokens = msg.token_count or 0
            if self.tokenizer and not msg.token_count:
                msg_tokens = self.tokenizer.count(msg.content)

            if token_count + msg_tokens > max_tokens:
                break

            messages_to_add.append(msg)
            token_count += msg_tokens

        # Reverse to get chronological order and add to messages
        messages_to_add.reverse()
        messages.extend(messages_to_add)

        return messages

    async def get_history_for_llm(
        self,
        session_id: UUID,
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get history formatted for LLM API.

        Args:
            session_id: Session identifier.
            max_tokens: Max tokens to include.

        Returns:
            List of dicts with role and content.
        """
        messages = await self.get_history(session_id, max_tokens)
        return [msg.to_dict() for msg in messages]

    async def clear_session(self, session_id: UUID) -> bool:
        """Clear all messages from a session.

        Args:
            session_id: Session identifier.

        Returns:
            True if cleared, False if session not found.
        """
        session = await self.store.get_session(session_id)
        if not session:
            return False

        session.messages = []
        session.summary = None
        session.summarized_count = 0
        session.total_messages = 0
        session.total_tokens = 0

        await self.store.update_session(session)
        return True

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session entirely.

        Args:
            session_id: Session identifier.

        Returns:
            True if deleted, False if not found.
        """
        return await self.store.delete_session(session_id)

    async def get_session_stats(self, session_id: UUID) -> SessionStats | None:
        """Get statistics for a session.

        Args:
            session_id: Session identifier.

        Returns:
            SessionStats or None if session not found.
        """
        session = await self.store.get_session(session_id)
        if not session:
            return None

        now = datetime.now(tz=UTC)

        return SessionStats(
            message_count=len(session.messages),
            total_tokens=session.total_tokens,
            summarized_messages=session.summarized_count,
            age_seconds=(now - session.created_at).total_seconds(),
            last_activity_seconds=(now - session.last_activity).total_seconds(),
        )

    async def _should_summarize(self, session: ConversationSession) -> bool:
        """Check if history should be summarized.

        Args:
            session: The session to check.

        Returns:
            True if summarization should be triggered.
        """
        if not self.config.enable_summarization:
            return False

        if not self.summarizer:
            return False

        unsummarized = len(session.messages) - session.summarized_count
        return unsummarized >= self.config.summarize_after_messages

    async def _summarize_history(self, session: ConversationSession) -> None:
        """Summarize older messages.

        Args:
            session: The session to summarize.
        """
        if not self.summarizer:
            return

        # Get messages to summarize
        messages_to_summarize = session.messages[
            : session.summarized_count + self.config.summarize_after_messages
        ]

        # Generate summary
        new_summary = await self.summarizer.summarize(
            messages_to_summarize,
            existing_summary=session.summary,
        )

        session.summary = new_summary
        session.summarized_count = len(messages_to_summarize)

    async def _enforce_message_limit(self, session: ConversationSession) -> None:
        """Remove oldest messages if over limit.

        Args:
            session: The session to enforce limits on.
        """
        while len(session.messages) > self.config.max_messages:
            removed = session.messages.pop(0)
            session.total_tokens -= removed.token_count or 0
