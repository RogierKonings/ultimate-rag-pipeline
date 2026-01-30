# Architecture

**Analysis Date:** 2026-01-30

## Pattern Overview

**Overall:** Microservices with polyglot architecture (Rust + Python), using distributed systems patterns for retrieval-augmented generation.

**Key Characteristics:**
- **Language split by domain:** Rust services for data-intensive operations (ingestion, retrieval, embedding), Python for orchestration
- **Event-driven async:** Tokio for Rust services, asyncio for Python; Redis for queueing
- **Multi-tenancy by default:** All operations scoped to tenant_id throughout the stack
- **Distributed pipeline:** Document → Parse → Chunk → Embed → Index → Search → Rerank → Generate with independent scaling per stage

## Layers

**Presentation (HTTP API):**
- Purpose: Expose services via REST/HTTP with OpenAI-compatible endpoints
- Location: `crates/rag-*/src/api/`, `services/orchestrator/api/`
- Contains: Axum route handlers (Rust), FastAPI endpoints (Python), request/response models
- Depends on: Business logic, configuration, error handling
- Used by: External clients, inter-service communication

**Business Logic / Orchestration:**
- Purpose: Coordinate workflows, routing decisions, state management
- Location: `crates/rag-retrieval/src/hybrid/`, `services/orchestrator/workflow/nodes/`, `crates/rag-ingestion/src/worker/`
- Contains: HybridSearcher, LangGraph StateGraph nodes, job queue processing
- Depends on: Data access layer, external services (Qdrant, OpenSearch), caching
- Used by: API routes, other services

**Data Access / Integration Layer:**
- Purpose: Interact with external systems (vector stores, search engines, databases, caches)
- Location: `crates/rag-vectorstore/src/`, `crates/rag-search/src/`, `crates/rag-database/src/`, `crates/rag-cache/src/`
- Contains: Client wrappers for Qdrant, OpenSearch, PostgreSQL, Redis
- Depends on: Configuration, error handling
- Used by: Business logic, aggregators

**Shared Infrastructure:**
- Purpose: Cross-cutting concerns (auth, telemetry, config, types)
- Location: `crates/rag-types/`, `crates/rag-auth/`, `crates/rag-telemetry/`, `crates/rag-config/`, `services/orchestrator/shared/`
- Contains: Common types (TenantId, DocumentId, etc.), JWT handling, OpenTelemetry setup, environment config
- Depends on: Third-party libraries
- Used by: All layers

**Specialized Workers & Processors:**
- Purpose: Background job processing and domain-specific transformations
- Location: `crates/rag-ingestion/src/worker/`, `crates/rag-ingestion/src/parsers/`, `crates/rag-ingestion/src/chunking/`, `crates/rag-video/src/`
- Contains: Job pool, document parsers, text chunking, video frame extraction
- Depends on: Data access, configuration
- Used by: Ingestion service, orchestrator

## Data Flow

**Document Ingestion Pipeline:**

1. Client → Ingestion Service API (`POST /api/v1/ingest`)
2. Input validation + connector dispatch (Filesystem, S3, API)
3. Document fetch → Raw document record
4. Parse (HTML, Markdown, PDF, DOCX) → Structured text
5. Chunk (recursive character splitter, semantic, hierarchical) → Text fragments
6. Embed via HTTP to Embedding Service → Vector embeddings
7. Parallel writes:
   - Qdrant: Upsert vectors with payload (tenant_id, chunk_id, metadata)
   - OpenSearch: Index text with BM25 analyzer
   - PostgreSQL: Store chunk metadata, source docs, embeddings
8. Job status updates via Redis queue
9. Async worker processes completion event → Returns IndexStatus

**Query Retrieval Pipeline:**

