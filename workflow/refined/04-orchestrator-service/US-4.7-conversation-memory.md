# US-4.7: Conversation Memory

> **Story ID:** US-4.7  
> **Epic:** Orchestrator Service  
> **Priority:** High  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-4.1 (LangGraph Workflow), Epic 1 (Infrastructure - Redis)

## User Story

**As a** developer  
**I want** conversation history management  
**So that** multi-turn conversations work correctly

## Context

Conversation memory enables multi-turn interactions by maintaining chat history across requests within a session. The system uses Redis for session storage, supports configurable history length, implements history summarization for long conversations to manage token limits, and handles session timeout and cleanup. Memory integrates with the prompt builder to include relevant conversation context in each request.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── memory/
    ├── __init__.py
    ├── session.py           # Session management
    ├── store.py             # Redis storage
    ├── summarizer.py        # History summarization
    ├── models.py            # Pydantic models
    └── config.py            # Configuration
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum

class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"

class Message(BaseModel):
    """A single message in the conversation."""
    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str
    
    # Optional metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    name: Optional[str] = None  # For function messages
    
    # Token count (for management)
    token_count: Optional[int] = None
    
    # Source tracking
    sources: Optional[list[str]] = None  # Referenced sources
    
    def to_dict(self) -> dict:
        """Convert to dict for LLM API."""
        d = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d

