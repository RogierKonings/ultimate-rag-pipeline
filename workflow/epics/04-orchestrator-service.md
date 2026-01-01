# Epic 4: Orchestrator Service

> **Priority:** Critical  
> **Estimated Effort:** 3-4 weeks  
> **Dependencies:** Epic 3 (Retrieval), Epic 5 (LLM Serving)

## Overview

Build the orchestration layer using LangGraph that coordinates the RAG workflow, including query routing, retrieval, prompt construction, LLM calls, and response generation with guardrails.

## Goals

- Implement stateful RAG workflows with LangGraph
- Support multiple query routing strategies
- Build flexible prompt templates
- Integrate guardrails for safety
- Enable streaming responses

## User Stories

### US-4.1: LangGraph Workflow
**As a** developer  
**I want** a graph-based RAG workflow  
**So that** I can orchestrate complex retrieval and generation

**Acceptance Criteria:**
- [ ] LangGraph state machine defined
- [ ] Nodes for each pipeline stage
- [ ] Conditional edges for routing
- [ ] State persistence support
- [ ] Workflow visualization

### US-4.2: Query Router
**As a** developer  
**I want** intelligent query routing  
**So that** queries are handled by the appropriate strategy

**Acceptance Criteria:**
- [ ] Simple query detection (direct retrieval)
- [ ] Complex query detection (multi-step)
- [ ] No-retrieval detection (general knowledge)
- [ ] Router model integration
- [ ] Fallback to default strategy

### US-4.3: Prompt Builder
**As a** developer  
**I want** flexible prompt construction  
**So that** prompts are optimized for different use cases

**Acceptance Criteria:**
- [ ] Template-based prompt construction
- [ ] Context injection with source citations
- [ ] System prompt configuration
- [ ] Few-shot example support
- [ ] Token limit management

### US-4.4: Model Gateway
**As a** developer  
**I want** unified LLM access layer  
**So that** I can switch between models easily

**Acceptance Criteria:**
- [ ] OpenAI-compatible API client
- [ ] Model selection configuration
- [ ] Retry with exponential backoff
- [ ] Rate limiting
- [ ] Usage tracking

### US-4.5: Guardrails
**As a** developer  
**I want** input/output safety checks  
**So that** harmful content is blocked

**Acceptance Criteria:**
- [ ] Input validation (length, format)
- [ ] Prompt injection detection
- [ ] Output toxicity filtering
- [ ] PII redaction in responses
- [ ] Hallucination detection (optional)

### US-4.6: Streaming Support
**As a** developer  
**I want** streaming response generation  
**So that** users see responses progressively

**Acceptance Criteria:**
- [ ] Server-sent events (SSE) endpoint
- [ ] Token-by-token streaming
- [ ] Chunk metadata in stream
- [ ] Error handling in stream
- [ ] Connection timeout handling

### US-4.7: Conversation Memory
**As a** developer  
**I want** conversation history management  
**So that** multi-turn conversations work correctly

**Acceptance Criteria:**
- [ ] Redis-based session storage
- [ ] Configurable history length
- [ ] History summarization for long conversations
- [ ] Session timeout and cleanup

### US-4.8: Orchestrator API
**As a** API consumer  
**I want** REST endpoints for RAG queries  
**So that** I can integrate with client applications

**Acceptance Criteria:**
- [ ] POST `/query` - synchronous query
- [ ] POST `/query/stream` - streaming query
- [ ] GET `/sessions/{id}` - get session history
- [ ] DELETE `/sessions/{id}` - clear session
- [ ] OpenAPI documentation

## Technical Tasks

1. Set up FastAPI service structure
2. Define LangGraph state and nodes
3. Implement query router logic
4. Build prompt template system
5. Create model gateway client
6. Implement guardrail checks
7. Add SSE streaming support
8. Implement Redis session storage
9. Create API routes
10. Add OpenTelemetry instrumentation
11. Write unit and integration tests

## Definition of Done

- [ ] LangGraph workflow executes correctly
- [ ] Query routing works for different query types
- [ ] Prompts correctly formatted with context
- [ ] Guardrails block harmful content
- [ ] Streaming responses work end-to-end
- [ ] Conversation history maintained
- [ ] API documented and tested
- [ ] 80%+ test coverage
