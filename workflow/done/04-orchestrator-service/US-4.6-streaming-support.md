# US-4.6: Streaming Support

> **Story ID:** US-4.6  
> **Epic:** Orchestrator Service  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-4.4 (Model Gateway), US-4.8 (Orchestrator API)

## User Story

**As a** developer  
**I want** streaming response generation  
**So that** users see responses progressively

## Context

Streaming support enables real-time, token-by-token response delivery to clients using Server-Sent Events (SSE). This significantly improves perceived latency as users see responses building progressively rather than waiting for complete generation. The streaming system integrates with LangGraph workflows, supports metadata injection in stream chunks, handles errors gracefully mid-stream, and manages connection timeouts. Streaming is essential for long-form responses and conversational applications.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── streaming/
    ├── __init__.py
    ├── sse.py               # SSE implementation
    ├── manager.py           # Stream manager
    ├── models.py            # Streaming models
    ├── middleware.py        # Streaming middleware
    └── handlers.py          # Stream event handlers
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any, AsyncIterator
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4

class StreamEventType(str, Enum):
    # Content events
    TOKEN = "token"              # Individual token
    CHUNK = "chunk"              # Multi-token chunk
    CONTENT = "content"          # Content block
    
    # Metadata events
    START = "start"              # Stream started
    METADATA = "metadata"        # Stream metadata
    SOURCES = "sources"          # Source citations
    
    # Status events
    DONE = "done"                # Stream completed
    ERROR = "error"              # Error occurred
    HEARTBEAT = "heartbeat"      # Keep-alive ping
    
    # Progress events
    STAGE = "stage"              # Pipeline stage update
    PROGRESS = "progress"        # Progress indicator

class StreamEvent(BaseModel):
    """A single event in the SSE stream."""
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    event: StreamEventType
    data: Any
    
    # Timing
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Optional retry hint (ms)
    retry: Optional[int] = None
    
    def to_sse(self) -> str:
        """Format as SSE message."""
        lines = []
        
        if self.id:
            lines.append(f"id: {self.id}")
        
        lines.append(f"event: {self.event.value}")
        
        # Handle different data types
        if isinstance(self.data, str):
            # Multi-line strings need proper formatting
            for line in self.data.split('\n'):
                lines.append(f"data: {line}")
        elif isinstance(self.data, dict):
            import json
            lines.append(f"data: {json.dumps(self.data)}")
        else:
            lines.append(f"data: {self.data}")
        
        if self.retry:
            lines.append(f"retry: {self.retry}")
        
        return '\n'.join(lines) + '\n\n'

class StreamMetadata(BaseModel):
    """Metadata sent at stream start."""
    request_id: UUID
    model: str
    session_id: Optional[str] = None
    
    # Timing estimates
    estimated_tokens: Optional[int] = None
    
    # Pipeline info
    retrieval_time_ms: Optional[float] = None
    sources_count: Optional[int] = None

class SourceCitation(BaseModel):
    """Source citation for retrieved content."""
    id: str
    title: Optional[str] = None
    source: str
    score: float
    snippet: Optional[str] = None

class StreamConfig(BaseModel):
    """Configuration for streaming."""
    # Chunking
    chunk_size: int = 1  # Tokens per chunk (1 = token-by-token)
    buffer_size: int = 10  # Buffer before flushing
    
    # Timeouts
    client_timeout: float = 300.0  # 5 minutes
    heartbeat_interval: float = 15.0  # Seconds between heartbeats
    write_timeout: float = 10.0  # Timeout for writing to client
    
    # Error handling
    retry_on_error: bool = True
    max_retries: int = 3
    error_retry_delay: int = 1000  # ms
    
    # Metadata
    include_metadata: bool = True
    include_sources: bool = True
    include_timing: bool = True

class StreamState(BaseModel):
    """State of an active stream."""
    request_id: UUID
    started_at: datetime
    tokens_sent: int = 0
    bytes_sent: int = 0
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    completed: bool = False
    error: Optional[str] = None
```

### SSE Response Implementation

```python
import asyncio
from typing import AsyncIterator, Optional
from fastapi import Request
from fastapi.responses import StreamingResponse
import json
import time

