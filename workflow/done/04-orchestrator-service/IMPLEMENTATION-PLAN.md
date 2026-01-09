# Orchestrator Service - Multi-Agent Implementation Plan

> **Epic:** Orchestrator Service
> **Total User Stories:** 11
> **Approach:** Wave-based parallel execution with integration checkpoints
> **Created:** 2026-01-09

---

## Executive Summary

This plan organizes the Orchestrator Service implementation into 4 waves, enabling parallel agent execution where dependencies allow. Each wave concludes with an integration checkpoint to verify components work together before proceeding.

**Key Metrics:**
- Maximum parallel agents per wave: 4 (Wave 4)
- Critical path: Setup → Wave 1 → Wave 2 → Wave 3 → Wave 4
- Integration checkpoints: 4

---

## Wave Structure Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SETUP: Shared infrastructure, config, requirements, test fixtures           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────┐ ┌────────────────────────────────┐
│ WAVE 1A: Model Gateway         │ │ WAVE 1B: Conversation Memory   │
│ US-4.4 (Agent A)               │ │ US-4.7 (Agent B)               │
└────────────────────────────────┘ └────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │ Integration Checkpoint 1
                        └───────────┬───────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────────┐
│ WAVE 2: LangGraph Workflow (Agent C) → Prompt Builder (Agent D)             │
│ US-4.1 → US-4.3 (sequential)                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │ Integration Checkpoint 2
                        └───────────┬───────────┘
                                    │
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ WAVE 3A: Query Router│ │ WAVE 3B: Guardrails  │ │ WAVE 3C: Streaming   │
│ US-4.2 (Agent E)     │ │ US-4.5 (Agent F)     │ │ US-4.6 (Agent G)     │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │ Integration Checkpoint 3
                        └───────────┬───────────┘
                                    │
┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ WAVE 4A: API   │ │ WAVE 4B:       │ │ WAVE 4C:       │ │ WAVE 4D:       │
│ US-4.8 (H)     │ │ Resilience (I) │ │ Persistence (J)│ │ Contract (K)   │
│                │ │ US-4.9         │ │ US-4.10        │ │ US-4.11        │
└────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │ Final Integration
                        └───────────────────────┘
```

---

## Pre-Wave Setup

**Objective:** Create shared infrastructure before any wave begins.

### Directory Structure

```
services/orchestrator/
├── __init__.py
├── config.py                    # Pydantic settings
├── run.py                       # Entry point
├── requirements.txt             # All dependencies
├── Dockerfile                   # (exists)
├── api/
│   ├── __init__.py
│   ├── app.py                   # FastAPI application
│   ├── routes/
│   │   └── __init__.py
│   ├── middleware/
│   │   └── __init__.py
│   ├── models/
│   │   └── __init__.py
│   └── dependencies.py
├── workflow/
│   ├── __init__.py
│   ├── graph.py                 # LangGraph definition
│   ├── state.py                 # State models
│   └── nodes/
│       └── __init__.py
├── routing/
│   ├── __init__.py
│   ├── router.py
│   └── classifiers.py
├── prompts/
│   ├── __init__.py
│   ├── builder.py
│   ├── templates.py
│   └── context.py
├── gateway/
│   ├── __init__.py
│   ├── client.py
│   ├── streaming.py
│   └── models.py
├── guardrails/
│   ├── __init__.py
│   ├── input.py
│   ├── output.py
│   └── detection.py
├── memory/
│   ├── __init__.py
│   ├── session.py
│   ├── store.py
│   ├── summarizer.py
│   ├── models.py
│   └── persistence.py
├── streaming/
│   ├── __init__.py
│   ├── models.py
│   └── manager.py
├── resilience/
│   ├── __init__.py
│   ├── circuit_breaker.py
│   ├── fallbacks.py
│   └── degradation.py
└── tests/
    ├── __init__.py
    ├── conftest.py              # Shared fixtures
    ├── fixtures/
    │   └── __init__.py
    ├── gateway/
    ├── memory/
    ├── workflow/
    ├── routing/
    ├── prompts/
    ├── guardrails/
    ├── streaming/
    ├── resilience/
    └── api/
```

### requirements.txt

```txt
# Framework
fastapi>=0.104.0
uvicorn>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0