class ConversationSession(BaseModel):
    """A conversation session with history."""
    id: UUID = Field(default_factory=uuid4)
    
    # User/tenant info
    user_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    
    # Messages
    messages: list[Message] = []
    
    # Summary of older messages
    summary: Optional[str] = None
    summarized_count: int = 0  # Messages included in summary
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    
    # Stats
    total_messages: int = 0
    total_tokens: int = 0
    
    # Configuration
    system_prompt: Optional[str] = None

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
```

### Redis Session Store

```python
import redis.asyncio as redis
import json
from typing import Optional
from datetime import datetime, timedelta
from uuid import UUID

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
        self.config = config
        self._redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis."""
        self._redis = await redis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
    
    def _session_key(self, session_id: UUID) -> str:
        """Get Redis key for session."""
        return f"{self.config.redis_prefix}{session_id}"
    
    def _user_sessions_key(self, user_id: UUID) -> str:
        """Get Redis key for user's session list."""
        return f"{self.config.redis_prefix}user:{user_id}:sessions"
    
    async def create_session(
        self,
        user_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        """
        Create a new conversation session.
        
        Args:
            user_id: Optional user identifier
            tenant_id: Optional tenant identifier
            system_prompt: Optional system prompt for this session
        
        Returns:
            New ConversationSession
        """
        session = ConversationSession(
            user_id=user_id,
            tenant_id=tenant_id,
            system_prompt=system_prompt
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
            session_id: Session identifier
        
        Returns:
            ConversationSession or None if not found
        """
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
            session: Session to update
        """
        session.updated_at = datetime.utcnow()
        await self._save_session(session)
    
    async def delete_session(self, session_id: UUID) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session to delete
        
        Returns:
            True if deleted, False if not found
        """
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
            user_id: User identifier
        
        Returns:
            List of user's sessions
        """
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
        """Extend session TTL on activity."""
        key = self._session_key(session_id)
        await self._redis.expire(key, self.config.session_ttl)
    
    async def cleanup_expired(self) -> int:
        """
        Clean up expired/inactive sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        # Redis handles TTL-based expiration automatically
        # This is for additional cleanup logic
        return 0
    
    async def _save_session(self, session: ConversationSession) -> None:
        """Save session to Redis."""
        key = self._session_key(session.id)
        
        # Serialize session
        data = session.model_dump_json()
        
        # Store with TTL
        await self._redis.set(key, data, ex=self.config.session_ttl)
    
    async def _add_user_session(self, user_id: UUID, session_id: UUID) -> None:
        """Add session to user's session set."""
        key = self._user_sessions_key(user_id)
        await self._redis.sadd(key, str(session_id))
        await self._redis.expire(key, self.config.session_ttl * 2)
        
        # Enforce max sessions per user
        await self._enforce_session_limit(user_id)
    
    async def _remove_user_session(self, user_id: UUID, session_id: UUID) -> None:
        """Remove session from user's session set."""
        key = self._user_sessions_key(user_id)
        await self._redis.srem(key, str(session_id))
    
    async def _enforce_session_limit(self, user_id: UUID) -> None:
        """Enforce max sessions per user limit."""
        sessions = await self.get_user_sessions(user_id)
        
        if len(sessions) > self.config.max_sessions_per_user:
            # Delete oldest sessions
            sessions_to_delete = sessions[self.config.max_sessions_per_user:]
            for session in sessions_to_delete:
                await self.delete_session(session.id)
```

### Session Manager

```python
from typing import Optional
from uuid import UUID

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
        summarizer = None,  # HistorySummarizer
        tokenizer = None    # TokenCounter
    ):
        self.store = store
        self.config = config
        self.summarizer = summarizer
        self.tokenizer = tokenizer
    
    async def create_session(
        self,
        user_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        system_prompt: Optional[str] = None
    ) -> ConversationSession:
        """Create a new conversation session."""
        return await self.store.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            system_prompt=system_prompt
        )
    
    async def get_session(self, session_id: UUID) -> Optional[ConversationSession]:
        """Get a session by ID."""
        return await self.store.get_session(session_id)
    
    async def add_message(
        self,
        session_id: UUID,
        role: MessageRole,
        content: str,
        sources: Optional[list[str]] = None
    ) -> Message:
        """
        Add a message to the session.
        
        Args:
            session_id: Session identifier
            role: Message role
            content: Message content
            sources: Optional source references
        
        Returns:
            Created Message
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
            token_count=token_count
        )
        
        # Add to session
        session.messages.append(message)
        session.total_messages += 1
        session.total_tokens += token_count
        session.last_activity = datetime.utcnow()
        
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
        content: str
    ) -> Message:
        """Convenience method to add a user message."""
        return await self.add_message(session_id, MessageRole.USER, content)
    
    async def add_assistant_message(
        self,
        session_id: UUID,
        content: str,
        sources: Optional[list[str]] = None
    ) -> Message:
        """Convenience method to add an assistant message."""
        return await self.add_message(
            session_id, 
            MessageRole.ASSISTANT, 
            content,
            sources
        )
    
    async def get_history(
        self,
        session_id: UUID,
        max_tokens: Optional[int] = None,
        include_system: bool = True
    ) -> list[Message]:
        """
        Get conversation history for context.
        
        Args:
            session_id: Session identifier
            max_tokens: Max tokens to include
            include_system: Whether to include system message
        
        Returns:
            List of messages for context window
        """
        session = await self.store.get_session(session_id)
        if not session:
            return []
        
        max_tokens = max_tokens or self.config.max_tokens
        messages = []
        token_count = 0
        
        # Add system prompt first
        if include_system and session.system_prompt:
            system_msg = Message(
                role=MessageRole.SYSTEM,
                content=session.system_prompt
            )
            if self.tokenizer:
                system_msg.token_count = self.tokenizer.count(session.system_prompt)
            messages.append(system_msg)
            token_count += system_msg.token_count or 0
        
        # Add summary if exists
        if session.summary:
            summary_msg = Message(
                role=MessageRole.SYSTEM,
                content=f"Summary of earlier conversation:\n{session.summary}"
            )
            if self.tokenizer:
                summary_msg.token_count = self.tokenizer.count(summary_msg.content)
            messages.append(summary_msg)
            token_count += summary_msg.token_count or 0
        
        # Add recent messages (from newest to oldest until token limit)
        for msg in reversed(session.messages):
            msg_tokens = msg.token_count or 0
            if self.tokenizer and not msg.token_count:
                msg_tokens = self.tokenizer.count(msg.content)
            
            if token_count + msg_tokens > max_tokens:
                break
            
            messages.insert(len(messages), msg)
            token_count += msg_tokens
        
        return messages
    
    async def get_history_for_llm(
        self,
        session_id: UUID,
        max_tokens: Optional[int] = None
    ) -> list[dict]:
        """
        Get history formatted for LLM API.
        
        Returns list of dicts with role and content.
        """
        messages = await self.get_history(session_id, max_tokens)
        return [msg.to_dict() for msg in messages]
    
    async def clear_session(self, session_id: UUID) -> bool:
        """Clear all messages from a session."""
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
        """Delete a session entirely."""
        return await self.store.delete_session(session_id)
    
    async def get_session_stats(self, session_id: UUID) -> Optional[SessionStats]:
        """Get statistics for a session."""
        session = await self.store.get_session(session_id)
        if not session:
            return None
        
        now = datetime.utcnow()
        
        return SessionStats(
            message_count=len(session.messages),
            total_tokens=session.total_tokens,
            summarized_messages=session.summarized_count,
            age_seconds=(now - session.created_at).total_seconds(),
            last_activity_seconds=(now - session.last_activity).total_seconds()
        )
    
    async def _should_summarize(self, session: ConversationSession) -> bool:
        """Check if history should be summarized."""
        if not self.config.enable_summarization:
            return False
        
        if not self.summarizer:
            return False
        
        unsummarized = len(session.messages) - session.summarized_count
        return unsummarized >= self.config.summarize_after_messages
    
    async def _summarize_history(self, session: ConversationSession) -> None:
        """Summarize older messages."""
        if not self.summarizer:
            return
        
        # Get messages to summarize
        messages_to_summarize = session.messages[:session.summarized_count + self.config.summarize_after_messages]
        
        # Generate summary
        new_summary = await self.summarizer.summarize(
            messages_to_summarize,
            existing_summary=session.summary
        )
        
        session.summary = new_summary
        session.summarized_count = len(messages_to_summarize)
    
    async def _enforce_message_limit(self, session: ConversationSession) -> None:
        """Remove oldest messages if over limit."""
        while len(session.messages) > self.config.max_messages:
            removed = session.messages.pop(0)
            session.total_tokens -= removed.token_count or 0
```

### History Summarizer

```python
from typing import Optional

class HistorySummarizer:
    """
    Summarizes conversation history to save tokens.
    
    Uses an LLM to create concise summaries of older
    conversation turns that can be included as context.
    """
    
    SUMMARIZE_PROMPT = """Summarize the following conversation history into a concise paragraph. 