1. Client → Retrieval Service API (`POST /api/v1/retrieve`)
2. Cache check (Redis) → Return if hit
3. Query preprocessing (normalization, intent classification)
4. Optional query expansion (synonym addition)
5. Optional HyDE (generate hypothetical document)
6. Embed query via HTTP to Embedding Service → Query vector
7. Parallel hybrid search execution:
   - Semantic: Qdrant.search(vector, filters) → Top-50 candidates
   - Keyword: OpenSearch.bm25(text, filters) → Top-50 candidates
8. Fusion (RRF, Linear, DBSF) → Merged ranked results
9. Optional reranking (HTTP to LLM Gateway cross-encoder) → Final top-K
10. ACL filtering (visibility + group membership check) → Filtered results
11. Cache store (Redis) → RetrievalResult
12. Return to client with metadata, scores, debug info

**RAG Query Orchestration Pipeline:**

1. Client → Orchestrator Service API (`POST /api/v1/query`)
2. LangGraph workflow invocation:
   - **Input Validation Node:** Check PII, length, injection attempts
   - **Routing Node:** Classify intent (factual/analytical/conversational), select strategy (simple/complex/no_retrieval)
   - **Retrieval Node:** Call Retrieval Service if strategy != no_retrieval
   - **Prompt Building Node:** Format context with Jinja2 templates, manage conversation history
   - **Generation Node:** Call LLM Gateway, stream tokens via SSE, track TTFT
   - **Output Validation Node:** Filter harmful content, detect PII leakage, verify citations
3. Response assembly with sources, metadata, usage stats
4. Optional streaming (Server-Sent Events) via `POST /api/v1/query/stream`
5. Session persistence (Redis + PostgreSQL fallback)
6. Return to client

**State Management:**

- **Ingestion:** Job state in Redis queue, document metadata in PostgreSQL
- **Retrieval:** Query results cached in Redis (hash key = hash(query + filters)), TTL-based expiration
- **Orchestration:** Session context in Redis (hash = session_id), full conversation in PostgreSQL, fallback to summarization
- **Query state:** Per-request state in LangGraph RAGState (dict) with timing/metadata per node

## Key Abstractions

**Document:**
- Purpose: Represents ingested content with metadata
- Examples: `crates/rag-types/src/document.rs`, `services/orchestrator/shared/database/models/`
- Pattern: Record with source_type, visibility, chunk references, ACL fields (allowed_groups)

**Chunk:**
- Purpose: Atomic unit for embedding and retrieval
- Examples: `crates/rag-types/src/document.rs`
- Pattern: Text fragment with parent document reference, embedding vector, position metadata

**SearchResult:**
- Purpose: Unified result from semantic or keyword search
- Examples: `crates/rag-retrieval/src/types.rs`, `crates/rag-types/src/search.rs`
- Pattern: Item with ID, score, content, source URI, and optional debug metadata

**RetrievalResult:**
- Purpose: Complete retrieval response with hybrid fusion metadata
- Examples: `crates/rag-retrieval/src/api/types.rs`
- Pattern: Top-K results, per-stage timing, fusion scores, available in cache

**RAGState (LangGraph):**
- Purpose: Shared workflow state across all orchestration nodes
- Examples: `services/orchestrator/workflow/state.py`
- Pattern: TypedDict with request_id, query, session_id, strategy, documents, response, timing dict, error

**UserContext:**
- Purpose: Encapsulates authenticated user info with tenant/group membership
- Examples: `crates/rag-retrieval/src/types.rs`, `services/orchestrator/shared/security/`
- Pattern: user_id + tenant_id + roles + groups + admin flag

**Embedding:**
- Purpose: Dense vector representation of text
- Examples: `crates/rag-types/src/embedding.rs`
- Pattern: Vec<f32> with dimension (384), optionally cached with content hash

## Entry Points

**Ingestion Service:**
- Location: `crates/rag-ingestion/src/bin/main.rs`
- Triggers: Startup via `cargo run -p rag-ingestion`, Docker container, Kubernetes pod
- Responsibilities: Listen on port 8001, accept document ingest requests, spawn worker pool, manage indexing