# Orchestration
langgraph>=0.0.40
langchain-core>=0.1.0

# LLM Client
httpx>=0.25.0
openai>=1.6.0

# Storage
redis>=5.0.0
asyncpg>=0.29.0
sqlalchemy>=2.0.0

# Streaming
sse-starlette>=1.8.0

# Prompts
jinja2>=3.1.0

# Guardrails
presidio-analyzer>=2.2.0
presidio-anonymizer>=2.2.0

# Utilities
tenacity>=8.2.0
tiktoken>=0.5.0

# Observability
opentelemetry-api>=1.21.0
opentelemetry-sdk>=1.21.0
opentelemetry-instrumentation-fastapi>=0.42b0
opentelemetry-exporter-otlp>=1.21.0
prometheus-client>=0.19.0
structlog>=23.2.0

# Auth
python-jose[cryptography]>=3.3.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
httpx>=0.25.0
```

### config.py (Skeleton)

```python
from pydantic_settings import BaseSettings
from typing import Optional

class OrchestratorConfig(BaseSettings):
    # Service
    service_name: str = "orchestrator-service"
    service_port: int = 8003
    debug: bool = False

    # Retrieval Service
    retrieval_url: str = "http://localhost:8002"
    retrieval_timeout: float = 10.0

    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"
    default_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    fallback_model: str = "meta-llama/Llama-3.1-70B-Instruct"
    max_tokens: int = 1024
    temperature: float = 0.7

    # Redis
    redis_url: str = "redis://localhost:6379"
    session_ttl: int = 3600
    max_history_length: int = 20

    # Postgres
    database_url: str = "postgresql+asyncpg://raguser:ragpassword@localhost:5432/ragpipeline"

    # Guardrails
    enable_input_guardrails: bool = True
    enable_output_guardrails: bool = True
    max_input_length: int = 4000

    # Streaming
    stream_timeout: float = 60.0

    # JWT
    jwt_secret: str = "secret"
    jwt_algorithm: str = "HS256"

    class Config:
        env_prefix = "ORCHESTRATOR_"
```

### Setup Tasks

| Task | Description |
|------|-------------|
| Create directory structure | All folders and `__init__.py` files |
| Write `requirements.txt` | All dependencies listed above |
| Write `config.py` | Pydantic settings class |
| Write `tests/conftest.py` | Mock Redis, mock LLM fixtures |
| Write `run.py` | Basic uvicorn entry point |

---

## Wave 1: Foundation Layer

### Agent A: Model Gateway (US-4.4)

**Scope:** `gateway/` module

**Files to Create:**
- `gateway/models.py` - Request/response Pydantic models
- `gateway/client.py` - Async HTTP client for vLLM/Ollama
- `gateway/streaming.py` - SSE stream consumer
- `gateway/config.py` - Model configurations
- `tests/gateway/test_client.py`
- `tests/gateway/test_streaming.py`

**Key Implementation Details:**
- Use `httpx.AsyncClient` for HTTP calls
- OpenAI-compatible API format for vLLM
- Retry logic with `tenacity` (exponential backoff)
- Health check endpoint per model
- Token counting with `tiktoken`

**Exit Criteria:**
- [ ] `ChatCompletionRequest` / `ChatCompletionResponse` models defined
- [ ] `ModelGateway.chat_completion()` works with mock vLLM
- [ ] `ModelGateway.chat_completion_stream()` yields tokens
- [ ] Health check returns model availability
- [ ] Unit tests pass: `pytest tests/gateway/ -v`

**Agent Prompt:**
```
Implement the Model Gateway (US-4.4) for the Orchestrator Service.

Create the gateway/ module with:
1. models.py - Pydantic models for ChatCompletionRequest, ChatCompletionResponse,
   ChatMessage, ModelConfig matching OpenAI API format
2. client.py - ModelGateway class with:
   - async chat_completion(request) -> response
   - async chat_completion_stream(request) -> AsyncGenerator[token]
   - async health_check() -> dict of model statuses
   - Retry logic using tenacity (3 retries, exponential backoff)
   - Configurable timeout per request
3. streaming.py - SSE stream parsing for vLLM responses
4. Tests with mocked httpx responses