Focus on key topics discussed, decisions made, and any important context for future messages.

{existing_summary}

Recent messages:
{messages}

Provide a brief summary (max 2-3 paragraphs):"""
    
    def __init__(
        self,
        config: MemoryConfig,
        gateway = None  # ModelGateway
    ):
        self.config = config
        self.gateway = gateway
    
    async def summarize(
        self,
        messages: list[Message],
        existing_summary: Optional[str] = None
    ) -> str:
        """
        Summarize a list of messages.
        
        Args:
            messages: Messages to summarize
            existing_summary: Previous summary to incorporate
        
        Returns:
            Summary text
        """
        if not self.gateway:
            # Fallback: simple truncation
            return self._simple_summary(messages)
        
        # Format messages for prompt
        formatted = self._format_messages(messages)
        
        existing = ""
        if existing_summary:
            existing = f"Previous summary:\n{existing_summary}\n\n"
        
        prompt = self.SUMMARIZE_PROMPT.format(
            existing_summary=existing,
            messages=formatted
        )
        
        try:
            from gateway.models import ChatCompletionRequest, ChatMessage
            
            request = ChatCompletionRequest(
                model=self.config.summary_model,
                messages=[
                    ChatMessage(role="user", content=prompt)
                ],
                max_tokens=self.config.summary_max_tokens,
                temperature=0.3  # Lower temperature for consistent summaries
            )
            
            response = await self.gateway.chat_completion(request)
            return response.choices[0].message.content
            
        except Exception:
            return self._simple_summary(messages)
    
    def _format_messages(self, messages: list[Message]) -> str:
        """Format messages for summary prompt."""
        lines = []
        for msg in messages:
            role = msg.role.value.capitalize()
            content = msg.content[:500]  # Truncate long messages
            if len(msg.content) > 500:
                content += "..."
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    
    def _simple_summary(self, messages: list[Message]) -> str:
        """Create simple summary without LLM."""
        if not messages:
            return ""
        
        # Extract key topics (simple heuristic)
        user_messages = [m for m in messages if m.role == MessageRole.USER]
        
        if not user_messages:
            return "Previous conversation context."
        
        topics = []
        for msg in user_messages[-5:]:  # Last 5 user messages
            # Take first sentence or first 100 chars
            content = msg.content.split('.')[0][:100]
            topics.append(content)
        
        return f"Topics discussed: {'; '.join(topics)}"
```

### LangGraph Integration

```python
from langgraph.graph import StateGraph
from typing import TypedDict, Optional
from uuid import UUID

class ConversationState(TypedDict):
    session_id: Optional[UUID]
    user_id: Optional[UUID]
    query: str
    messages: list[dict]
    response: Optional[str]
    sources: Optional[list[str]]

class MemoryNode:
    """LangGraph node for conversation memory."""
    
    def __init__(self, session_manager: SessionManager):
        self.manager = session_manager
    
    async def load_history(self, state: ConversationState) -> ConversationState:
        """Load conversation history into state."""
        session_id = state.get("session_id")
        
        if not session_id:
            # Create new session
            session = await self.manager.create_session(
                user_id=state.get("user_id")
            )
            session_id = session.id
        
        # Get formatted history
        messages = await self.manager.get_history_for_llm(session_id)
        
        # Add current query
        messages.append({"role": "user", "content": state["query"]})
        
        return {
            **state,
            "session_id": session_id,
            "messages": messages
        }
    
    async def save_turn(self, state: ConversationState) -> ConversationState:
        """Save the conversation turn to memory."""
        session_id = state.get("session_id")
        
        if not session_id:
            return state
        
        # Save user message
        await self.manager.add_user_message(
            session_id,
            state["query"]
        )
        
        # Save assistant response
        if state.get("response"):
            await self.manager.add_assistant_message(
                session_id,
                state["response"],
                sources=state.get("sources")
            )
        
        return state

# Build graph with memory nodes
def build_conversational_graph(session_manager: SessionManager) -> StateGraph:
    memory = MemoryNode(session_manager)
    
    graph = StateGraph(ConversationState)
    
    graph.add_node("load_history", memory.load_history)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("save_turn", memory.save_turn)
    
    graph.add_edge("load_history", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "save_turn")
    
    graph.set_entry_point("load_history")
    graph.set_finish_point("save_turn")
    
    return graph
```

### FastAPI Integration

```python
from fastapi import FastAPI, Depends, HTTPException
from typing import Optional
from uuid import UUID

app = FastAPI()

async def get_session_manager() -> SessionManager:
    """Dependency for session manager."""
    # Initialize from app state
    return app.state.session_manager

@app.post("/sessions")
async def create_session(
    user_id: Optional[UUID] = None,
    system_prompt: Optional[str] = None,
    manager: SessionManager = Depends(get_session_manager)
) -> dict:
    """Create a new conversation session."""
    session = await manager.create_session(
        user_id=user_id,
        system_prompt=system_prompt
    )
    return {
        "session_id": str(session.id),
        "created_at": session.created_at.isoformat()
    }

@app.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    manager: SessionManager = Depends(get_session_manager)
) -> dict:
    """Get session details and history."""
    session = await manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": str(session.id),
        "messages": [msg.to_dict() for msg in session.messages],
        "total_messages": session.total_messages,
        "total_tokens": session.total_tokens,
        "has_summary": session.summary is not None,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat()
    }

@app.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: UUID,
    max_tokens: Optional[int] = None,
    manager: SessionManager = Depends(get_session_manager)
) -> list[dict]:
    """Get session history formatted for LLM."""
    messages = await manager.get_history_for_llm(session_id, max_tokens)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")
    return messages

@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    manager: SessionManager = Depends(get_session_manager)
) -> dict:
    """Delete a session."""
    deleted = await manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}

@app.post("/sessions/{session_id}/clear")
async def clear_session(
    session_id: UUID,
    manager: SessionManager = Depends(get_session_manager)
) -> dict:
    """Clear session messages but keep session."""
    cleared = await manager.clear_session(session_id)
    if not cleared:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "cleared"}

@app.get("/sessions/{session_id}/stats")
async def get_session_stats(
    session_id: UUID,
    manager: SessionManager = Depends(get_session_manager)
) -> SessionStats:
    """Get session statistics."""
    stats = await manager.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Session not found")
    return stats

@app.get("/users/{user_id}/sessions")
async def get_user_sessions(
    user_id: UUID,
    manager: SessionManager = Depends(get_session_manager)
) -> list[dict]:
    """Get all sessions for a user."""
    sessions = await manager.store.get_user_sessions(user_id)
    return [
        {
            "session_id": str(s.id),
            "message_count": len(s.messages),
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat()
        }
        for s in sessions
    ]
```

## Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timedelta
import json

@pytest.fixture
def memory_config():
    return MemoryConfig(
        session_ttl=3600,
        max_messages=50,
        max_tokens=4096,
        enable_summarization=True,
        summarize_after_messages=20
    )

@pytest.fixture
async def redis_store(memory_config):
    """Create store with mocked Redis."""
    store = RedisSessionStore(memory_config)
    store._redis = AsyncMock()
    return store

@pytest.fixture
def session_manager(redis_store, memory_config):
    tokenizer = MagicMock()
    tokenizer.count = lambda x: len(x.split())
    return SessionManager(redis_store, memory_config, tokenizer=tokenizer)

# Message Tests
def test_message_to_dict():
    """Test message conversion to dict."""
    msg = Message(
        role=MessageRole.USER,
        content="Hello"
    )
    
    d = msg.to_dict()
    
    assert d["role"] == "user"
    assert d["content"] == "Hello"
    assert "name" not in d

def test_message_with_name():
    """Test function message with name."""
    msg = Message(
        role=MessageRole.FUNCTION,
        content="result",
        name="search"
    )
    
    d = msg.to_dict()
    
    assert d["name"] == "search"

# Session Store Tests
@pytest.mark.asyncio
async def test_create_session(redis_store):
    """Test session creation."""
    user_id = uuid4()
    
    session = await redis_store.create_session(user_id=user_id)
    
    assert session.user_id == user_id
    assert session.id is not None
    redis_store._redis.set.assert_called()

@pytest.mark.asyncio
async def test_get_session(redis_store):
    """Test session retrieval."""
    session_id = uuid4()
    session_data = ConversationSession(id=session_id)
    
    redis_store._redis.get.return_value = session_data.model_dump_json()
    
    result = await redis_store.get_session(session_id)
    
    assert result is not None
    assert result.id == session_id

@pytest.mark.asyncio
async def test_get_session_not_found(redis_store):
    """Test session not found."""
    redis_store._redis.get.return_value = None
    
    result = await redis_store.get_session(uuid4())
    
    assert result is None

@pytest.mark.asyncio
async def test_delete_session(redis_store):
    """Test session deletion."""
    session_id = uuid4()
    session = ConversationSession(id=session_id, user_id=uuid4())
    
    redis_store._redis.get.return_value = session.model_dump_json()
    redis_store._redis.delete.return_value = 1
    
    result = await redis_store.delete_session(session_id)
    
    assert result is True
    redis_store._redis.delete.assert_called()

@pytest.mark.asyncio
async def test_session_ttl_extended(redis_store):
    """Test TTL extension on activity."""
    session_id = uuid4()
    
    await redis_store.extend_ttl(session_id)
    
    redis_store._redis.expire.assert_called_with(
        redis_store._session_key(session_id),
        redis_store.config.session_ttl
    )

# Session Manager Tests
@pytest.mark.asyncio
async def test_add_message(session_manager):
    """Test adding a message."""
    session_id = uuid4()
    session = ConversationSession(id=session_id)
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    session_manager.store.update_session = AsyncMock()
    session_manager.store.extend_ttl = AsyncMock()
    
    message = await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "Hello, how are you?"
    )
    
    assert message.role == MessageRole.USER
    assert message.content == "Hello, how are you?"
    session_manager.store.update_session.assert_called()

@pytest.mark.asyncio
async def test_add_message_session_not_found(session_manager):
    """Test adding message to non-existent session."""
    session_manager.store.get_session = AsyncMock(return_value=None)
    
    with pytest.raises(ValueError, match="Session not found"):
        await session_manager.add_message(
            uuid4(),
            MessageRole.USER,
            "Hello"
        )

@pytest.mark.asyncio
async def test_get_history(session_manager):
    """Test history retrieval."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        system_prompt="You are helpful.",
        messages=[
            Message(role=MessageRole.USER, content="Hi"),
            Message(role=MessageRole.ASSISTANT, content="Hello!")
        ]
    )
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    
    history = await session_manager.get_history(session_id)
    
    # Should include system prompt + messages
    assert len(history) == 3
    assert history[0].role == MessageRole.SYSTEM