**Retrieval Service:**
- Location: `crates/rag-retrieval/src/bin/main.rs`
- Triggers: Startup via `cargo run -p rag-retrieval`, Docker/Kubernetes
- Responsibilities: Listen on port 8002, serve hybrid search requests, enforce ACL, manage query caching

**Embedding Service:**
- Location: `crates/rag-embedding/src/bin/main.rs`
- Triggers: Startup via `cargo run -p rag-embedding`
- Responsibilities: Listen on port 8080, serve embeddings via OpenAI-compatible API, load ONNX model into memory

**LLM Gateway:**
- Location: `crates/rag-llm-gateway/src/bin/main.rs`
- Triggers: Startup via `cargo run -p rag-llm-gateway`
- Responsibilities: Listen on port 8004, proxy to vLLM, provide reranker, rate limiting, JWT auth

**Orchestrator Service:**
- Location: `services/orchestrator/run.py`
- Triggers: `python -m run` or uvicorn, Docker/Kubernetes
- Responsibilities: Listen on port 8003, build and execute LangGraph workflows, stream responses

**Ingestion Worker:**
- Location: `crates/rag-ingestion/src/bin/main.rs` (same service)
- Triggers: Background tasks spawned from API route handlers
- Responsibilities: Process job queue from Redis, execute document parsing/chunking/embedding, persist results

## Error Handling

**Strategy:** Typed errors with conversion to HTTP status codes, graceful degradation with fallbacks.

**Patterns:**

1. **Rust Services:** Custom error enums (e.g., `RetrievalError`, `IngestionError`) derived from `thiserror`
   - Map to HTTP 400/404/500 via Axum extractors
   - Logged with context via `tracing` span attributes
   - Example: `crates/rag-retrieval/src/error.rs`

2. **Python Services:** Pydantic validation errors caught in FastAPI exception handlers
   - Circuit breaker raises `CircuitOpenError` → 503 Service Unavailable
   - Fallback handlers invoked before returning error
   - Example: `services/orchestrator/resilience/circuit_breaker.py`

3. **Job Failures:** Ingestion job goes to DLQ (dead-letter queue) after max retries
   - Status stored in PostgreSQL for audit
   - Client can query sync status endpoint: `GET /api/v1/ingest/sync-status/{document_id}`

4. **Timeout Handling:** All external calls wrapped with timeout decorator
   - Cascading timeouts enforce outer > inner (e.g., RAG total 30s > Retrieval 15s > Embedding 5s)
   - Validated at startup in `services/orchestrator/config/timeouts.py`

## Cross-Cutting Concerns

**Logging:**
- Structured logging via `tracing` (Rust) and Python `logging` with JSON formatters
- Request ID propagated via X-Request-ID header
- All logs include trace_id, span_id, request_id, tenant_id

**Validation:**
- Input validation on API boundaries via Serde (Rust) and Pydantic (Python)
- Pii detection in guardrails (email, phone, SSN, credit card patterns)
- Query length limits (default 4000 chars) enforced in orchestrator

**Authentication:**
- JWT validation via `crates/rag-auth/` with RS256/HS256 support
- Token claims include tenant_id, user_id, roles, groups
- Middleware on all Rust services checks Authorization header
- FastAPI dependency injection for Python services

**Multi-Tenancy:**
- All queries filter by tenant_id at API layer (Axum/FastAPI extractors)
- Filters pushed to data stores (Qdrant payload filter, OpenSearch query filter, PostgreSQL WHERE)
- Isolation enforced before returning results to prevent cross-tenant data leakage

**Observability:**
- OpenTelemetry tracing with OTLP export to Jaeger (configurable endpoint)
- Prometheus metrics collected in `crates/rag-telemetry/`, exposed on `/metrics` endpoint
- Structured logging with correlation IDs enables end-to-end request tracing

---

*Architecture analysis: 2026-01-30*