Reference: workflow/refined/04-orchestrator-service/US-4.4-model-gateway.md
Config: Use OrchestratorConfig from config.py for URLs/timeouts
Pattern: Follow services/retrieval/ code style
```

---

### Agent B: Conversation Memory (US-4.7)

**Scope:** `memory/` module

**Files to Create:**
- `memory/models.py` - Message, ConversationSession, MemoryConfig
- `memory/store.py` - RedisSessionStore
- `memory/session.py` - SessionManager
- `memory/summarizer.py` - HistorySummarizer
- `tests/memory/test_store.py`
- `tests/memory/test_session.py`

**Key Implementation Details:**
- Use `redis.asyncio` for async Redis operations
- JSON serialization for session data
- TTL-based expiration
- Token counting for history truncation
- LLM-based summarization (optional, with fallback)

**Exit Criteria:**
- [ ] `ConversationSession` model with messages list
- [ ] `RedisSessionStore` CRUD operations work
- [ ] `SessionManager.add_message()` tracks tokens
- [ ] `SessionManager.get_history()` respects token limits
- [ ] Session TTL expiration works
- [ ] Unit tests pass: `pytest tests/memory/ -v`

**Agent Prompt:**
```
Implement Conversation Memory (US-4.7) for the Orchestrator Service.

Create the memory/ module with:
1. models.py - Message, MessageRole enum, ConversationSession, MemoryConfig, SessionStats
2. store.py - RedisSessionStore class with:
   - async create_session() / get_session() / update_session() / delete_session()
   - User session tracking and limits
   - TTL management
3. session.py - SessionManager class with:
   - async add_message() with token counting
   - async get_history() with token limit truncation
   - async get_history_for_llm() returning list[dict]
4. summarizer.py - HistorySummarizer with LLM and fallback modes
5. Tests with mocked Redis

Reference: workflow/refined/04-orchestrator-service/US-4.7-conversation-memory.md
Config: Use OrchestratorConfig for Redis URL and session settings
```

---

### Integration Checkpoint 1

**Run after Wave 1 completes:**

```bash
cd services/orchestrator

# Run all Wave 1 tests
pytest tests/gateway/ tests/memory/ -v

# Verify imports work
python -c "from gateway.client import ModelGateway; from memory.session import SessionManager; print('OK')"
```

**Manual Verification:**
1. Start Redis: `docker-compose up -d redis`
2. Create session, add messages, verify TTL works
3. Mock LLM call through gateway

---

## Wave 2: Core Workflow

### Agent C: LangGraph Workflow (US-4.1)

**Scope:** `workflow/` module

**Files to Create:**
- `workflow/state.py` - RAGState TypedDict, node input/output types
- `workflow/graph.py` - LangGraph StateGraph definition
- `workflow/nodes/__init__.py`
- `workflow/nodes/router.py` - Routing node (stub)
- `workflow/nodes/retriever.py` - Retrieval node (stub)
- `workflow/nodes/generator.py` - Generation node (stub)
- `workflow/nodes/guardrails.py` - Guardrail nodes (stub)
- `tests/workflow/test_graph.py`
- `tests/workflow/test_state.py`

**Key Implementation Details:**
- TypedDict for state (not Pydantic - LangGraph requirement)
- Conditional edges for routing decisions
- Node functions are async
- Error state handling

**State Definition:**
```python
class RAGState(TypedDict):
    # Input
    request_id: str
    query: str
    session_id: Optional[str]
    user_id: Optional[str]
    tenant_id: Optional[str]

    # Routing
    strategy: str  # "simple", "complex", "no_retrieval"

    # Retrieval
    documents: List[dict]
    context: str

    # Generation
    messages: List[dict]
    response: Optional[str]

    # Metadata
    model_used: Optional[str]
    usage: Optional[dict]
    timing: dict

    # Error handling
    error: Optional[str]
    fallbacks_used: List[str]
```

**Exit Criteria:**
- [ ] `RAGState` TypedDict defined with all fields
- [ ] `build_rag_workflow()` returns compiled StateGraph
- [ ] Graph has nodes: input_validation, routing, retrieval, prompt_building, generation, output_validation
- [ ] Conditional edges work for routing decisions
- [ ] Graph executes with mocked nodes
- [ ] Unit tests pass: `pytest tests/workflow/ -v`

**Agent Prompt:**
```
Implement the LangGraph Workflow (US-4.1) for the Orchestrator Service.