class SSEResponse(StreamingResponse):
    """
    Server-Sent Events response for FastAPI.
    
    Handles proper SSE formatting, connection management,
    and client disconnection detection.
    """
    
    media_type = "text/event-stream"
    
    def __init__(
        self,
        content: AsyncIterator[StreamEvent],
        config: StreamConfig = StreamConfig(),
        **kwargs
    ):
        super().__init__(
            content=self._generate(content, config),
            media_type=self.media_type,
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
            **kwargs
        )
        self.config = config
    
    async def _generate(
        self,
        events: AsyncIterator[StreamEvent],
        config: StreamConfig
    ) -> AsyncIterator[bytes]:
        """Generate SSE formatted bytes from events."""
        try:
            async for event in events:
                sse_data = event.to_sse()
                yield sse_data.encode('utf-8')
                
        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as e:
            # Send error event before closing
            error_event = StreamEvent(
                event=StreamEventType.ERROR,
                data={"error": str(e), "recoverable": False}
            )
            yield error_event.to_sse().encode('utf-8')


class SSEWriter:
    """
    Helper for writing SSE events with proper formatting.
    
    Used when manual control over the stream is needed.
    """
    
    def __init__(self, config: StreamConfig = StreamConfig()):
        self.config = config
        self._buffer: list[StreamEvent] = []
    
    def event(
        self,
        event_type: StreamEventType,
        data: Any,
        **kwargs
    ) -> StreamEvent:
        """Create a new stream event."""
        return StreamEvent(event=event_type, data=data, **kwargs)
    
    def token(self, content: str) -> StreamEvent:
        """Create a token event."""
        return self.event(StreamEventType.TOKEN, content)
    
    def chunk(self, content: str) -> StreamEvent:
        """Create a chunk event."""
        return self.event(StreamEventType.CHUNK, content)
    
    def metadata(self, meta: StreamMetadata) -> StreamEvent:
        """Create a metadata event."""
        return self.event(StreamEventType.METADATA, meta.model_dump())
    
    def sources(self, citations: list[SourceCitation]) -> StreamEvent:
        """Create a sources event."""
        return self.event(
            StreamEventType.SOURCES,
            [c.model_dump() for c in citations]
        )
    
    def error(self, message: str, recoverable: bool = False) -> StreamEvent:
        """Create an error event."""
        return self.event(
            StreamEventType.ERROR,
            {"error": message, "recoverable": recoverable}
        )
    
    def done(self, stats: Optional[dict] = None) -> StreamEvent:
        """Create a done event."""
        return self.event(StreamEventType.DONE, stats or {})
    
    def heartbeat(self) -> StreamEvent:
        """Create a heartbeat event."""
        return self.event(StreamEventType.HEARTBEAT, "ping")
    
    def stage(self, stage_name: str, status: str = "started") -> StreamEvent:
        """Create a stage progress event."""
        return self.event(
            StreamEventType.STAGE,
            {"stage": stage_name, "status": status}
        )
```

### Stream Manager

```python
import asyncio
from typing import AsyncIterator, Optional, Callable, Any
from uuid import UUID, uuid4
from datetime import datetime
import time