@pytest.mark.asyncio
async def test_get_history_with_token_limit(session_manager):
    """Test history respects token limits."""
    session_id = uuid4()
    
    # Create many messages
    messages = [
        Message(role=MessageRole.USER, content="Message " * 100, token_count=100)
        for _ in range(10)
    ]
    
    session = ConversationSession(id=session_id, messages=messages)
    session_manager.store.get_session = AsyncMock(return_value=session)
    
    history = await session_manager.get_history(session_id, max_tokens=250)
    
    # Should be truncated
    assert len(history) < len(messages)

@pytest.mark.asyncio
async def test_clear_session(session_manager):
    """Test clearing session messages."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[Message(role=MessageRole.USER, content="Hi")],
        summary="Previous conversation",
        total_messages=5
    )
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    session_manager.store.update_session = AsyncMock()
    
    result = await session_manager.clear_session(session_id)
    
    assert result is True
    session_manager.store.update_session.assert_called()
    
    # Check session was cleared
    updated_session = session_manager.store.update_session.call_args[0][0]
    assert len(updated_session.messages) == 0
    assert updated_session.summary is None

@pytest.mark.asyncio
async def test_session_stats(session_manager):
    """Test session statistics."""
    session_id = uuid4()
    now = datetime.utcnow()
    session = ConversationSession(
        id=session_id,
        messages=[Message(role=MessageRole.USER, content="Hi")],
        total_tokens=100,
        created_at=now - timedelta(hours=1),
        last_activity=now - timedelta(minutes=5)
    )
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    
    stats = await session_manager.get_session_stats(session_id)
    
    assert stats.message_count == 1
    assert stats.total_tokens == 100
    assert stats.age_seconds > 0

@pytest.mark.asyncio
async def test_message_limit_enforcement(session_manager):
    """Test that old messages are removed when limit exceeded."""
    session_manager.config.max_messages = 5
    
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[
            Message(role=MessageRole.USER, content=f"Msg {i}", token_count=10)
            for i in range(5)
        ],
        total_tokens=50
    )
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    session_manager.store.update_session = AsyncMock()
    session_manager.store.extend_ttl = AsyncMock()
    
    # Add one more message
    await session_manager.add_message(
        session_id,
        MessageRole.USER,
        "New message"
    )
    
    # Check oldest was removed
    updated = session_manager.store.update_session.call_args[0][0]
    assert len(updated.messages) == 5

# Summarizer Tests
@pytest.mark.asyncio
async def test_summarizer_simple_fallback(memory_config):
    """Test simple summary without LLM."""
    summarizer = HistorySummarizer(memory_config)
    
    messages = [
        Message(role=MessageRole.USER, content="What is Python?"),
        Message(role=MessageRole.ASSISTANT, content="Python is a programming language."),
        Message(role=MessageRole.USER, content="How do I learn it?"),
    ]
    
    summary = await summarizer.summarize(messages)
    
    assert len(summary) > 0
    assert "Python" in summary or "Topics discussed" in summary

@pytest.mark.asyncio
async def test_summarizer_with_gateway(memory_config):
    """Test LLM-based summarization."""
    gateway = AsyncMock()
    gateway.chat_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Summary of discussion."))]
    )
    
    summarizer = HistorySummarizer(memory_config, gateway)
    
    messages = [
        Message(role=MessageRole.USER, content="Hello"),
        Message(role=MessageRole.ASSISTANT, content="Hi there!")
    ]
    
    summary = await summarizer.summarize(messages)
    
    assert summary == "Summary of discussion."
    gateway.chat_completion.assert_called()

# LangGraph Integration Tests
@pytest.mark.asyncio
async def test_memory_node_load_history(session_manager):
    """Test LangGraph memory node loading."""
    session_id = uuid4()
    session = ConversationSession(
        id=session_id,
        messages=[Message(role=MessageRole.USER, content="Previous")]
    )
    
    session_manager.store.get_session = AsyncMock(return_value=session)
    
    memory_node = MemoryNode(session_manager)
    
    state = {
        "session_id": session_id,
        "query": "New question",
        "messages": []
    }
    
    result = await memory_node.load_history(state)
    
    assert len(result["messages"]) == 2  # Previous + new query
    assert result["messages"][-1]["content"] == "New question"

@pytest.mark.asyncio
async def test_memory_node_creates_session(session_manager):
    """Test that memory node creates session if needed."""
    new_session = ConversationSession()
    session_manager.create_session = AsyncMock(return_value=new_session)
    session_manager.get_history_for_llm = AsyncMock(return_value=[])
    
    memory_node = MemoryNode(session_manager)
    
    state = {
        "session_id": None,
        "user_id": uuid4(),
        "query": "Hello",
        "messages": []
    }
    
    result = await memory_node.load_history(state)
    
    assert result["session_id"] is not None
    session_manager.create_session.assert_called()

@pytest.mark.asyncio
async def test_memory_node_save_turn(session_manager):
    """Test saving conversation turn."""
    session_id = uuid4()
    
    session_manager.add_user_message = AsyncMock()
    session_manager.add_assistant_message = AsyncMock()
    
    memory_node = MemoryNode(session_manager)
    
    state = {
        "session_id": session_id,
        "query": "What is AI?",
        "response": "AI is artificial intelligence.",
        "sources": ["doc1.pdf"],
        "messages": []
    }
    
    await memory_node.save_turn(state)
    
    session_manager.add_user_message.assert_called_with(session_id, "What is AI?")
    session_manager.add_assistant_message.assert_called_with(
        session_id,
        "AI is artificial intelligence.",
        sources=["doc1.pdf"]
    )
```

## Dependencies

- `redis>=5.0.0`
- `pydantic>=2.0.0`
- `langgraph>=0.0.20`

## Definition of Done

- [ ] ConversationSession model stores messages and metadata
- [ ] RedisSessionStore creates/reads/updates/deletes sessions
- [ ] Session TTL expiration works correctly
- [ ] User session limits enforced
- [ ] SessionManager adds messages with token tracking
- [ ] History retrieval respects token limits
- [ ] Older messages excluded to fit context window
- [ ] Summary included in history when available
- [ ] HistorySummarizer creates summaries with LLM
- [ ] Fallback summary works without LLM
- [ ] Auto-summarization triggers at configured threshold
- [ ] LangGraph MemoryNode loads and saves history
- [ ] Session created automatically if needed
- [ ] FastAPI endpoints for session CRUD operations
- [ ] Session stats available
- [ ] User sessions listing works
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