Create the workflow/ module with:
1. state.py - RAGState TypedDict with all fields for the RAG pipeline
2. graph.py - build_rag_workflow() function that:
   - Creates StateGraph with RAGState
   - Adds nodes: input_validation, routing, retrieval, prompt_building, generation, output_validation
   - Adds conditional edges for routing (simple/complex/no_retrieval paths)
   - Sets entry and finish points
   - Returns compiled graph
3. nodes/ with stub implementations that pass state through
4. Tests verifying graph compiles and executes

Reference: workflow/refined/04-orchestrator-service/US-4.1-langgraph-workflow.md
Important: Use TypedDict not Pydantic for state (LangGraph requirement)
```

---

### Agent D: Prompt Builder (US-4.3)

**Scope:** `prompts/` module

**Depends on:** Agent C (needs RAGState definition)

**Files to Create:**
- `prompts/templates.py` - Jinja2 template strings
- `prompts/builder.py` - PromptBuilder class
- `prompts/context.py` - Context formatting utilities
- `tests/prompts/test_builder.py`
- `tests/prompts/test_templates.py`

**Key Implementation Details:**
- Jinja2 for template rendering
- Multiple prompt templates (RAG, no-context, follow-up)
- Context truncation to fit token limits
- Source citation formatting

**Exit Criteria:**
- [ ] RAG prompt template with system, context, query sections
- [ ] `PromptBuilder.build()` returns formatted messages list
- [ ] Context truncation respects token limits
- [ ] Citation formatting works
- [ ] Unit tests pass: `pytest tests/prompts/ -v`

**Agent Prompt:**
```
Implement the Prompt Builder (US-4.3) for the Orchestrator Service.

Create the prompts/ module with:
1. templates.py - Jinja2 template strings for:
   - RAG_SYSTEM_PROMPT (with context)
   - NO_CONTEXT_PROMPT (direct answer)
   - FOLLOW_UP_PROMPT (conversation continuation)
2. builder.py - PromptBuilder class with:
   - build(query, context, history, strategy) -> list[dict] messages
   - Token counting and context truncation
   - Citation instruction injection
3. context.py - format_context(documents) -> str, format_citations(documents) -> str
4. Tests with various input combinations

Reference: workflow/refined/04-orchestrator-service/US-4.3-prompt-builder.md
Import RAGState from workflow.state for type hints
```

---

### Integration Checkpoint 2

**Run after Wave 2 completes:**

```bash
cd services/orchestrator

# Run Wave 2 tests
pytest tests/workflow/ tests/prompts/ -v

# Verify workflow builds
python -c "
from workflow.graph import build_rag_workflow
workflow = build_rag_workflow()
print(f'Workflow nodes: {list(workflow.nodes.keys())}')
print('OK')
"

# Test prompt building
python -c "
from prompts.builder import PromptBuilder
builder = PromptBuilder()
messages = builder.build('What is Python?', 'Python is a programming language.', [], 'simple')
print(f'Messages: {len(messages)}')
print('OK')
"
```

---

## Wave 3: Processing Components

### Agent E: Query Router (US-4.2)

**Scope:** `routing/` module

**Files to Create:**
- `routing/classifiers.py` - Intent and complexity classifiers
- `routing/router.py` - QueryRouter class
- `routing/models.py` - RoutingResult, QueryIntent enums
- `tests/routing/test_router.py`
- `tests/routing/test_classifiers.py`

**Key Implementation Details:**
- Keyword-based classification (fast path)
- Optional LLM-based classification (complex queries)
- Query complexity scoring
- Strategy selection: simple, complex, no_retrieval

**Exit Criteria:**
- [ ] `QueryRouter.route()` returns strategy and confidence
- [ ] Simple factual queries → "simple"
- [ ] Complex multi-part queries → "complex"
- [ ] Greetings/chitchat → "no_retrieval"
- [ ] Unit tests pass: `pytest tests/routing/ -v`

**Agent Prompt:**
```
Implement the Query Router (US-4.2) for the Orchestrator Service.

Create the routing/ module with:
1. models.py - QueryIntent enum, RoutingStrategy enum, RoutingResult model
2. classifiers.py -
   - KeywordClassifier for fast pattern matching
   - ComplexityScorer for query complexity (0-1 score)