class StreamManager:
    """
    Manages streaming response generation.
    
    Features:
    - Coordinates streaming from LLM gateway
    - Injects metadata and sources
    - Handles heartbeats for long streams
    - Tracks stream state and statistics
    - Graceful error handling
    """
    
    def __init__(
        self,
        config: StreamConfig = StreamConfig(),
        gateway = None  # ModelGateway
    ):
        self.config = config
        self.gateway = gateway
        self._active_streams: dict[UUID, StreamState] = {}
        self._writer = SSEWriter(config)
    
    async def stream_response(
        self,
        request_id: UUID,
        model: str,
        messages: list,
        sources: Optional[list[SourceCitation]] = None,
        session_id: Optional[str] = None,
        on_token: Optional[Callable[[str], None]] = None
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream a complete RAG response.
        
        Args:
            request_id: Unique request identifier
            model: Model to use for generation
            messages: Chat messages for the LLM
            sources: Retrieved sources for citation
            session_id: Optional session for conversation
            on_token: Optional callback for each token
        
        Yields:
            StreamEvent objects for the SSE response
        """
        # Initialize stream state
        state = StreamState(
            request_id=request_id,
            started_at=datetime.utcnow()
        )
        self._active_streams[request_id] = state
        
        start_time = time.perf_counter()
        
        try:
            # Send start event
            yield self._writer.event(StreamEventType.START, {
                "request_id": str(request_id),
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Send metadata
            if self.config.include_metadata:
                yield self._writer.metadata(StreamMetadata(
                    request_id=request_id,
                    model=model,
                    session_id=session_id,
                    sources_count=len(sources) if sources else 0
                ))
            
            # Send sources before content
            if self.config.include_sources and sources:
                yield self._writer.sources(sources)
            
            # Stage: generation
            yield self._writer.stage("generation", "started")
            
            # Stream tokens from LLM
            full_response = ""
            async for event in self._stream_tokens(model, messages, state, on_token):
                yield event
                if event.event == StreamEventType.TOKEN:
                    full_response += event.data
            
            yield self._writer.stage("generation", "completed")
            
            # Calculate final stats
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            # Send done event with stats
            yield self._writer.done({
                "tokens": state.tokens_sent,
                "elapsed_ms": elapsed_ms,
                "tokens_per_second": state.tokens_sent / (elapsed_ms / 1000) if elapsed_ms > 0 else 0
            })
            
            state.completed = True
            
        except asyncio.CancelledError:
            # Client disconnected
            state.error = "Client disconnected"
            raise
        except Exception as e:
            state.error = str(e)
            yield self._writer.error(str(e), recoverable=False)
            raise
        finally:
            # Cleanup
            if request_id in self._active_streams:
                del self._active_streams[request_id]
    
    async def _stream_tokens(
        self,
        model: str,
        messages: list,
        state: StreamState,
        on_token: Optional[Callable[[str], None]]
    ) -> AsyncIterator[StreamEvent]:
        """Stream tokens from the LLM gateway."""
        if not self.gateway:
            raise ValueError("No gateway configured")
        
        from gateway.models import ChatCompletionRequest, ChatMessage
        
        request = ChatCompletionRequest(
            model=model,
            messages=messages,
            stream=True
        )
        
        buffer = ""
        last_heartbeat = time.time()
        
        async for chunk in self.gateway.chat_completion_stream(request):
            # Check for heartbeat
            if time.time() - last_heartbeat > self.config.heartbeat_interval:
                yield self._writer.heartbeat()
                last_heartbeat = time.time()
            
            # Extract content from chunk
            if chunk.choices:
                delta = chunk.choices[0].get("delta", {})
                content = delta.get("content", "")
                
                if content:
                    state.tokens_sent += 1
                    state.last_activity = datetime.utcnow()
                    
                    if on_token:
                        on_token(content)
                    
                    # Buffer for chunk mode
                    if self.config.chunk_size > 1:
                        buffer += content
                        if len(buffer) >= self.config.chunk_size:
                            yield self._writer.chunk(buffer)
                            buffer = ""
                    else:
                        yield self._writer.token(content)
        
        # Flush remaining buffer
        if buffer:
            yield self._writer.chunk(buffer)
    
    def get_stream_state(self, request_id: UUID) -> Optional[StreamState]:
        """Get state of an active stream."""
        return self._active_streams.get(request_id)
    
    def get_active_streams(self) -> list[StreamState]:
        """Get all active stream states."""
        return list(self._active_streams.values())
    
    async def cancel_stream(self, request_id: UUID) -> bool:
        """Cancel an active stream."""
        if request_id in self._active_streams:
            self._active_streams[request_id].error = "Cancelled"
            return True
        return False


class HeartbeatManager:
    """
    Manages heartbeat events for long-running streams.
    
    Prevents connection timeouts by sending periodic ping events.
    """
    
    def __init__(self, interval: float = 15.0):
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self, callback: Callable[[], Any]):
        """Start heartbeat with callback."""
        self._running = True
        
        async def heartbeat_loop():
            while self._running:
                await asyncio.sleep(self.interval)
                if self._running:
                    try:
                        await callback()
                    except Exception:
                        pass
        
        self._task = asyncio.create_task(heartbeat_loop())
    
    async def stop(self):
        """Stop heartbeat."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
```

### LangGraph Streaming Integration

```python
from langgraph.graph import StateGraph
from typing import TypedDict, Optional, AsyncIterator
from uuid import UUID

class StreamingRAGState(TypedDict):
    request_id: UUID
    query: str
    messages: list
    model: str
    sources: Optional[list]
    session_id: Optional[str]

async def streaming_generate_node(
    state: StreamingRAGState,
    stream_manager: StreamManager
) -> AsyncIterator[StreamEvent]:
    """
    LangGraph node that yields streaming events.
    
    This node integrates streaming into the LangGraph workflow,
    allowing the graph to emit SSE events during execution.
    """
    async for event in stream_manager.stream_response(
        request_id=state["request_id"],
        model=state["model"],
        messages=state["messages"],
        sources=state.get("sources"),
        session_id=state.get("session_id")
    ):
        yield event


class StreamingGraphRunner:
    """
    Runs a LangGraph workflow with streaming output.
    
    Wraps the graph execution to yield SSE events from
    streaming-enabled nodes.
    """
    
    def __init__(
        self,
        graph: StateGraph,
        stream_manager: StreamManager
    ):
        self.graph = graph
        self.stream_manager = stream_manager
        self._compiled = graph.compile()
    
    async def stream(
        self,
        initial_state: dict,
        config: Optional[dict] = None
    ) -> AsyncIterator[StreamEvent]:
        """
        Execute graph and stream results.
        
        Args:
            initial_state: Initial state for the graph
            config: Optional LangGraph config
        
        Yields:
            StreamEvent objects from streaming nodes
        """
        writer = SSEWriter()
        
        # Send start event
        yield writer.event(StreamEventType.START, {
            "request_id": str(initial_state.get("request_id", uuid4()))
        })
        
        try:
            # Run graph with streaming
            async for event in self._compiled.astream_events(
                initial_state,
                config=config or {},
                version="v2"
            ):
                # Handle different event types from LangGraph
                if event["event"] == "on_chain_start":
                    yield writer.stage(event["name"], "started")
                
                elif event["event"] == "on_chain_end":
                    yield writer.stage(event["name"], "completed")
                
                elif event["event"] == "on_llm_stream":
                    # Token from LLM
                    chunk = event.get("data", {}).get("chunk", {})
                    content = chunk.get("content", "")
                    if content:
                        yield writer.token(content)
                
                elif event["event"] == "on_tool_end":
                    # Tool completed (e.g., retrieval)
                    tool_name = event.get("name", "")
                    if "retriev" in tool_name.lower():
                        output = event.get("data", {}).get("output", {})
                        if "sources" in output:
                            yield writer.sources(output["sources"])
            
            yield writer.done()
            
        except Exception as e:
            yield writer.error(str(e))
            raise
```

### FastAPI Streaming Endpoint

```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
from uuid import uuid4

app = FastAPI()

@app.post("/query/stream")
async def stream_query(
    request: Request,
    query_request: QueryRequest,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> StreamingResponse:
    """
    Streaming RAG query endpoint.
    
    Returns a Server-Sent Events stream with progressive response.
    """
    request_id = uuid4()
    
    async def generate():
        """Generate SSE events."""
        try:
            async for event in stream_manager.stream_response(
                request_id=request_id,
                model=query_request.model or "default",
                messages=query_request.messages,
                sources=None,  # Will be populated during retrieval
                session_id=query_request.session_id
            ):
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                yield event.to_sse()
                
        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as e:
            error_event = StreamEvent(
                event=StreamEventType.ERROR,
                data={"error": str(e)}
            )
            yield error_event.to_sse()
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": str(request_id)
        }
    )


