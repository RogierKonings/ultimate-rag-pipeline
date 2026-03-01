"""Pydantic models for conversation memory.

Database Tables (created by Alembic migration):
------------------------------------------------

conversations:
    - id: UUID PRIMARY KEY
    - tenant_id: UUID (nullable, indexed)
    - user_id: UUID (nullable, indexed)
    - created_at: TIMESTAMP WITH TIME ZONE
    - updated_at: TIMESTAMP WITH TIME ZONE
    - metadata: JSONB (contains summary, summarized_count, total_messages,
                       total_tokens, system_prompt)

messages:
    - id: UUID PRIMARY KEY
    - conversation_id: UUID REFERENCES conversations(id) ON DELETE CASCADE
    - role: VARCHAR(20) NOT NULL (enum: system, user, assistant, function)
    - content: TEXT NOT NULL
    - citations: JSONB (nullable, stores source references as JSON array)
    - token_count: INTEGER (nullable)
    - created_at: TIMESTAMP WITH TIME ZONE

Indexes:
    - conversations: tenant_id, user_id, updated_at
    - messages: conversation_id, created_at
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(UTC)


class MessageRole(StrEnum):
    """Role of a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"


class Message(BaseModel):
    """A single message in the conversation."""

    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str

    # Timestamp
    timestamp: datetime = Field(default_factory=_utc_now)

    # Token count for management
    token_count: int | None = None

    # Source tracking for assistant messages
    sources: list[str] | None = None

    # For function messages
    name: str | None = None

    def to_dict(self) -> dict:
        """Convert to dict for LLM API.

        Returns:
            Dictionary with role and content suitable for LLM API calls.
        """
        d = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


class ConversationSession(BaseModel):
    """A conversation session with history."""

    id: UUID = Field(default_factory=uuid4)

    # User/tenant info
    user_id: UUID | None = None
    tenant_id: UUID | None = None

    # Messages
    messages: list[Message] = Field(default_factory=list)

    # Summary of older messages
    summary: str | None = None
    summarized_count: int = 0  # Number of messages included in summary

    # Metadata
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    last_activity: datetime = Field(default_factory=_utc_now)

    # Stats
    total_messages: int = 0
    total_tokens: int = 0

    # Configuration
    system_prompt: str | None = None


class MemoryConfig(BaseModel):
    """Configuration for conversation memory."""

    # Session settings
    session_ttl: int = 3600  # 1 hour default
    max_sessions_per_user: int = 10

    # History limits
    max_messages: int = 50  # Max messages to keep
    max_tokens: int = 4096  # Max tokens in history

    # Summarization
    enable_summarization: bool = True
    summarize_after_messages: int = 20
    summary_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    summary_max_tokens: int = 500

    # Cleanup
    cleanup_interval: int = 300  # 5 minutes
    inactive_threshold: int = 1800  # 30 minutes

    # Redis settings
    redis_prefix: str = "session:"
    redis_url: str = "redis://localhost:6379/0"


class SessionStats(BaseModel):
    """Statistics for a session."""

    message_count: int
    total_tokens: int
    summarized_messages: int
    age_seconds: float
    last_activity_seconds: float