3. router.py - QueryRouter class with:
   - async route(query, history) -> RoutingResult
   - Strategy selection based on intent + complexity
   - Configurable thresholds
4. Tests covering various query types

Reference: workflow/refined/04-orchestrator-service/US-4.2-query-router.md
Strategies: "simple" (single retrieval), "complex" (multi-step), "no_retrieval" (direct LLM)
```

---

### Agent F: Guardrails (US-4.5)

**Scope:** `guardrails/` module

**Files to Create:**
- `guardrails/models.py` - GuardrailResult, Violation models
- `guardrails/input.py` - InputGuardrail class
- `guardrails/output.py` - OutputGuardrail class
- `guardrails/detection.py` - PII detection, injection detection
- `guardrails/pipeline.py` - GuardrailPipeline orchestrator
- `tests/guardrails/test_input.py`
- `tests/guardrails/test_output.py`

**Key Implementation Details:**
- Presidio for PII detection
- Regex patterns for prompt injection
- Content length validation
- Output hallucination detection (optional)
- Configurable block vs warn behavior

**Exit Criteria:**
- [ ] `InputGuardrail.check()` detects PII, injection attempts
- [ ] `OutputGuardrail.check()` filters harmful content
- [ ] `GuardrailPipeline` runs all checks
- [ ] Results include violation details
- [ ] Unit tests pass: `pytest tests/guardrails/ -v`

**Agent Prompt:**
```
Implement Guardrails (US-4.5) for the Orchestrator Service.

Create the guardrails/ module with:
1. models.py - GuardrailResult, Violation, ViolationType enum
2. input.py - InputGuardrail class:
   - Length validation
   - Prompt injection detection (regex patterns)
   - PII detection using Presidio
3. output.py - OutputGuardrail class:
   - Harmful content filtering
   - Response length limits
4. detection.py - Utility functions for pattern matching
5. pipeline.py - GuardrailPipeline combining input + output guards
6. Tests for each guardrail type

Reference: workflow/refined/04-orchestrator-service/US-4.5-guardrails.md
Use presidio-analyzer for PII detection
```

---

### Agent G: Streaming Support (US-4.6)

**Scope:** `streaming/` module

**Files to Create:**
- `streaming/models.py` - StreamEvent, StreamEventType enum
- `streaming/manager.py` - StreamManager class
- `streaming/buffer.py` - Token buffer for batching
- `tests/streaming/test_manager.py`
- `tests/streaming/test_events.py`

**Key Implementation Details:**
- SSE event format: `event: type\ndata: json\n\n`
- Event types: start, delta, citations, done, error
- Token buffering for smoother streaming
- Timeout handling

**Exit Criteria:**
- [ ] `StreamEvent.to_sse()` produces valid SSE format
- [ ] `StreamManager.stream_response()` yields events in order
- [ ] Start event includes metadata
- [ ] Delta events contain tokens
- [ ] Done event includes usage stats
- [ ] Unit tests pass: `pytest tests/streaming/ -v`

**Agent Prompt:**
```
Implement Streaming Support (US-4.6) for the Orchestrator Service.

Create the streaming/ module with:
1. models.py - StreamEvent, StreamEventType enum (start, delta, citations, done, error)
   - to_sse() method producing "event: type\ndata: json\n\n" format
2. manager.py - StreamManager class:
   - async stream_response(request_id, model, messages, session_id) -> AsyncGenerator[StreamEvent]
   - Emits: start → delta* → citations → done
   - Error handling with error event
3. buffer.py - TokenBuffer for batching small tokens
4. Tests verifying event order and format

Reference: workflow/refined/04-orchestrator-service/US-4.6-streaming-support.md
SSE format must match architecture contract
```

---

### Integration Checkpoint 3

**Run after Wave 3 completes:**

```bash
cd services/orchestrator

# Run Wave 3 tests
pytest tests/routing/ tests/guardrails/ tests/streaming/ -v

# Test routing
python -c "
from routing.router import QueryRouter
router = QueryRouter()
import asyncio
result = asyncio.run(router.route('What is the capital of France?', []))
print(f'Strategy: {result.strategy}')
"

# Test guardrails
python -c "
from guardrails.pipeline import GuardrailPipeline
pipeline = GuardrailPipeline()
import asyncio
result = asyncio.run(pipeline.check_input('Hello, how are you?'))
print(f'Passed: {result.passed}')
"