@app.get("/streams/active")
async def get_active_streams(
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> list[dict]:
    """Get information about active streams."""
    streams = stream_manager.get_active_streams()
    return [
        {
            "request_id": str(s.request_id),
            "started_at": s.started_at.isoformat(),
            "tokens_sent": s.tokens_sent,
            "last_activity": s.last_activity.isoformat()
        }
        for s in streams
    ]


@app.delete("/streams/{request_id}")
async def cancel_stream(
    request_id: UUID,
    stream_manager: StreamManager = Depends(get_stream_manager)
) -> dict:
    """Cancel an active stream."""
    cancelled = await stream_manager.cancel_stream(request_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Stream not found")
    return {"status": "cancelled"}
```

### Client-Side Integration Example

```typescript
// TypeScript/JavaScript client example

interface StreamEvent {
  id: string;
  event: string;
  data: any;
}

class RAGStreamClient {
  private eventSource: EventSource | null = null;
  private abortController: AbortController | null = null;

  async streamQuery(
    query: string,
    options: {
      onToken?: (token: string) => void;
      onMetadata?: (meta: any) => void;
      onSources?: (sources: any[]) => void;
      onDone?: (stats: any) => void;
      onError?: (error: string) => void;
    }
  ): Promise<void> {
    this.abortController = new AbortController();

    const response = await fetch('/api/query/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
      signal: this.abortController.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = this.parseSSE(buffer);
        buffer = events.remaining;

        for (const event of events.parsed) {
          this.handleEvent(event, options);
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private parseSSE(buffer: string): { parsed: StreamEvent[]; remaining: string } {
    const events: StreamEvent[] = [];
    const lines = buffer.split('\n');
    let remaining = '';
    
    let currentEvent: Partial<StreamEvent> = {};
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      
      if (line === '') {
        // Empty line = event complete
        if (currentEvent.event && currentEvent.data !== undefined) {
          events.push(currentEvent as StreamEvent);
        }
        currentEvent = {};
      } else if (line.startsWith('id: ')) {
        currentEvent.id = line.slice(4);
      } else if (line.startsWith('event: ')) {
        currentEvent.event = line.slice(7);
      } else if (line.startsWith('data: ')) {
        const data = line.slice(6);
        try {
          currentEvent.data = JSON.parse(data);
        } catch {
          currentEvent.data = data;
        }
      }
    }
    
    // Keep incomplete event in buffer
    if (currentEvent.event || currentEvent.data) {
      remaining = lines.slice(-1).join('\n');
    }
    
    return { parsed: events, remaining };
  }

  private handleEvent(event: StreamEvent, options: any) {
    switch (event.event) {
      case 'token':
        options.onToken?.(event.data);
        break;
      case 'metadata':
        options.onMetadata?.(event.data);
        break;
      case 'sources':
        options.onSources?.(event.data);
        break;
      case 'done':
        options.onDone?.(event.data);
        break;
      case 'error':
        options.onError?.(event.data.error);
        break;
    }
  }

  cancel() {
    this.abortController?.abort();
  }
}

// Usage example
const client = new RAGStreamClient();

let response = '';
await client.streamQuery('What is machine learning?', {
  onToken: (token) => {
    response += token;
    console.log('Token:', token);
  },
  onSources: (sources) => {
    console.log('Sources:', sources);
  },
  onDone: (stats) => {
    console.log('Complete!', stats);
    console.log('Full response:', response);
  },
  onError: (error) => {
    console.error('Error:', error);
  },
});
```

## Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import asyncio

@pytest.fixture
def stream_config():
    return StreamConfig(
        chunk_size=1,
        heartbeat_interval=30.0
    )

@pytest.fixture
def stream_manager(stream_config):
    gateway = AsyncMock()
    return StreamManager(stream_config, gateway)

@pytest.fixture
def sse_writer(stream_config):
    return SSEWriter(stream_config)

# SSE Formatting Tests
def test_stream_event_to_sse():
    """Test SSE message formatting."""
    event = StreamEvent(
        id="test-id",
        event=StreamEventType.TOKEN,
        data="Hello"
    )
    
    sse = event.to_sse()
    
    assert "id: test-id" in sse
    assert "event: token" in sse
    assert "data: Hello" in sse
    assert sse.endswith("\n\n")

def test_stream_event_json_data():
    """Test SSE formatting with JSON data."""
    event = StreamEvent(
        event=StreamEventType.METADATA,
        data={"model": "llama", "tokens": 100}
    )
    
    sse = event.to_sse()
    
    assert "event: metadata" in sse
    assert '"model": "llama"' in sse

def test_stream_event_multiline_data():
    """Test SSE formatting with multiline content."""
    event = StreamEvent(
        event=StreamEventType.CONTENT,
        data="Line 1\nLine 2\nLine 3"
    )
    
    sse = event.to_sse()
    
    assert sse.count("data: ") == 3

# SSEWriter Tests
def test_sse_writer_token(sse_writer):
    """Test token event creation."""
    event = sse_writer.token("Hello")
    
    assert event.event == StreamEventType.TOKEN
    assert event.data == "Hello"

def test_sse_writer_metadata(sse_writer):
    """Test metadata event creation."""
    meta = StreamMetadata(
        request_id=uuid4(),
        model="test-model"
    )
    event = sse_writer.metadata(meta)
    
    assert event.event == StreamEventType.METADATA
    assert event.data["model"] == "test-model"

def test_sse_writer_sources(sse_writer):
    """Test sources event creation."""
    sources = [
        SourceCitation(id="1", source="doc1.pdf", score=0.9),
        SourceCitation(id="2", source="doc2.pdf", score=0.8)
    ]
    event = sse_writer.sources(sources)
    
    assert event.event == StreamEventType.SOURCES
    assert len(event.data) == 2

def test_sse_writer_error(sse_writer):
    """Test error event creation."""
    event = sse_writer.error("Something went wrong", recoverable=True)
    
    assert event.event == StreamEventType.ERROR
    assert event.data["error"] == "Something went wrong"
    assert event.data["recoverable"] is True

def test_sse_writer_done(sse_writer):
    """Test done event creation."""
    event = sse_writer.done({"tokens": 100, "elapsed_ms": 500})
    
    assert event.event == StreamEventType.DONE
    assert event.data["tokens"] == 100

# StreamManager Tests
@pytest.mark.asyncio
async def test_stream_manager_basic_flow(stream_manager):
    """Test basic streaming flow."""
    request_id = uuid4()
    
    # Mock gateway streaming
    async def mock_stream(*args, **kwargs):
        for i, token in enumerate(["Hello", " ", "World"]):
            yield MagicMock(choices=[{"delta": {"content": token}}])
    
    stream_manager.gateway.chat_completion_stream = mock_stream
    
    events = []
    async for event in stream_manager.stream_response(
        request_id=request_id,
        model="test-model",
        messages=[{"role": "user", "content": "Hi"}]
    ):
        events.append(event)
    
    # Should have start, metadata, stage, tokens, stage, done
    event_types = [e.event for e in events]
    assert StreamEventType.START in event_types
    assert StreamEventType.TOKEN in event_types
    assert StreamEventType.DONE in event_types

@pytest.mark.asyncio
async def test_stream_manager_with_sources(stream_manager):
    """Test streaming with source citations."""
    request_id = uuid4()
    sources = [
        SourceCitation(id="1", source="doc.pdf", score=0.9)
    ]
    
    async def mock_stream(*args, **kwargs):
        yield MagicMock(choices=[{"delta": {"content": "Answer"}}])
    
    stream_manager.gateway.chat_completion_stream = mock_stream
    
    events = []
    async for event in stream_manager.stream_response(
        request_id=request_id,
        model="test-model",
        messages=[],
        sources=sources
    ):
        events.append(event)
    
    source_events = [e for e in events if e.event == StreamEventType.SOURCES]
    assert len(source_events) == 1

@pytest.mark.asyncio
async def test_stream_manager_error_handling(stream_manager):
    """Test error handling in stream."""
    request_id = uuid4()
    
    async def mock_stream_error(*args, **kwargs):
        yield MagicMock(choices=[{"delta": {"content": "Start"}}])
        raise Exception("Stream error")
    
    stream_manager.gateway.chat_completion_stream = mock_stream_error
    
    events = []
    with pytest.raises(Exception):
        async for event in stream_manager.stream_response(
            request_id=request_id,
            model="test-model",
            messages=[]
        ):
            events.append(event)
    
    error_events = [e for e in events if e.event == StreamEventType.ERROR]
    assert len(error_events) == 1

@pytest.mark.asyncio
async def test_stream_state_tracking(stream_manager):
    """Test that stream state is tracked."""
    request_id = uuid4()
    
    async def mock_stream(*args, **kwargs):
        for token in ["A", "B", "C"]:
            yield MagicMock(choices=[{"delta": {"content": token}}])
    
    stream_manager.gateway.chat_completion_stream = mock_stream
    
    # Start streaming in background
    events = []
    async for event in stream_manager.stream_response(
        request_id=request_id,
        model="test-model",
        messages=[]
    ):
        events.append(event)
    
    # State should be cleaned up after completion
    assert stream_manager.get_stream_state(request_id) is None

@pytest.mark.asyncio
async def test_stream_manager_token_callback(stream_manager):
    """Test token callback is called."""
    request_id = uuid4()
    tokens_received = []
    
    async def mock_stream(*args, **kwargs):
        for token in ["Hello", " ", "World"]:
            yield MagicMock(choices=[{"delta": {"content": token}}])
    
    stream_manager.gateway.chat_completion_stream = mock_stream
    
    async for event in stream_manager.stream_response(
        request_id=request_id,
        model="test-model",
        messages=[],
        on_token=lambda t: tokens_received.append(t)
    ):
        pass
    
    assert tokens_received == ["Hello", " ", "World"]

# Heartbeat Tests
@pytest.mark.asyncio
async def test_heartbeat_manager():
    """Test heartbeat manager sends periodic pings."""
    heartbeats = []
    
    async def on_heartbeat():
        heartbeats.append(True)
    
    manager = HeartbeatManager(interval=0.1)
    await manager.start(on_heartbeat)
    
    await asyncio.sleep(0.35)
    await manager.stop()
    
    # Should have sent ~3 heartbeats
    assert len(heartbeats) >= 2

@pytest.mark.asyncio
async def test_heartbeat_manager_stop():
    """Test heartbeat stops cleanly."""
    manager = HeartbeatManager(interval=0.1)
    await manager.start(lambda: None)
    await manager.stop()
    
    assert not manager._running

# Integration-style Tests
@pytest.mark.asyncio
async def test_full_streaming_pipeline(stream_config):
    """Test complete streaming with all components."""
    gateway = AsyncMock()
    manager = StreamManager(stream_config, gateway)
    
    async def mock_stream(*args, **kwargs):
        for token in list("Test response"):
            await asyncio.sleep(0.01)  # Simulate latency
            yield MagicMock(choices=[{"delta": {"content": token}}])
    
    gateway.chat_completion_stream = mock_stream
    
    sources = [
        SourceCitation(id="1", source="source.pdf", score=0.95)
    ]
    
    all_events = []
    full_response = ""
    
    async for event in manager.stream_response(
        request_id=uuid4(),
        model="test-model",
        messages=[{"role": "user", "content": "Test"}],
        sources=sources
    ):
        all_events.append(event)
        if event.event == StreamEventType.TOKEN:
            full_response += event.data
    
    assert full_response == "Test response"
    assert any(e.event == StreamEventType.SOURCES for e in all_events)
    assert any(e.event == StreamEventType.DONE for e in all_events)
```

## Dependencies

- `fastapi>=0.104.0`
- `starlette>=0.27.0`
- `pydantic>=2.0.0`

## Definition of Done

- [ ] SSE response class properly formats events
- [ ] StreamEvent supports all event types (token, metadata, sources, done, error)
- [ ] Multi-line content formatted correctly
- [ ] StreamManager coordinates LLM streaming
- [ ] Metadata event sent at stream start
- [ ] Sources event includes all retrieved citations
- [ ] Done event includes timing statistics
- [ ] Error events include error details
- [ ] Heartbeat keeps connection alive during long operations
- [ ] Stream state tracking works correctly
- [ ] Stream cancellation supported
- [ ] Client disconnection handled gracefully
- [ ] LangGraph integration yields streaming events
- [ ] FastAPI endpoint returns proper SSE headers
- [ ] Connection timeout handling works
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
