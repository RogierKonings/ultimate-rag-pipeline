# Orchestrator Service Documentation

The Orchestrator Service is the central coordination layer of the RAG pipeline, responsible for managing the complete query lifecycle from user input to response generation. It implements a LangGraph-based workflow with intelligent routing, prompt construction, guardrails, and streaming support.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [LangGraph Workflow](#langgraph-workflow)
- [Query Router](#query-router)
- [Answer Verification](#answer-verification)
- [Multi-Hop RAG](#multi-hop-rag)
- [Prompt Builder](#prompt-builder)
- [Model Gateway](#model-gateway)
- [Guardrails](#guardrails)
- [Conversation Memory](#conversation-memory)
- [Streaming Support](#streaming-support)
- [Graceful Degradation](#graceful-degradation)
- [Cost-Aware Retrieval & Model Tiering](#cost-aware-retrieval--model-tiering)
- [Model & Retrieval Policy](#model--retrieval-policy)
- [API Reference](#api-reference)
- [Configuration](#configuration)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Orchestrator Service                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      LangGraph Workflow Engine                        │   │
│  │                                                                       │   │
│  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌───────┐ │   │
│  │   │  Input  │──▶│  Query  │──▶│Retrieval│──▶│ Prompt  │──▶│ LLM   │ │   │
│  │   │Validate │   │ Router  │   │  Node   │   │ Builder │   │ Gen   │ │   │
│  │   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └───────┘ │   │
│  │        │                           │                           │     │   │
│  │        │         ┌─────────────────┘                           │     │   │
│  │        │         │ (skip for no_retrieval)                     │     │   │
│  │        ▼         ▼                                             ▼     │   │
│  │   ┌─────────────────────────────────────────────────────────────┐   │   │
│  │   │                    Output Validation                         │   │   │
│  │   └─────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │   Guardrails  │  │    Memory     │  │   Streaming   │  │  Resilience │  │
│  │  ┌─────────┐  │  │  ┌─────────┐  │  │  ┌─────────┐  │  │ ┌─────────┐ │  │
│  │  │  Input  │  │  │  │  Redis  │  │  │  │   SSE   │  │  │ │Circuit  │ │  │
│  │  ├─────────┤  │  │  ├─────────┤  │  │  │ Events  │  │  │ │Breaker  │ │  │
│  │  │ Output  │  │  │  │Postgres │  │  │  ├─────────┤  │  │ ├─────────┤ │  │
│  │  ├─────────┤  │  │  ├─────────┤  │  │  │  TTFT   │  │  │ │Fallback │ │  │
│  │  │   PII   │  │  │  │Summary  │  │  │  │Tracking │  │  │ │Handlers │ │  │
│  │  └─────────┘  │  │  └─────────┘  │  │  └─────────┘  │  │ └─────────┘ │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  └─────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         Model Gateway (vLLM/Ollama)                    │  │
│  │  - OpenAI-compatible API  - Retry logic  - Health checks  - Streaming │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
services/orchestrator/
├── api/
│   ├── app.py                 # FastAPI application factory
│   ├── dependencies.py        # Dependency injection
│   ├── routes/
│   │   ├── query.py           # /api/v1/query, /query/stream, /feedback
│   │   ├── sessions.py        # Session CRUD endpoints
│   │   └── health.py          # Health check endpoints
│   └── models/
│       ├── requests.py        # Request schemas
│       └── responses.py       # Response schemas
├── workflow/
│   ├── graph.py               # LangGraph StateGraph definition
│   ├── state.py               # RAGState TypedDict
│   └── nodes/
│       ├── input_validation.py
│       ├── routing.py
│       ├── retrieval.py
│       ├── prompt_building.py
│       ├── generation.py
│       └── output_validation.py
├── routing/
│   ├── router.py              # QueryRouter class
│   ├── classifiers.py         # Intent/complexity classifiers
│   └── models.py              # RoutingResult, QueryIntent enums
├── prompts/
│   ├── builder.py             # PromptBuilder class
│   ├── templates.py           # Jinja2 prompt templates
│   └── context.py             # Context formatting utilities
├── gateway/
│   ├── client.py              # ModelGateway async client
│   ├── streaming.py           # SSE stream parsing
│   └── models.py              # ChatCompletionRequest/Response
├── guardrails/
│   ├── pipeline.py            # GuardrailPipeline orchestrator
│   ├── input.py               # InputGuardrail (PII, injection)
│   ├── output.py              # OutputGuardrail (harmful content)
│   └── detection.py           # Detection utilities
├── memory/
│   ├── session.py             # SessionManager
│   ├── store.py               # RedisSessionStore
│   ├── persistence.py         # PostgresConversationStore
│   ├── summarizer.py          # HistorySummarizer
│   └── models.py              # Message, ConversationSession
├── streaming/
│   ├── manager.py             # StreamManager
│   ├── models.py              # StreamEvent, StreamEventType
│   ├── validation.py          # Event sequence validation
│   ├── metrics.py             # TTFT tracking, Prometheus
│   └── buffer.py              # TokenBuffer for batching
├── resilience/
│   ├── circuit_breaker.py     # CircuitBreaker class
│   ├── fallbacks.py           # FallbackHandlers
│   ├── degradation.py         # DegradationManager
│   └── config.py              # Resilience configuration
├── config.py                  # OrchestratorConfig settings
├── run.py                     # Application entry point
└── tests/                     # 883 unit tests, 96% coverage
```

---

## LangGraph Workflow

The core RAG pipeline is implemented as a LangGraph StateGraph with conditional routing.

### State Definition

```python
from typing import TypedDict, Optional, List

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

### Workflow Graph

```python
from workflow.graph import build_rag_workflow

workflow = build_rag_workflow()
print(workflow.nodes.keys())
# ['__start__', 'input_validation', 'routing', 'retrieval',
#  'prompt_building', 'generation', 'output_validation']
```

### Graph Visualization

```mermaid
graph TD
    START([Start]) --> INPUT[Input Validation]
    INPUT -->|error| OUTPUT[Output Validation]
    INPUT -->|valid| ROUTING[Query Router]
    ROUTING -->|simple/complex| RETRIEVAL[Retrieval]
    ROUTING -->|no_retrieval| PROMPT[Prompt Building]
    RETRIEVAL --> PROMPT
    PROMPT --> GENERATION[LLM Generation]
    GENERATION --> OUTPUT
    OUTPUT --> END([End])
```

### Workflow Execution

```python
from workflow.graph import build_rag_workflow
from workflow.state import create_initial_state

workflow = build_rag_workflow()

# Create initial state
state = create_initial_state(
    request_id="req-123",
    query="What is Python?",
    session_id="session-456",
    tenant_id="tenant-789"
)

# Execute workflow
result = await workflow.ainvoke(state)

print(result["response"])  # LLM-generated answer
print(result["timing"])    # Per-node timing metrics
```

---

## Query Router

Intelligent query classification and routing strategy selection.

### Routing Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `simple` | Single retrieval pass | Factual questions, straightforward queries |
| `complex` | Multi-step retrieval | Analytical, comparison, multi-part queries |
| `no_retrieval` | Direct LLM response | Greetings, chitchat, general knowledge |

### Query Intent Classification

```python
from routing.router import QueryRouter
from routing.models import QueryIntent, RoutingStrategy

router = QueryRouter()

# Simple factual query
result = await router.route("What is Python?")
# RoutingResult(strategy=SIMPLE, intent=FACTUAL, confidence=0.85)

# Complex analytical query
result = await router.route("Compare Python and JavaScript for web development")
# RoutingResult(strategy=COMPLEX, intent=ANALYTICAL, confidence=0.90)

# Greeting (no retrieval needed)
result = await router.route("Hello!")
# RoutingResult(strategy=NO_RETRIEVAL, intent=CONVERSATIONAL, confidence=0.95)
```

### Intent Types

```python
class QueryIntent(str, Enum):
    FACTUAL = "factual"            # Seeking specific information
    ANALYTICAL = "analytical"      # Requires reasoning/comparison
    PROCEDURAL = "procedural"      # How-to/step-by-step
    CONVERSATIONAL = "conversational"  # Chitchat/greetings
    CLARIFICATION = "clarification"    # Asking to explain more
```

### Complexity Scoring

The router uses a complexity scorer (0-1 scale) based on:
- Number of clauses and conjunctions
- Query length
- Presence of comparison words
- Conversation history depth

```python
from routing.classifiers import ComplexityScorer

scorer = ComplexityScorer()
score = scorer.score("What are the benefits of Python, and how does it compare to Java?")
# 0.75 (high complexity due to multi-part structure)
```

---

## Answer Verification

CRAG-style (Corrective RAG) self-verification validates generated answers against retrieved context to improve answer quality and detect hallucinations.

### Verification Pipeline

```mermaid
graph LR
    GEN[Generation] --> EXTRACT[Claim Extraction]
    EXTRACT --> VERIFY[Claim Verification]
    VERIFY --> SCORE[Score Calculation]
    SCORE --> DISC{Score < Threshold?}
    DISC -->|Yes| DISCLAIM[Add Disclaimer]
    DISC -->|No| OUTPUT[Output]
    DISCLAIM --> OUTPUT
```

### Claim Extraction

The verification node extracts key factual claims from generated answers:

```python
from workflow.verification.claim_extractor import ClaimExtractor, Claim

extractor = ClaimExtractor(llm_client, max_claims=5)
result = await extractor.extract("Python was released in 1991 and uses indentation for code blocks.")

# ClaimExtractionResult(
#   claims=[
#     Claim(text="Python was released in 1991", claim_type="temporal"),
#     Claim(text="Python uses indentation for code blocks", claim_type="factual")
#   ],
#   extraction_time_ms=45.2
# )
```

### Claim Verification

Each claim is verified against the retrieved context:

```python
from workflow.verification.claim_verifier import ClaimVerifier, VerificationStatus

verifier = ClaimVerifier(llm_client)
result = await verifier.verify(claim, context)

# ClaimVerificationResult(
#   claim_text="Python was released in 1991",
#   status=VerificationStatus.SUPPORTED,
#   supporting_evidence="Python was first released in 1991 by Guido van Rossum",
#   confidence=0.95
# )
```

### Verification Status

| Status | Description |
|--------|-------------|
| `SUPPORTED` | Claim fully supported by context |
| `PARTIALLY_SUPPORTED` | Claim partially supported |
| `UNSUPPORTED` | No supporting evidence found |
| `UNVERIFIABLE` | Cannot determine from context |

### Verification Result

The verification node produces an overall result:

```python
@dataclass
class VerificationResult:
    score: float           # 0-1, proportion of supported claims
    label: str             # "supported", "partial", "unsupported"
    claims_total: int
    claims_supported: int
    claims_partial: int
    claims_unsupported: int
    verification_time_ms: float
    skipped: bool = False
    skip_reason: str | None = None
```

### Low Confidence Handling

When verification score falls below threshold (default: 0.7), a disclaimer is added:

```
*Note: Some information in this response could not be fully verified
against the available sources. Please verify important details independently.*
```

### Configuration

```python
class VerificationConfig(BaseModel):
    enabled: bool = False              # Opt-in by default
    max_claims: int = 5                # Max claims to extract
    confidence_threshold: float = 0.7  # Disclaimer threshold
    latency_budget_ms: int = 500       # Max additional latency
    add_disclaimer_on_low_confidence: bool = True
```

### Verification Metrics

Prometheus metrics for verification tracking:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_verification_score` | Histogram | Distribution of verification scores |
| `rag_verification_label_total` | Counter | Count by verification label |
| `rag_verification_latency_seconds` | Histogram | Verification node latency |
| `rag_verification_claims_total` | Counter | Claims by verification status |

---

## Multi-Hop RAG

Extended routing with query decomposition for complex multi-hop queries requiring information from multiple sources.

### Extended Routing Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `simple` | Single retrieval pass | Factual questions |
| `complex` | Multi-step retrieval | Analytical queries |
| `multi_hop` | Query decomposition | Sequential reasoning |
| `comparison` | Compare entities | "X vs Y" questions |
| `aggregation` | Collect and summarize | "List all...", "Summarize..." |
| `no_retrieval` | Direct LLM response | Greetings, chitchat |

### Multi-Hop Detection

The router detects multi-hop patterns using configurable regex patterns:

```python
from routing.strategies import MultiHopIndicators

# Comparison patterns
"compare X and Y", "difference between", "X vs Y", "better than"

# Aggregation patterns
"list all", "what are all", "summarize", "overview of"

# Sequential patterns
"first...then", "step by step", "after that"
```

### Query Decomposition

Complex queries are decomposed into independent sub-questions:

```python
from workflow.nodes.decomposition import QueryDecomposer

decomposer = QueryDecomposer(llm_client, max_sub_questions=5)
sub_questions = await decomposer.decompose(
    "Compare Python and JavaScript for web development"
)

# [
#   "What are the key features of Python for web development?",
#   "What are the key features of JavaScript for web development?",
#   "What are the advantages of Python over JavaScript for backends?",
#   "What are the advantages of JavaScript over Python for frontends?"
# ]
```

### Parallel Multi-Retrieval

Sub-questions are retrieved in parallel with result aggregation:

```python
from workflow.nodes.multi_retrieval import multi_retrieval_node

# Parallel retrieval for all sub-questions
results = await asyncio.gather(*[
    retrieve(sq, user_context) for sq in sub_questions
])

# Results are:
# - Deduplicated by chunk_id
# - Score-boosted for documents relevant to multiple sub-questions
# - Sorted by combined relevance
```

### Context Aggregation

Retrieved context is organized by sub-question for comprehensive answers:

```
### Context for: What are the key features of Python for web development?
[abc123] Python offers Django and Flask frameworks for web development...

### Context for: What are the key features of JavaScript for web development?
[def456] JavaScript powers both frontend (React, Vue) and backend (Node.js)...
```

### Multi-Hop Workflow

```mermaid
graph TD
    INPUT[Input] --> ROUTING[Query Router]
    ROUTING -->|simple/complex| RETRIEVAL[Single Retrieval]
    ROUTING -->|multi_hop/comparison/aggregation| DECOMP[Decomposition]
    DECOMP --> MULTI_RET[Parallel Multi-Retrieval]
    MULTI_RET --> DEDUP[Deduplication & Scoring]
    RETRIEVAL --> PROMPT[Prompt Building]
    DEDUP --> PROMPT
    PROMPT --> GEN[Generation]
    GEN --> VERIFY[Verification]
    VERIFY --> OUTPUT[Output]
```

### Multi-Hop Metrics

| Metric | Description |
|--------|-------------|
| `rag_multi_hop_queries_total` | Multi-hop query count |
| `rag_sub_question_count` | Sub-questions per query |
| `rag_multi_retrieval_latency_seconds` | Parallel retrieval latency |
| `rag_dedup_removed_total` | Duplicate documents removed |

---

## Prompt Builder

Jinja2-based prompt construction with context management.

### Prompt Templates

```python
from prompts.templates import TEMPLATES, get_template

# Available templates
print(list(TEMPLATES.keys()))
# ['rag', 'no_context', 'follow_up', 'rag_citations', 'clarification', 'summary']

# RAG template with context
template = get_template("rag")
```

### Building Prompts

```python
from prompts.builder import PromptBuilder

builder = PromptBuilder()

messages = builder.build(
    query="What is Python?",
    context="Python is a high-level programming language...",
    history=[],
    strategy="rag"
)

# Returns list of message dicts:
# [
#   {"role": "system", "content": "You are a helpful assistant..."},
#   {"role": "user", "content": "What is Python?"}
# ]
```

### Context Formatting

```python
from prompts.context import format_context, format_citations

# Format retrieved documents into context string
context = format_context(
    documents=[
        {"content": "Python is...", "title": "Intro to Python", "score": 0.95},
        {"content": "Python supports...", "title": "Python Features", "score": 0.88}
    ],
    max_tokens=2000
)

# Format citation references
citations = format_citations(documents)
# "[1] Intro to Python\n[2] Python Features"
```

---

## Model Gateway

Async HTTP client for LLM communication with streaming support.

### Basic Usage

```python
from gateway.client import ModelGateway
from gateway.models import ChatMessage, ChatCompletionRequest

gateway = ModelGateway(
    base_url="http://localhost:8004/v1",
    default_model="meta-llama/Llama-3.1-8B-Instruct"
)

# Non-streaming completion
request = ChatCompletionRequest(
    messages=[
        ChatMessage(role="user", content="What is Python?")
    ],
    max_tokens=512,
    temperature=0.7
)

response = await gateway.chat_completion(request)
print(response.choices[0].message.content)
```

### Streaming Completions

```python
# Streaming completion
async for chunk in gateway.chat_completion_stream(request):
    print(chunk.choices[0].delta.content, end="", flush=True)
```

### Retry Logic

The gateway includes automatic retry with exponential backoff:
- 3 retries for server errors (5xx)
- Exponential backoff: 1s, 2s, 4s
- No retry for client errors (4xx except 429)
- Rate limit errors (429) trigger retry with backoff

### Health Checks

```python
health = await gateway.health_check()
# {"healthy": True, "models": ["llama-3.1-8b-instruct"], "latency_ms": 45}
```

---

## Guardrails

Input validation and output filtering for safe AI interactions.

### Guardrail Pipeline

```python
from guardrails.pipeline import GuardrailPipeline

pipeline = GuardrailPipeline()

# Check user input
result = await pipeline.check_input("What is my SSN 123-45-6789?")
# GuardrailResult(passed=False, violations=[Violation(type=PII_DETECTED, ...)])

# Check LLM output
result = await pipeline.check_output(llm_response)
# GuardrailResult(passed=True, violations=[])
```

### Input Guardrails

| Check | Description |
|-------|-------------|
| Length validation | Reject queries > max length |
| PII detection | Detect email, phone, SSN, credit cards |
| Injection detection | Block prompt injection attempts |

```python
from guardrails.input import InputGuardrail

guardrail = InputGuardrail(max_length=4000)
result = await guardrail.check("ignore previous instructions...")
# Violation: INJECTION_ATTEMPT detected
```

### Output Guardrails

| Check | Description |
|-------|-------------|
| Length limits | Truncate overly long responses |
| Harmful content | Filter violent/illegal content |
| PII leakage | Detect PII in responses |

### PII Detection Patterns

```python
from guardrails.detection import detect_pii

pii_found = detect_pii("Contact me at john@example.com or 555-123-4567")
# [
#   PIIMatch(type="EMAIL", value="john@example.com", start=14, end=30),
#   PIIMatch(type="PHONE", value="555-123-4567", start=34, end=46)
# ]
```

---

## Conversation Memory

Redis-based session management with PostgreSQL persistence.

### Session Management

```python
from memory.session import SessionManager
from memory.store import RedisSessionStore

store = RedisSessionStore(redis_url="redis://localhost:6379")
manager = SessionManager(store=store)

# Create session
session = await manager.create_session(
    user_id="user-123",
    tenant_id="tenant-456",
    system_prompt="You are a helpful assistant."
)

# Add messages
await manager.add_message(
    session_id=session.id,
    role="user",
    content="What is Python?"
)

await manager.add_message(
    session_id=session.id,
    role="assistant",
    content="Python is a programming language..."
)

# Get history for LLM
history = await manager.get_history_for_llm(session_id=session.id)
# [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]
```

### Token-Aware History

```python
# Get history with token limit (for context window management)
history = await manager.get_history(
    session_id=session.id,
    max_tokens=4000,
    include_system=True
)
```

### History Summarization

When conversation history exceeds the token limit, it can be summarized:

```python
from memory.summarizer import HistorySummarizer

summarizer = HistorySummarizer(gateway=model_gateway)
summary = await summarizer.summarize(messages, existing_summary=None)
# "The user asked about Python programming..."
```

### PostgreSQL Persistence

Conversations are persisted to PostgreSQL for durability:

```python
from memory.persistence import PostgresConversationStore

pg_store = PostgresConversationStore(database_url)
await pg_store.connect()

# Save conversation
await pg_store.save_conversation(session)

# Load after Redis cache miss
session = await pg_store.load_conversation(session_id)
```

### Session TTL

Sessions expire after configurable TTL (default: 1 hour):
- Redis: Automatic TTL-based expiration
- PostgreSQL: Soft delete with cleanup job

---

## Streaming Support

Server-Sent Events (SSE) for real-time response streaming.

### Event Types

| Event | Description | Payload |
|-------|-------------|---------|
| `start` | Stream initiated | `{request_id, model, session_id}` |
| `delta` | Token chunk | `{token}` |
| `citations` | Source references | `{sources: [...]}` |
| `done` | Stream complete | `{usage, latency_ms}` |
| `error` | Error occurred | `{error, code, recoverable}` |

### SSE Wire Format

```
event: start
data: {"request_id": "req-123", "model": "llama-3.1-8b", "session_id": "sess-456"}

event: delta
data: {"token": "Python"}

event: delta
data: {"token": " is"}

event: delta
data: {"token": " a"}

event: citations
data: {"sources": [{"id": "doc-1", "title": "Python Guide", "score": 0.95}]}

event: done
data: {"usage": {"prompt_tokens": 150, "completion_tokens": 120}, "latency_ms": 450}
```

### Stream Manager

```python
from streaming.manager import StreamManager

manager = StreamManager(gateway=model_gateway)

async for event in manager.stream_response(
    request_id="req-123",
    model="llama-3.1-8b",
    messages=[{"role": "user", "content": "What is Python?"}],
    session_id="sess-456"
):
    print(event.to_sse())
```

### Event Sequence Validation

```python
from streaming.validation import EventSequenceValidator

validator = EventSequenceValidator()

for event in events:
    validator.add_event(event)  # Raises EventValidationError if invalid

assert validator.validate_sequence()  # True if valid complete sequence
```

### TTFT Tracking

Time to First Token (TTFT) is tracked for performance monitoring:

```python
from streaming.metrics import TTFTTracker, ttft_histogram

tracker = TTFTTracker(request_id="req-123")
tracker.start()

# ... wait for first token ...

tracker.record_first_token()
print(f"TTFT: {tracker.ttft_ms}ms")  # Observed in Prometheus histogram
print(f"Meets target (<500ms): {tracker.meets_target}")
```

---

## Graceful Degradation

Circuit breakers and fallback handlers for resilient operation.

### Circuit Breaker

```python
from resilience.circuit_breaker import CircuitBreaker, CircuitState

breaker = CircuitBreaker(
    name="llm_gateway",
    failure_threshold=5,
    recovery_timeout=30.0
)

# Protected call
try:
    result = await breaker.call(
        gateway.chat_completion,
        request,
        fallback=fallback_handler
    )
except CircuitOpenError:
    # Circuit is open, use fallback
    result = await fallback_handler()

# Check state
print(breaker.state)  # CircuitState.CLOSED / OPEN / HALF_OPEN
```

### Circuit States

```
CLOSED ──[failure_threshold exceeded]──▶ OPEN
   ▲                                        │
   │                                        │
   │                          [recovery_timeout]
   │                                        │
   │                                        ▼
   └───────[success]────────────────── HALF_OPEN
                                           │
                                   [failure]│
                                           ▼
                                         OPEN
```

### Fallback Handlers

```python
from resilience.fallbacks import FallbackHandlers

# LLM fallback - returns cached or default response
response = await FallbackHandlers.llm_fallback(error)
# "I apologize, but I'm unable to process your request right now."

# Retrieval fallback - returns empty results
docs = await FallbackHandlers.retrieval_fallback(error)
# []

# Embedding fallback - returns cached or raises
embedding = await FallbackHandlers.embedding_fallback(error)
```

### Degradation Manager

```python
from resilience.degradation import DegradationManager, DegradationLevel

manager = DegradationManager()

# Register circuits
manager.register_circuit("llm_gateway", critical=True)
manager.register_circuit("retrieval", critical=True)
manager.register_circuit("reranker", critical=False)

# Check degradation level
level = manager.degradation_level
# DegradationLevel.NORMAL / DEGRADED / MINIMAL

# Get status for health endpoint
status = manager.get_status()
# {
#   "level": "normal",
#   "circuits": {
#     "llm_gateway": {"state": "closed", "failures": 0},
#     "retrieval": {"state": "closed", "failures": 0}
#   }
# }
```

---

## Cost-Aware Retrieval & Model Tiering

The Orchestrator Service implements intelligent cost optimization through dynamic retrieval parameters, model tiering, answer-level caching, and token usage accounting.

## Model & Retrieval Policy

The latest policy-driven behavior is documented in:

- [Model and Retrieval Policy](model-retrieval-policy.md)

Key capabilities added:

- Centralized stage-aware model policy for generation, streaming, decomposition, and verification.
- Routing signals (`strategy`, `intent`, `complexity_score`) propagated into downstream model/retrieval decisions.
- Selective reranking (complex/analytical queries) with explicit request override support.
- Retrieval option normalization with support for both nested (`options.retrieval.*`) and legacy request keys.
- Cache-key hashing aligned with effective retrieval policy (including rerank defaults and query-based routing inference).

---

### Dynamic Retrieval Parameters

Retrieval parameters are automatically adjusted based on query type and tenant tier to optimize cost without sacrificing quality.

#### Tenant Tier Configuration

| Tier | Semantic Top-K | Keyword Top-K | Reranker | Rerank Top-K | Max Context Tokens |
|------|---------------|---------------|----------|--------------|-------------------|
| `basic` | 20 | 20 | ❌ | 0 | 2,000 |
| `standard` | 35 | 35 | ✅ | 15 | 4,000 |
| `premium` | 50 | 50 | ✅ | 30 | 8,000 |

#### Query Type Modifiers

Query complexity influences retrieval parameters via multipliers:

| Query Type | Top-K Multiplier | Reranker Override |
|------------|-----------------|-------------------|
| `SIMPLE` | 0.5x | Disabled |
| `QUESTION` | 1.0x | Use tier default |
| `SEMANTIC` | 1.2x | Enabled |
| `HYBRID` | 1.0x | Enabled |

#### Effective Parameters Calculation

```python
from services.retrieval.config import get_effective_params

# Premium tenant with semantic query
params = get_effective_params(tenant_tier="premium", query_type="SEMANTIC")
# {
#     "semantic_top_k": 60,  # 50 * 1.2
#     "keyword_top_k": 60,   # 50 * 1.2
#     "use_reranker": True,
#     "rerank_top_k": 30
# }

# Basic tenant with simple query
params = get_effective_params(tenant_tier="basic", query_type="SIMPLE")
# {
#     "semantic_top_k": 10,  # 20 * 0.5
#     "keyword_top_k": 10,   # 20 * 0.5
#     "use_reranker": False,
#     "rerank_top_k": 0
# }
```

Effective parameters are logged in the response `debug` object for observability.

### LLM Model Tiering

The Model Router selects appropriate LLM models based on query complexity and tenant tier to reduce inference costs.

#### Model Tiers

| Tier | Default Model | Max Tokens | Cost (per 1K tokens) | Use Case |
|------|---------------|------------|---------------------|----------|
| `small` | llama3.2:3b | 2,048 | $0.001 | Simple queries, basic tenants |
| `medium` | llama3.1:8b | 4,096 | $0.003 | Standard complexity |
| `large` | qwen2.5:14b | 8,192 | $0.01 | Complex analytical, premium |

Models are configurable via environment variables:
- `ORCHESTRATOR_SMALL_MODEL` - Model for small tier (default: llama3.2:3b)
- `ORCHESTRATOR_MEDIUM_MODEL` - Model for medium tier (default: llama3.1:8b)
- `ORCHESTRATOR_LARGE_MODEL` - Model for large tier (default: qwen2.5:14b)
- `ORCHESTRATOR_FALLBACK_MODEL` - Fallback model when primary fails (default: llama3.2:3b)

#### Selection Matrix

| Tenant Tier | Simple Query | Complex Query |
|-------------|--------------|---------------|
| `basic` | Small | Small |
| `standard` | Small | Medium |
| `premium` | Medium | Large |

**Intent Override:** Analytical queries from non-basic tenants are upgraded to at least Medium tier.

#### Model Router Usage

```python
from services.orchestrator.model_router import ModelRouter

router = ModelRouter()
config = router.select_model(
    tenant_tier="premium",
    complexity="complex",
    intent="ANALYTICAL"
)
# {
#     "model": "llama-3.1-70b",
#     "max_tokens": 8192,
#     "tier": "large"
# }
```

#### Fallback Logic

If the primary model fails, the router automatically falls back to the small model tier to ensure request completion.

### Answer-Level Caching

Complete RAG responses are cached to serve instant answers for repeated questions, significantly reducing LLM costs.

#### Cache Key Components

Cache keys are constructed from:
- `tenant_id`: Tenant isolation
- `normalized_query`: Lowercased, trimmed query (SHA-256 hash)
- `config_hash`: Hash of retrieval configuration
- `prompt_version`: Template version for cache invalidation

#### Cache Behavior

```python
from services.orchestrator.cache.answer_cache import AnswerCache, CachedAnswer

cache = AnswerCache(redis=redis_client, default_ttl=3600)

# Check cache before retrieval/generation
cached = await cache.get(
    tenant_id="tenant-123",
    query="How do I reset my password?",
    config_hash="abc123"
)

if cached:
    # Return cached response (skip retrieval + LLM)
    return {
        "response": cached.response,
        "citations": cached.citations,
        "cache_hit": True
    }

# Store new response after generation
await cache.set(
    tenant_id="tenant-123",
    query="How do I reset my password?",
    config_hash="abc123",
    answer=CachedAnswer(
        response="To reset your password...",
        citations=[...],
        model_used="llama-3.1-8b",
        cached_at="2025-01-15T10:00:00Z",
        retrieval_mode="hybrid"
    ),
    ttl=3600  # 1 hour, configurable per tenant
)
```

#### Cache Invalidation

Cache entries are automatically invalidated when source documents change:

```python
# Invalidate all cache entries for a tenant when documents are updated
count = await cache.invalidate_for_document(
    tenant_id="tenant-123",
    document_id="doc-456"
)
# Returns number of invalidated entries
```

#### Cache Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `default_ttl` | 3600s (1 hour) | Cache entry lifetime |
| `enable_answer_cache` | `true` | Enable/disable per request |
| `key_prefix` | `rag:answer_cache` | Redis key prefix |

### Token Usage Accounting

Per-tenant token usage is tracked for LLM and embedding operations to enable quotas and billing.

#### Usage Tracking

```python
from services.orchestrator.usage.tracker import UsageTracker

tracker = UsageTracker(redis=redis_client, session_factory=db_session)

# Record LLM usage after each request
await tracker.record_llm_usage(
    tenant_id="tenant-123",
    model="llama-3.1-8b",
    prompt_tokens=500,
    completion_tokens=150
)

# Check quota before processing
allowed, remaining = await tracker.check_quota(tenant_id="tenant-123")
if not allowed:
    raise HTTPException(status_code=429, detail="Monthly token quota exceeded")
```

#### Storage Architecture

- **Redis**: Fast real-time counters with automatic TTL
- **PostgreSQL**: Daily/monthly aggregations for reporting and billing

```sql
-- Token usage table (PostgreSQL)
SELECT tenant_id, date, model,
       SUM(prompt_tokens) as prompt_tokens,
       SUM(completion_tokens) as completion_tokens
FROM token_usage
WHERE tenant_id = 'tenant-123'
  AND date >= '2025-01-01'
GROUP BY tenant_id, date, model;
```

#### Usage API Endpoint

```
GET /api/v1/usage/{tenant_id}?period=month
```

Response:
```json
{
  "tenant_id": "tenant-123",
  "period": "month",
  "start_date": "2024-12-20",
  "end_date": "2025-01-19",
  "usage_by_model": [
    {
      "model": "llama-3.1-8b",
      "prompt_tokens": 1250000,
      "completion_tokens": 450000
    },
    {
      "model": "llama-3.1-70b",
      "prompt_tokens": 150000,
      "completion_tokens": 75000
    }
  ]
}
```

### Cost Optimization Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `rag_retrieval_top_k_used` | Histogram | Distribution of effective top_k values |
| `rag_reranker_invocations_total` | Counter | Reranker calls by tenant tier |
| `rag_llm_requests_by_model` | Counter | Requests per model tier |
| `rag_answer_cache_hit_total` | Counter | Cache hits |
| `rag_answer_cache_miss_total` | Counter | Cache misses |
| `rag_llm_tokens_total{type}` | Counter | Token usage (prompt/completion) |
| `rag_embeddings_generated_total` | Counter | Embedding operations |

### Cost Savings Summary

| Strategy | Typical Savings | Implementation |
|----------|-----------------|----------------|
| Answer caching | 20-40% | Cache repeated queries |
| Model tiering | 60-70% | Use smaller models for simple queries |
| Dynamic retrieval | 30-50% | Reduce candidates for basic tenants |
| Query-based parameters | 20-30% | Skip reranker for simple queries |

---

## API Reference

### Endpoints

#### Query Endpoints

```
POST /api/v1/query
```

Synchronous RAG query:

```json
{
  "query": "What is Python?",
  "session_id": "optional-session-id",
  "tenant_id": "tenant-uuid",
  "user_id": "user-uuid",
  "options": {
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "max_tokens": 512,
    "temperature": 0.7,
    "include_citations": true
  }
}
```

Response:

```json
{
  "request_id": "req-uuid",
  "response": "Python is a high-level programming language...",
  "sources": [
    {
      "id": "doc-uuid",
      "title": "Python Guide",
      "source_uri": "https://docs.python.org/",
      "score": 0.95
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 120,
    "total_tokens": 270
  },
  "model": "meta-llama/Llama-3.1-8B-Instruct",
  "latency_ms": 680
}
```

```
POST /api/v1/query/stream
```

Streaming RAG query (SSE):

Same request format, returns `text/event-stream` with events as documented above.

```
POST /api/v1/feedback
```

Submit user feedback:

```json
{
  "request_id": "req-uuid",
  "rating": 5,
  "comment": "Helpful answer!"
}
```

#### Session Endpoints

```
POST   /api/v1/sessions              # Create session
GET    /api/v1/sessions/{id}         # Get session
GET    /api/v1/sessions/{id}/history # Get conversation history
DELETE /api/v1/sessions/{id}         # Delete session
POST   /api/v1/sessions/{id}/clear   # Clear session history
```

#### Health Endpoints

```
GET /health       # Detailed health with component status
GET /health/live  # Kubernetes liveness probe
GET /health/ready # Kubernetes readiness probe
```

Health response:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "redis": {"status": "healthy", "latency_ms": 2},
    "llm_gateway": {"status": "healthy", "latency_ms": 45},
    "retrieval": {"status": "healthy", "latency_ms": 30}
  },
  "degradation_level": "normal"
}
```

---

## Configuration

### Environment Variables

```bash
# Service
ORCHESTRATOR_SERVICE_NAME=orchestrator-service
ORCHESTRATOR_SERVICE_PORT=8003
ORCHESTRATOR_DEBUG=false

# Retrieval Service
ORCHESTRATOR_RETRIEVAL_URL=http://localhost:8002
ORCHESTRATOR_RETRIEVAL_TIMEOUT=10.0

# LLM Gateway
ORCHESTRATOR_LLM_GATEWAY_URL=http://localhost:8004
ORCHESTRATOR_DEFAULT_MODEL=meta-llama/Llama-3.1-8B-Instruct
ORCHESTRATOR_FALLBACK_MODEL=meta-llama/Llama-3.1-70B-Instruct
ORCHESTRATOR_MAX_TOKENS=1024
ORCHESTRATOR_TEMPERATURE=0.7

# Redis (Session Storage)
ORCHESTRATOR_REDIS_URL=redis://localhost:6379
ORCHESTRATOR_SESSION_TTL=3600
ORCHESTRATOR_MAX_HISTORY_LENGTH=20

# PostgreSQL (Conversation Persistence)
ORCHESTRATOR_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ragpipeline

# Guardrails
ORCHESTRATOR_ENABLE_INPUT_GUARDRAILS=true
ORCHESTRATOR_ENABLE_OUTPUT_GUARDRAILS=true
ORCHESTRATOR_MAX_INPUT_LENGTH=4000

# Streaming
ORCHESTRATOR_STREAM_TIMEOUT=60.0

# JWT Authentication
ORCHESTRATOR_JWT_SECRET=your-secret-key
ORCHESTRATOR_JWT_ALGORITHM=HS256

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
PROMETHEUS_PORT=9090
```

### Pydantic Settings

```python
from config import OrchestratorConfig

config = OrchestratorConfig()

# Access settings
print(config.llm_gateway_url)      # http://localhost:8004
print(config.default_model)         # meta-llama/Llama-3.1-8B-Instruct
print(config.session_ttl)           # 3600
print(config.enable_input_guardrails)  # True
```

---

## Observability

### Prometheus Metrics

```
# TTFT histogram
orchestrator_ttft_seconds_bucket{le="0.5"} 950
orchestrator_ttft_seconds_count 1000

# Stream completions
orchestrator_stream_completions_total{status="success"} 980
orchestrator_stream_completions_total{status="error"} 20

# Circuit breaker status
orchestrator_circuit_state{name="llm_gateway"} 0  # 0=closed, 1=open, 2=half_open

# Request latency
orchestrator_request_duration_seconds{endpoint="/api/v1/query"}
```

### OpenTelemetry Tracing

Spans are created for each workflow node:

- `orchestrator.input_validation`
- `orchestrator.routing`
- `orchestrator.retrieval`
- `orchestrator.prompt_building`
- `orchestrator.generation`
- `orchestrator.output_validation`

Span attributes include:
- `request_id`
- `session_id`
- `tenant_id`
- `strategy`
- `model`
- `token_count`

### Structured Logging

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Query processed",
  "trace_id": "abc123",
  "span_id": "def456",
  "request_id": "req-789",
  "session_id": "sess-012",
  "tenant_id": "tenant-345",
  "strategy": "simple",
  "model": "llama-3.1-8b",
  "latency_ms": 680,
  "ttft_ms": 120
}
```

---

## Testing

### Run Tests

```bash
cd services/orchestrator

# Activate virtual environment
source ../../.venv/bin/activate

# Run all tests
python -m pytest -v

# Run specific module tests
python -m pytest tests/workflow/ -v
python -m pytest tests/routing/ -v
python -m pytest tests/guardrails/ -v

# With coverage
python -m pytest --cov=. --cov-report=html
```

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| api | 91 | 95%+ |
| workflow | 64 | 97% |
| routing | 158 | 98% |
| prompts | 100 | 99% |
| gateway | 47 | 99% |
| guardrails | 52 | 98% |
| memory | 108 | 96% |
| streaming | 219 | 99% |
| resilience | 74 | 98% |
| **Total** | **883** | **96%** |

---

## Performance Targets

| Operation | Target (p95) |
|-----------|--------------|
| Input validation | 5ms |
| Query routing | 10ms |
| Retrieval call | 200ms |
| Prompt building | 10ms |
| LLM generation | 1500ms |
| Output validation | 5ms |
| TTFT (streaming) | 500ms |
| Total E2E (sync) | 2000ms |

---

## Troubleshooting

### Common Issues

**Circuit breaker stuck open:**
```python
# Check circuit status
from resilience.degradation import get_degradation_manager
manager = get_degradation_manager()
print(manager.get_status())

# Manually reset if needed
manager.reset_circuit("llm_gateway")
```

**Session not found after restart:**
```bash
# Check Redis connectivity
redis-cli ping

# Verify PostgreSQL fallback is working
curl http://localhost:8003/health | jq '.components.postgres'
```

**Streaming timeout:**
```bash
# Increase timeout
export ORCHESTRATOR_STREAM_TIMEOUT=120.0

# Check LLM gateway health
curl http://localhost:8004/health
```

**High TTFT:**
```bash
# Check metrics
curl http://localhost:9090/metrics | grep ttft

# Verify model is loaded
curl http://localhost:8004/v1/models
```