# Test streaming format
python -c "
from streaming.models import StreamEvent, StreamEventType
event = StreamEvent(event=StreamEventType.START, data={'request_id': 'test'})
print(event.to_sse())
"
```

---

## Wave 4: Integration & API Layer

### Agent H: Orchestrator API (US-4.8)

**Scope:** `api/` module

**Files to Create:**
- `api/app.py` - FastAPI application factory
- `api/routes/query.py` - Query endpoints
- `api/routes/sessions.py` - Session endpoints
- `api/routes/health.py` - Health endpoints
- `api/models/requests.py` - Request models
- `api/models/responses.py` - Response models
- `api/middleware/logging.py` - Request logging
- `api/middleware/tracing.py` - OpenTelemetry
- `api/dependencies.py` - Dependency injection
- `tests/api/test_query.py`
- `tests/api/test_sessions.py`
- `tests/api/test_health.py`

**Key Implementation Details:**
- Lifespan handler for startup/shutdown
- Dependency injection for services
- CORS middleware
- OpenTelemetry instrumentation
- Structured error responses

**Endpoints:**
- `POST /api/v1/query` - Synchronous RAG query
- `POST /api/v1/query/stream` - Streaming RAG query (SSE)
- `POST /api/v1/feedback` - Submit feedback
- `POST /api/v1/sessions` - Create session
- `GET /api/v1/sessions/{id}` - Get session
- `GET /api/v1/sessions/{id}/history` - Get history
- `DELETE /api/v1/sessions/{id}` - Delete session
- `POST /api/v1/sessions/{id}/clear` - Clear session
- `GET /health` - Detailed health
- `GET /health/live` - Liveness
- `GET /health/ready` - Readiness

**Exit Criteria:**
- [ ] All endpoints respond with correct status codes
- [ ] Request validation works
- [ ] Streaming endpoint returns SSE
- [ ] Health checks verify dependencies
- [ ] OpenTelemetry traces created
- [ ] Unit tests pass: `pytest tests/api/ -v`

**Agent Prompt:**
```
Implement the Orchestrator API (US-4.8) for the Orchestrator Service.

Create the api/ module with:
1. app.py - create_app() factory with lifespan, middleware, routers
2. routes/query.py - POST /api/v1/query, POST /api/v1/query/stream, POST /api/v1/feedback
3. routes/sessions.py - Session CRUD endpoints
4. routes/health.py - /health, /health/live, /health/ready
5. models/requests.py - QueryRequest, StreamQueryRequest, FeedbackRequest
6. models/responses.py - QueryResponse, SessionResponse, HealthResponse, ErrorResponse
7. middleware/logging.py - RequestLoggingMiddleware
8. middleware/tracing.py - TracingMiddleware with OpenTelemetry
9. dependencies.py - get_workflow, get_session_manager, etc.
10. Tests using TestClient with mocked services

Reference: workflow/refined/04-orchestrator-service/US-4.8-orchestrator-api.md
Wire up: workflow, session_manager, model_gateway, guardrail_pipeline, stream_manager
```

---

### Agent I: Graceful Degradation (US-4.9)

**Scope:** `resilience/` module

**Files to Create:**
- `resilience/circuit_breaker.py` - CircuitBreaker class
- `resilience/fallbacks.py` - FallbackHandlers class
- `resilience/degradation.py` - DegradationManager class
- `resilience/config.py` - ResilienceConfig
- `tests/resilience/test_circuit_breaker.py`
- `tests/resilience/test_fallbacks.py`

**Key Implementation Details:**
- Circuit breaker states: closed, open, half-open
- Configurable failure thresholds
- Fallback strategies per service
- Degradation level tracking

**Exit Criteria:**
- [ ] Circuit breaker opens after N failures
- [ ] Circuit breaker recovers after timeout
- [ ] Fallback handlers return cached/default responses
- [ ] Degradation manager tracks system state
- [ ] Unit tests pass: `pytest tests/resilience/ -v`

**Agent Prompt:**
```
Implement Graceful Degradation (US-4.9) for the Orchestrator Service.

Create the resilience/ module with:
1. config.py - CircuitBreakerConfig, FallbackConfig, ResilienceConfig
2. circuit_breaker.py - CircuitBreaker class:
   - States: CLOSED, OPEN, HALF_OPEN
   - async call(func, *args, **kwargs) with fallback
   - Configurable thresholds and timeouts
3. fallbacks.py - FallbackHandlers:
   - embedding_fallback, retrieval_fallback, reranker_fallback, llm_fallback
4. degradation.py - DegradationManager:
   - Track service health
   - Calculate degradation level (NORMAL, DEGRADED, MINIMAL)
5. Tests for circuit breaker state transitions and fallback invocation

Reference: workflow/refined/04-orchestrator-service/US-4.9-graceful-degradation.md
```

---

### Agent J: Conversation Persistence (US-4.10)

**Scope:** Extend `memory/` + database migrations

**Files to Create/Modify:**
- `memory/persistence.py` - PostgresConversationStore
- `memory/models.py` - Add SQLAlchemy models
- `services/shared/database/migrations/versions/xxx_add_conversations.py`
- `tests/memory/test_conversation_persistence.py`

**Key Implementation Details:**
- Write-through: Redis + Postgres
- Postgres as source of truth
- Cache miss recovery from Postgres
- JSONB for citations

**Database Schema:**
```sql
CREATE TABLE conversations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);

CREATE TABLE messages (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    citations JSONB,
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Exit Criteria:**
- [ ] Alembic migration creates tables
- [ ] Messages persist to Postgres on creation
- [ ] Redis cache stays in sync
- [ ] History reloads from Postgres after Redis flush
- [ ] Unit tests pass: `pytest tests/memory/test_conversation_persistence.py -v`

**Agent Prompt:**
```
Implement Conversation Persistence (US-4.10) for the Orchestrator Service.

Extend the memory/ module with:
1. persistence.py - PostgresConversationStore:
   - async save_conversation(session)
   - async save_message(session_id, message)
   - async load_conversation(session_id) -> ConversationSession
   - Write-through pattern: save to both Redis and Postgres
2. Update session.py to use persistence layer
3. Create Alembic migration in services/shared/database/migrations/versions/
   - conversations table (id, tenant_id, user_id, created_at, updated_at, metadata)
   - messages table (id, conversation_id, role, content, citations JSONB, token_count, created_at)
4. Tests covering:
   - Create conversation + messages
   - Redis flush recovery
   - OTEL span includes conversation_id

Reference: workflow/refined/04-orchestrator-service/US-4.10-conversation-persistence.md
Use existing asyncpg patterns from services/shared/
```

---

### Agent K: Streaming Contract Validation (US-4.11)

**Scope:** Test suite + SSE validation

**Files to Create:**
- `tests/api/test_streaming_contract.py` - Contract tests
- `streaming/validation.py` - Event validation utilities
- Update `api/routes/query.py` if needed

**Key Implementation Details:**
- Assert event order: start → delta* → citations → done
- Validate payload fields match architecture spec
- Measure and log TTFT
- Prometheus metric for TTFT

**Exit Criteria:**
- [ ] Integration test verifies event order
- [ ] All payload fields present per architecture.md
- [ ] TTFT logged and metric exported
- [ ] Guardrail retry doesn't break stream
- [ ] Tests pass: `pytest tests/api/test_streaming_contract.py -v`

**Agent Prompt:**
```
Implement Streaming Contract Validation (US-4.11) for the Orchestrator Service.

Create/update:
1. tests/api/test_streaming_contract.py:
   - Test event order: start → delta* → citations → done
   - Validate each event payload matches architecture contract
   - Test error event on guardrail failure
   - Test stream recovery on retries
2. streaming/validation.py - validate_event_sequence(events) -> bool
3. Add TTFT measurement:
   - Log TTFT in stream_manager
   - Export prometheus metric: orchestrator_ttft_seconds
4. Update OpenAPI docs to include streaming contract examples

Reference: workflow/refined/04-orchestrator-service/US-4.11-streaming-contract-validation.md
Reference: docs/architecture.md for SSE contract specification
TTFT target: <500ms
```

---

### Final Integration Checkpoint

**Run after Wave 4 completes:**

```bash
cd services/orchestrator

# Run all tests
pytest -v --cov=. --cov-report=term-missing

# Run mypy
mypy . --ignore-missing-imports

# Run database migrations
cd ../shared/database/migrations
alembic upgrade head
cd ../../../orchestrator

# Start service and verify
python run.py &
sleep 5

# Health check
curl http://localhost:8003/health | jq

# Test query endpoint
curl -X POST http://localhost:8003/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is Python?"}' | jq

# Test streaming
curl -N http://localhost:8003/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain machine learning"}'

# Cleanup
pkill -f "python run.py"
```

---

## Agent Dispatch Commands

### Setup Phase
```
Task tool call:
- subagent_type: general-purpose
- prompt: "Set up Orchestrator Service scaffolding per IMPLEMENTATION-PLAN.md Setup section"
- run_in_background: false
```

### Wave 1 (Parallel)
```
Task tool calls (parallel):
- Agent A: subagent_type: general-purpose, prompt: "Implement Model Gateway (US-4.4)...", run_in_background: true
- Agent B: subagent_type: general-purpose, prompt: "Implement Conversation Memory (US-4.7)...", run_in_background: true
```

### Wave 2 (Sequential)
```
Task tool calls (sequential):
- Agent C: subagent_type: general-purpose, prompt: "Implement LangGraph Workflow (US-4.1)...", run_in_background: false
- Agent D: subagent_type: general-purpose, prompt: "Implement Prompt Builder (US-4.3)...", run_in_background: false
```

### Wave 3 (Parallel)
```
Task tool calls (parallel):
- Agent E: subagent_type: general-purpose, prompt: "Implement Query Router (US-4.2)...", run_in_background: true
- Agent F: subagent_type: general-purpose, prompt: "Implement Guardrails (US-4.5)...", run_in_background: true
- Agent G: subagent_type: general-purpose, prompt: "Implement Streaming Support (US-4.6)...", run_in_background: true
```

### Wave 4 (Parallel with dependency)
```
Task tool calls (parallel):
- Agent H: subagent_type: general-purpose, prompt: "Implement Orchestrator API (US-4.8)...", run_in_background: true
- Agent I: subagent_type: general-purpose, prompt: "Implement Graceful Degradation (US-4.9)...", run_in_background: true
- Agent J: subagent_type: general-purpose, prompt: "Implement Conversation Persistence (US-4.10)...", run_in_background: true

After H completes:
- Agent K: subagent_type: general-purpose, prompt: "Implement Streaming Contract Validation (US-4.11)...", run_in_background: false
```

---

## Definition of Done (Epic Level)

- [ ] All 11 user stories implemented
- [ ] All integration checkpoints pass
- [ ] `pytest` passes with >80% coverage
- [ ] `mypy` passes with no errors
- [ ] OpenAPI docs complete at `/docs`
- [ ] Health endpoints respond correctly
- [ ] E2E query flow works (sync and streaming)
- [ ] Conversation persistence works (Redis + Postgres)
- [ ] Graceful degradation tested
- [ ] TTFT <500ms verified
- [ ] Docker image builds: `docker build -t orchestrator-service .`

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| LangGraph API changes | Pin version in requirements.txt |
| Presidio dependency size | Use lazy loading, consider lighter alternative |
| Redis connection issues | Connection pooling, health checks |
| vLLM compatibility | Test with both vLLM and Ollama |
| State explosion in workflow | Clear state boundaries, typed dicts |

---

## References

- [US-4.1 LangGraph Workflow](US-4.1-langgraph-workflow.md)
- [US-4.2 Query Router](US-4.2-query-router.md)
- [US-4.3 Prompt Builder](US-4.3-prompt-builder.md)
- [US-4.4 Model Gateway](US-4.4-model-gateway.md)
- [US-4.5 Guardrails](US-4.5-guardrails.md)
- [US-4.6 Streaming Support](US-4.6-streaming-support.md)
- [US-4.7 Conversation Memory](US-4.7-conversation-memory.md)
- [US-4.8 Orchestrator API](US-4.8-orchestrator-api.md)
- [US-4.9 Graceful Degradation](US-4.9-graceful-degradation.md)
- [US-4.10 Conversation Persistence](US-4.10-conversation-persistence.md)
- [US-4.11 Streaming Contract Validation](US-4.11-streaming-contract-validation.md)
- [Architecture Document](../../../docs/architecture.md)
