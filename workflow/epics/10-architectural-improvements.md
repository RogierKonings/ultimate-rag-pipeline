# Epic 10: Architectural Improvements & Production Hardening

> **Version:** 1.0  
> **Status:** Draft  
> **Priority:** P0-P2 (Mixed)  
> **Created:** January 2026  
> **Estimated Effort:** 6-8 weeks (phased)

## Executive Summary

This epic captures architectural improvements, optimizations, and production hardening recommendations derived from a deep analysis of the current RAG pipeline. The improvements are organized into seven initiatives spanning data consistency, resilience, observability, modern RAG techniques, cost optimization, developer experience, and security.

The current architecture is solid with good separation of concerns, ~90%+ test coverage, and production-ready foundations. The main gaps are:
1. Multi-store consistency and ACL enforcement
2. Cross-service resilience and adaptive degradation
3. Modern RAG patterns (self-RAG, query decomposition)
4. Security hardening for true multi-tenant production

---

## Table of Contents

1. [Initiative 1: Multi-Store Indexing & ACL Bulletproofing](#initiative-1-multi-store-indexing--acl-bulletproofing)
2. [Initiative 2: End-to-End Resilience & Adaptive Degradation](#initiative-2-end-to-end-resilience--adaptive-degradation)
3. [Initiative 3: Unified Cross-Service Observability](#initiative-3-unified-cross-service-observability)
4. [Initiative 4: Modern RAG Techniques](#initiative-4-modern-rag-techniques)
5. [Initiative 5: Cost-Aware Retrieval & Model Tiering](#initiative-5-cost-aware-retrieval--model-tiering)
6. [Initiative 6: Developer Experience Improvements](#initiative-6-developer-experience-improvements)
7. [Initiative 7: Security & Production Hardening](#initiative-7-security--production-hardening)

---

## Initiative 1: Multi-Store Indexing & ACL Bulletproofing

**Priority:** P0  
**Effort:** Large (1-2 weeks)  
**Addresses:** Architecture, Data Consistency, Security, Feature Gaps

### Problem Statement

The current architecture indexes documents to three stores (Qdrant, OpenSearch, PostgreSQL) but lacks explicit lifecycle state tracking and reconciliation. ACL filtering happens after RRF and reranking, which is suboptimal for performance and could leak results in edge cases.

### User Stories

#### US-10.1.1: Explicit Indexing State Machine
**As a** system operator  
**I want** to see the indexing status of each document across all stores  
**So that** I can identify and resolve sync issues quickly

**Acceptance Criteria:**
- [ ] Add `qdrant_status` and `opensearch_status` fields to Document model (`PENDING|OK|ERROR`)
- [ ] Add `last_indexed_at` and `last_index_error` fields
- [ ] `indexing/coordinator.py` tracks status per store
- [ ] API endpoint to query documents by indexing status
- [ ] Dashboard widget showing sync health

**Technical Notes:**
```python
# services/shared/database/models/document.py
class Document(Base, TimestampMixin, SoftDeleteMixin):
    # ... existing fields ...
    
    # Indexing status tracking
    qdrant_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
        comment="PENDING|OK|ERROR"
    )
    opensearch_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
        comment="PENDING|OK|ERROR"  
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

---

#### US-10.1.2: Background Index Reconciler
**As a** system operator  
**I want** automatic detection and repair of index inconsistencies  
**So that** retrieval quality is maintained without manual intervention

**Acceptance Criteria:**
- [ ] New Celery task `reconcile_index(tenant_id, document_id=None)`
- [ ] Compares Postgres authoritative state with Qdrant/OpenSearch
- [ ] Re-issues failed writes for missing chunks
- [ ] Cleans up orphaned vectors/docs where `status=deleted`
- [ ] Scheduled per-tenant with configurable frequency
- [ ] Admin API to trigger manual reconciliation
- [ ] Metrics: `index_reconciliation_runs_total`, `index_orphans_cleaned_total`

**Technical Notes:**
```python
# services/ingestion/tasks/reconcile.py
@celery_app.task(queue="maintenance")
async def reconcile_index(
    tenant_id: str,
    document_id: str | None = None,
    dry_run: bool = False
) -> ReconciliationResult:
    """
    Reconcile Postgres state with Qdrant/OpenSearch.
    
    1. Load documents from Postgres (filtered by status, tenant)
    2. Verify chunks exist in Qdrant (by chunk_id)
    3. Verify chunks exist in OpenSearch (by chunk_id)
    4. Re-index missing chunks
    5. Delete orphaned entries
    """
    ...
```

---

#### US-10.1.3: Soft-Delete Propagation
**As a** system administrator  
**I want** document deletions to cascade to all stores atomically  
**So that** deleted content is never returned in search results

**Acceptance Criteria:**
- [ ] When `status='deleted'` in Postgres, immediately enqueue tombstone task
- [ ] Tombstone task deletes from Qdrant and OpenSearch by `document_id`
- [ ] Retrieval filters always include `status='active'`
- [ ] `status` field synced to Qdrant payload and OpenSearch document
- [ ] Integration test verifying deleted docs are never returned

---

#### US-10.1.4: Early ACL Filtering
**As a** security-conscious developer  
**I want** ACL filters applied at the database query level  
**So that** unauthorized documents never reach the reranker

**Acceptance Criteria:**
- [ ] Qdrant queries always include `tenant_id`, `visibility`, `allowed_groups` filters
- [ ] OpenSearch queries include equivalent filter clause
- [ ] Remove or demote post-rerank ACL filter to safety-net only
- [ ] Performance improvement measured (fewer docs to rerank)
- [ ] Security test: unauthorized docs never appear in any stage

**Technical Notes:**
```python
# services/retrieval/acl/filter.py
def build_qdrant_filter(user_context: UserContext) -> dict:
    """Build Qdrant filter from user context - ALWAYS applied."""
    return {
        "must": [
            {"key": "tenant_id", "match": {"value": str(user_context.tenant_id)}},
            {"key": "status", "match": {"value": "active"}},
            {
                "should": [
                    {"key": "visibility", "match": {"value": "public"}},
                    {"key": "visibility", "match": {"value": "tenant"}},
                    {
                        "must": [
                            {"key": "visibility", "match": {"value": "group"}},
                            {"key": "allowed_groups", "match": {"any": user_context.groups}}
                        ]
                    },
                    {
                        "must": [
                            {"key": "visibility", "match": {"value": "private"}},
                            {"key": "owner_id", "match": {"value": str(user_context.user_id)}}
                        ]
                    }
                ]
            }
        ]
    }
```

---

#### US-10.1.5: Tenant-Scoped Index Configuration (Medium-term)
**As a** platform operator  
**I want** the option to use per-tenant collections for large tenants  
**So that** I can isolate workloads and scale independently

**Acceptance Criteria:**
- [ ] Configuration option `tenant_isolation_mode: shared|dedicated`
- [ ] `collection_manager.py` supports per-tenant Qdrant collections
- [ ] OpenSearch index templates for tenant-specific indices
- [ ] Retrieval service routes to correct collection/index
- [ ] Documentation for migration path

---

## Initiative 2: End-to-End Resilience & Adaptive Degradation

**Priority:** P0  
**Effort:** Large (1-2 weeks)  
**Addresses:** Architecture, Scalability, Resilience, Cost

### Problem Statement

The Orchestrator has resilience patterns (circuit breakers, fallbacks) but the Retrieval service lacks explicit degradation modes. Services don't communicate degradation state to each other. Ingestion lacks tenant-based rate limiting.

### User Stories

#### US-10.2.1: Retrieval Service Resilience Layer
**As a** system operator  
**I want** the retrieval service to gracefully degrade when components fail  
**So that** users get results even during partial outages

**Acceptance Criteria:**
- [ ] Create `retrieval/resilience/` module with circuit breakers
- [ ] Circuit breakers for: Qdrant, OpenSearch, LLM Gateway (reranking)
- [ ] Degradation modes:
  - `HYBRID_FULL` (default)
  - `SEMANTIC_ONLY` (OpenSearch unhealthy)
  - `KEYWORD_ONLY` (Qdrant unhealthy)
  - `HYBRID_NO_RERANK` (reranker slow/unhealthy)
- [ ] `/health` endpoint includes `degradation_level` field
- [ ] Prometheus metric: `retrieval_degradation_mode{mode}`

**Technical Notes:**
```python
# services/retrieval/resilience/degradation.py
class RetrievalDegradationManager:
    """Manages degradation modes based on circuit breaker states."""
    
    class Mode(str, Enum):
        HYBRID_FULL = "hybrid_full"
        SEMANTIC_ONLY = "semantic_only"
        KEYWORD_ONLY = "keyword_only"
        HYBRID_NO_RERANK = "hybrid_no_rerank"
        MINIMAL = "minimal"  # Last resort
    
    def get_current_mode(self) -> Mode:
        """Determine mode based on circuit states."""
        if self.qdrant_breaker.state == CircuitState.OPEN:
            if self.opensearch_breaker.state == CircuitState.OPEN:
                return Mode.MINIMAL
            return Mode.KEYWORD_ONLY
        if self.opensearch_breaker.state == CircuitState.OPEN:
            return Mode.SEMANTIC_ONLY
        if self.reranker_breaker.state == CircuitState.OPEN:
            return Mode.HYBRID_NO_RERANK
        return Mode.HYBRID_FULL
```

---

#### US-10.2.2: Cross-Service Degradation Propagation
**As a** system developer  
**I want** the orchestrator to adjust behavior based on retrieval degradation  
**So that** user expectations are set appropriately

**Acceptance Criteria:**
- [ ] Retrieval response includes `degradation_level` and `components` status
- [ ] Orchestrator parses degradation info from retrieval response
- [ ] Prompt adjusted when retrieval is degraded (e.g., "context may be incomplete")
- [ ] Streaming events include degradation status
- [ ] Response metadata includes `retrieval_mode_used`

**Technical Notes:**
```python
# services/orchestrator/workflow/nodes/retrieval.py
async def retrieval_node(state: RAGState) -> RAGState:
    response = await retrieval_client.search(...)
    
    # Track degradation
    degradation = response.get("degradation_level", "normal")
    if degradation != "normal":
        state["fallbacks_used"].append(f"retrieval:{degradation}")
        state["context_quality"] = "partial"
    
    return state
```

---

#### US-10.2.3: Ingestion Rate Limiting
**As a** platform operator  
**I want** per-tenant rate limits on ingestion jobs  
**So that** noisy tenants don't starve others

**Acceptance Criteria:**
- [ ] Per-tenant max concurrent ingestion jobs (configurable)
- [ ] Redis-based job counter per tenant
- [ ] Jobs exceeding limit are queued or rejected with 429
- [ ] Priority queues: `ingestion_high`, `ingestion_normal`, `ingestion_low`
- [ ] Admin API to view/modify tenant limits
- [ ] Metrics: `ingestion_jobs_queued_by_tenant`, `ingestion_rate_limited_total`

---

#### US-10.2.4: Timeout & Retry Policy Unification
**As a** system developer  
**I want** consistent timeout and retry policies across services  
**So that** behavior is predictable and debuggable

**Acceptance Criteria:**
- [ ] Document standard timeout values in `CLAUDE.md` or shared config
- [ ] Align env vars: `*_TIMEOUT`, `*_RETRIES` across services
- [ ] Single retry with exponential backoff for idempotent calls
- [ ] Surface partial degradation instead of silent timeout
- [ ] Integration test for timeout cascade behavior

**Technical Notes:**
| Operation | Timeout | Retries |
|-----------|---------|---------|
| Embedding request | 10s | 2 |
| Qdrant query | 5s | 1 |
| OpenSearch query | 5s | 1 |
| Reranker batch | 30s | 1 |
| LLM generation | 60s | 0 |
| Retrieval (total) | 30s | 0 |

---

## Initiative 3: Unified Cross-Service Observability

**Priority:** P1  
**Effort:** Large (1-2 weeks)  
**Addresses:** Performance, Observability, DX, Cost

### Problem Statement

Each service has OTEL and Prometheus, but there's no consistent correlation ID propagation or cross-service trace visualization. Business metrics (RAG success rate, feedback correlation) are missing.

### User Stories

#### US-10.3.1: Strict Correlation ID Propagation
**As a** system debugger  
**I want** to trace a single request across all services  
**So that** I can diagnose issues in distributed workflows

**Acceptance Criteria:**
- [ ] Standardize headers: `X-Request-ID`, `X-Trace-ID`, `X-Tenant-ID`
- [ ] Orchestrator generates `request_id` for each `/query`
- [ ] `request_id` propagated to: Retrieval, LLM Gateway, Embedding
- [ ] Middleware in all services extracts headers into:
  - OTEL span attributes
  - Log context
- [ ] All logs joinable by `request_id` in log aggregator

**Technical Notes:**
```python
# services/shared/observability/middleware.py
class CorrelationMiddleware:
    """Extract/generate correlation IDs and propagate to context."""
    
    async def __call__(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        trace_id = request.headers.get("X-Trace-ID") or request_id
        tenant_id = request.headers.get("X-Tenant-ID")
        
        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id
        )
        
        # Add to OTEL span
        span = trace.get_current_span()
        span.set_attribute("request_id", request_id)
        span.set_attribute("tenant_id", tenant_id or "unknown")
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

---

#### US-10.3.2: End-to-End Trace Hierarchy
**As a** performance engineer  
**I want** to see a single trace from ingestion through retrieval to generation  
**So that** I can identify bottlenecks across the pipeline

**Acceptance Criteria:**
- [ ] All HTTP clients (httpx) OTEL-instrumented
- [ ] Qdrant and OpenSearch clients emit child spans
- [ ] Canonical span naming:
  - `ingestion.{parse|chunk|embed|index}`
  - `retrieval.{preprocess|semantic_search|keyword_search|fusion|rerank}`
  - `orchestrator.workflow.{node_name}`
- [ ] Jaeger shows complete request lifecycle
- [ ] Document span hierarchy in observability docs

---

#### US-10.3.3: Business & Quality Metrics
**As a** product manager  
**I want** to see RAG quality metrics and user feedback  
**So that** I can measure and improve the product

**Acceptance Criteria:**
- [ ] Counter: `rag_queries_total{strategy, rag_used, degraded}`
- [ ] Counter: `rag_feedback_total{rating}` (from `/feedback` endpoint)
- [ ] Histogram: `rag_e2e_latency_seconds{strategy, tenant_tier}`
- [ ] Gauge: `rag_fallback_usage{type}` (cache, degraded retrieval, etc.)
- [ ] Dashboard: RAG quality overview with trending

---

#### US-10.3.4: SLO Definitions & Alerts
**As a** SRE  
**I want** defined SLOs with automated alerting  
**So that** I can ensure reliability targets are met

**Acceptance Criteria:**
- [ ] Define SLOs:
  - Retrieval p95 < 250ms
  - RAG E2E p95 < 2000ms
  - Error rate < 1% per tenant
- [ ] Grafana dashboards with SLO burn rate
- [ ] AlertManager rules for SLO violations
- [ ] Runbook for each alert type

---

## Initiative 4: Modern RAG Techniques

**Priority:** P1  
**Effort:** Large-XL (2-3 weeks, phased)  
**Addresses:** Architecture, Performance, Feature Gaps, Modern RAG

### Problem Statement

The current LangGraph workflow is linear with simple routing. Modern RAG techniques like self-RAG, CRAG-style verification, and query decomposition are not implemented.

### Phase 1: Self-RAG / CRAG-style Verification

#### US-10.4.1: Answer Verification Node
**As a** user  
**I want** the system to verify answers against retrieved context  
**So that** I receive more accurate, grounded responses

**Acceptance Criteria:**
- [ ] New `verification` node in LangGraph after `generation`
- [ ] LLM extracts key claims from generated answer
- [ ] Optional: secondary retrieval for claim verification
- [ ] LLM judges: `supported|partially|unsupported`
- [ ] Verification score stored in `RAGState.usage`
- [ ] Configurable per-tenant (enable for high-risk domains)
- [ ] Latency budget: max 500ms additional

**Technical Notes:**
```python
# services/orchestrator/workflow/nodes/verification.py
async def verification_node(state: RAGState) -> RAGState:
    """Verify generated answer against retrieved context."""
    if not state.get("enable_verification", False):
        state["verification_result"] = {"skipped": True}
        return state
    
    # Extract claims from answer
    claims = await extract_claims(state["response"], llm_client)
    
    # Check each claim against context
    verification_results = []
    for claim in claims:
        result = await verify_claim(claim, state["context"], llm_client)
        verification_results.append(result)
    
    # Aggregate
    supported_count = sum(1 for r in verification_results if r.supported)
    total_claims = len(verification_results)
    
    state["verification_result"] = {
        "score": supported_count / total_claims if total_claims > 0 else 1.0,
        "label": "supported" if supported_count == total_claims else "partial",
        "claims_verified": total_claims
    }
    
    # Add disclaimer if low confidence
    if state["verification_result"]["score"] < 0.7:
        state["response"] += "\n\n*Note: Some information could not be fully verified against available sources.*"
    
    return state
```

---

#### US-10.4.2: Verification Metrics & Logging
**As a** ML engineer  
**I want** to track verification outcomes  
**So that** I can measure and improve answer quality

**Acceptance Criteria:**
- [ ] Log `verification_score`, `verification_label` per request
- [ ] Prometheus metrics: `rag_verification_score_histogram`, `rag_verification_label_total`
- [ ] Correlation with user feedback
- [ ] Dashboard: verification success rate trending

---

### Phase 2: Query Decomposition (Optional)

#### US-10.4.3: Extended Routing with Multi-Hop Strategy
**As a** user asking complex questions  
**I want** the system to break down my query into sub-questions  
**So that** I get comprehensive answers for complex topics

**Acceptance Criteria:**
- [ ] Extend routing strategies: `SIMPLE|COMPLEX|MULTI_HOP|AGGREGATION|NO_RETRIEVAL`
- [ ] Multi-hop detection based on query complexity score
- [ ] New `decomposition` node that splits query into sub-questions
- [ ] Configurable max sub-questions (default: 3)
- [ ] Metrics: queries decomposed, sub-question count

---

#### US-10.4.4: Parallel Multi-Retrieval
**As a** user with multi-hop queries  
**I want** the system to retrieve context for each sub-question  
**So that** all aspects of my question are addressed

**Acceptance Criteria:**
- [ ] New `multi_retrieval` node after decomposition
- [ ] Parallel retrieval for sub-questions (asyncio.gather)
- [ ] Context aggregation and deduplication
- [ ] Merged context with sub-question attribution
- [ ] Latency target: < 500ms overhead for parallelism

**Technical Notes:**
```python
# Updated workflow graph for multi-hop
def build_rag_workflow() -> StateGraph:
    graph = StateGraph(RAGState)
    
    # Existing nodes...
    graph.add_node("decomposition", decomposition_node)
    graph.add_node("multi_retrieval", multi_retrieval_node)
    
    # Extended routing
    graph.add_conditional_edges(
        "routing",
        _route_after_routing,
        {
            "retrieval": "retrieval",
            "decomposition": "decomposition",  # Multi-hop path
            "prompt_building": "prompt_building",
        },
    )
    
    graph.add_edge("decomposition", "multi_retrieval")
    graph.add_edge("multi_retrieval", "prompt_building")
    
    return graph.compile()
```

---

## Initiative 5: Cost-Aware Retrieval & Model Tiering

**Priority:** P1  
**Effort:** Medium-Large (1 week)  
**Addresses:** Performance, Cost, Modern RAG

### Problem Statement

Current configuration uses static retrieval parameters and a single LLM model. There's no dynamic adjustment based on query complexity, tenant tier, or cost constraints.

### User Stories

#### US-10.5.1: Dynamic Retrieval Parameters
**As a** platform operator  
**I want** retrieval parameters adjusted based on query type and tenant  
**So that** I can optimize cost without sacrificing quality

**Acceptance Criteria:**
- [ ] Query type (`SIMPLE|QUESTION|SEMANTIC|HYBRID`) influences:
  - `semantic_top_k`, `keyword_top_k`
  - `use_reranker` flag
  - `rerank_top_k`
- [ ] Tenant tier configuration: `basic|standard|premium`
- [ ] Premium tenants get more retrieval candidates and reranking
- [ ] Effective parameters logged in response `debug` section
- [ ] Metrics: `retrieval_top_k_used`, `reranker_invocations_total`

**Technical Notes:**
```python
# services/retrieval/config.py
class TierConfig(BaseModel):
    """Retrieval configuration by tenant tier."""
    
    tier_configs = {
        "basic": {
            "semantic_top_k": 20,
            "keyword_top_k": 20,
            "use_reranker": False,
            "rerank_top_k": 0
        },
        "standard": {
            "semantic_top_k": 35,
            "keyword_top_k": 35,
            "use_reranker": True,
            "rerank_top_k": 15
        },
        "premium": {
            "semantic_top_k": 50,
            "keyword_top_k": 50,
            "use_reranker": True,
            "rerank_top_k": 30
        }
    }
```

---

#### US-10.5.2: LLM Model Tiering
**As a** platform operator  
**I want** to use smaller models for simple queries  
**So that** I can reduce inference costs

**Acceptance Criteria:**
- [ ] Router selects model based on `QueryIntent` and tenant tier
- [ ] Default: `Qwen2.5-7B` or `Llama-3.1-8B`
- [ ] Premium + complex queries: `Llama-70B`
- [ ] Model selection logged per request
- [ ] Metrics: `llm_requests_by_model{model}`
- [ ] Fallback model on primary failure

---

#### US-10.5.3: Answer-Level Caching
**As a** user asking common questions  
**I want** instant responses for previously asked questions  
**So that** I get faster answers and the system saves resources

**Acceptance Criteria:**
- [ ] Cache key: `(tenant_id, normalized_query, retrieval_config_hash, prompt_version)`
- [ ] On cache hit: return stored response and citations (skip retrieval+LLM)
- [ ] Configurable TTL per tenant (default: 1 hour)
- [ ] Cache invalidation when source documents change
- [ ] Metrics: `answer_cache_hit_total`, `answer_cache_miss_total`
- [ ] Response indicates cache hit in metadata

---

#### US-10.5.4: Token Usage Accounting
**As a** platform operator  
**I want** per-tenant token usage tracking  
**So that** I can implement quotas and billing

**Acceptance Criteria:**
- [ ] Counter: `llm_tokens_total{tenant_id, model, type}` (prompt/completion)
- [ ] Counter: `embeddings_generated_total{tenant_id}`
- [ ] Daily/monthly aggregation in Postgres
- [ ] API endpoint for usage stats per tenant
- [ ] Optional: enforce quota limits with 429 response

---

## Initiative 6: Developer Experience Improvements

**Priority:** P2  
**Effort:** Medium (3-5 days)  
**Addresses:** Architecture Clarity, Observability, DX

### User Stories

#### US-10.6.1: End-to-End Smoke Test Suite
**As a** developer  
**I want** an automated E2E test that validates the entire pipeline  
**So that** I can catch integration issues early

**Acceptance Criteria:**
- [ ] `tests/e2e/` directory with docker-compose based tests
- [ ] Ingest canonical test dataset (10 docs with known answers)
- [ ] Query orchestrator and assert:
  - Latency within bounds
  - Citations contain expected document IDs
  - Response quality checks
- [ ] CI job runs E2E tests on merge to main
- [ ] Documentation for running locally

---

#### US-10.6.2: Unified Shared Configuration
**As a** developer  
**I want** a single source of truth for chunking and embedding config  
**So that** services don't have diverging defaults

**Acceptance Criteria:**
- [ ] Create `services/shared/config/defaults.py`
- [ ] Define: chunking defaults, embedding model/dimensions
- [ ] Ingestion and retrieval import from shared config
- [ ] Config validation at service startup
- [ ] Documentation for config hierarchy

---

#### US-10.6.3: Developer CLI Tools
**As a** developer  
**I want** CLI tools for common operations  
**So that** I can debug multi-service issues quickly

**Acceptance Criteria:**
- [ ] `scripts/dev-ingest.py` - CLI for ingestion API
- [ ] `scripts/dev-query.py` - CLI for orchestrator queries with debug output
- [ ] `scripts/dev-health.py` - Check all service health endpoints
- [ ] `scripts/dev-reconcile.py` - Trigger index reconciliation
- [ ] Documentation in `scripts/README.md`

---

## Initiative 7: Security & Production Hardening

**Priority:** P0 (for production deployment)  
**Effort:** Large-XL (2-3 weeks)  
**Addresses:** Architecture, Resilience, Security

### Problem Statement

Current configuration is development-oriented (OpenSearch security disabled, MinIO root creds, etc.). True multi-tenant production requires explicit hardening.

### User Stories

#### US-10.7.1: Inter-Service Authentication
**As a** security engineer  
**I want** all inter-service communication authenticated  
**So that** rogue processes cannot access internal APIs

**Acceptance Criteria:**
- [ ] mTLS or service-level JWT between all services
- [ ] Kubernetes NetworkPolicy restricting traffic
- [ ] No internal services exposed publicly (Qdrant, OpenSearch, Redis, Postgres, MinIO)
- [ ] Service mesh integration documentation (optional Istio/Linkerd)
- [ ] Security test validating isolation

---

#### US-10.7.2: Database Security Enablement
**As a** security engineer  
**I want** production security features enabled on all data stores  
**So that** data at rest and in transit is protected

**Acceptance Criteria:**
- [ ] OpenSearch security plugin enabled in non-dev profiles
- [ ] Per-service credentials for OpenSearch
- [ ] Qdrant API keys and TLS enabled
- [ ] PostgreSQL SSL connections required
- [ ] Redis password complexity and TLS
- [ ] MinIO access policies (not root creds)

---

#### US-10.7.3: Secret Management
**As a** platform operator  
**I want** secrets managed externally, not in .env files  
**So that** credentials are secure and auditable

**Acceptance Criteria:**
- [ ] Kubernetes Secrets + sealed-secrets for all credentials
- [ ] Documentation for Vault/AWS KMS integration
- [ ] Secret rotation procedure documented
- [ ] Standardized secret naming convention
- [ ] No secrets in git history

---

#### US-10.7.4: Enhanced PII Handling
**As a** compliance officer  
**I want** comprehensive PII detection and policy enforcement  
**So that** we meet regulatory requirements

**Acceptance Criteria:**
- [ ] PII presence tagged in `doc_metadata` and `chunk_metadata`
- [ ] Per-tenant PII policies:
  - Searchable or not
  - Masked in retrieval context
- [ ] Input guardrails: detect PII in queries, optionally refuse
- [ ] Output guardrails: PII redaction when context contains PII
- [ ] Audit log of PII detections

---

#### US-10.7.5: Comprehensive Audit Logging
**As a** compliance officer  
**I want** immutable audit logs of all data access  
**So that** we can demonstrate compliance

**Acceptance Criteria:**
- [ ] Append-only audit log per tenant
- [ ] Log: who queried, when, which documents referenced (by ID)
- [ ] Log: document ingestion/deletion events
- [ ] Log retention policy (configurable per tenant)
- [ ] Export capability for compliance reporting

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
**Focus:** Data consistency and resilience

| Story | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| US-10.1.1 | P0 | M | None |
| US-10.1.3 | P0 | S | US-10.1.1 |
| US-10.1.4 | P0 | M | None |
| US-10.2.1 | P0 | L | None |
| US-10.2.4 | P0 | S | None |

### Phase 2: Observability & DX (Weeks 3-4)
**Focus:** Cross-service visibility and developer tools

| Story | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| US-10.3.1 | P1 | M | None |
| US-10.3.2 | P1 | M | US-10.3.1 |
| US-10.3.3 | P1 | M | None |
| US-10.6.1 | P2 | M | None |
| US-10.6.3 | P2 | S | None |

### Phase 3: Modern RAG & Cost (Weeks 5-6)
**Focus:** Quality improvements and optimization

| Story | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| US-10.4.1 | P1 | L | None |
| US-10.4.2 | P1 | S | US-10.4.1 |
| US-10.5.1 | P1 | M | None |
| US-10.5.2 | P1 | M | None |
| US-10.5.3 | P1 | M | None |

### Phase 4: Security Hardening (Weeks 7-8)
**Focus:** Production readiness

| Story | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| US-10.7.1 | P0 | L | None |
| US-10.7.2 | P0 | M | None |
| US-10.7.3 | P0 | M | None |
| US-10.7.4 | P1 | M | None |
| US-10.7.5 | P1 | L | None |

---

## Success Metrics

### Reliability
- Index consistency rate > 99.9%
- E2E success rate > 99%
- Degraded mode activations < 1/day

### Performance
- Retrieval p95 < 250ms
- RAG E2E p95 < 2000ms
- Cache hit rate > 30%

### Quality
- Verification score > 0.8 (when enabled)
- User feedback positive rate > 80%

### Cost
- Token usage reduction > 20% via model tiering
- Reranker usage reduction > 40% for simple queries

### Security
- Zero unauthorized data access incidents
- 100% audit log coverage

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Operational complexity from degradation modes | Medium | Medium | Keep defaults simple; clear documentation; dashboard visibility |
| Latency increase from verification | Medium | Medium | Make verification optional; strict latency budget; tenant opt-in |
| Index reconciliation overhead | Low | Medium | Low priority queue; rate limiting; off-peak scheduling |
| Security hardening breaks existing integrations | Medium | High | Staged rollout; feature flags; thorough testing |

---

## Future Considerations

When certain triggers occur, consider these advanced enhancements:

1. **Graph RAG / Knowledge Graph**
   - Trigger: Entity-centric queries underperforming
   - Build lightweight KG overlay in Postgres/Neo4j

2. **Dedicated Evaluation Service**
   - Trigger: Need for auto-tuned retrieval parameters
   - Consumes logs, RAGAS results, user feedback

3. **Per-Tenant Dedicated Indices**
   - Trigger: Large tenants (>100M chunks) causing contention
   - Migrate to tenant-specific Qdrant/OpenSearch clusters

4. **Online Learning-to-Rank**
   - Trigger: Need for personalization beyond static reranking
   - Replace static reranker with tenant-specific LTR model

---

## Appendix: Effort Legend

| Symbol | Meaning | Duration |
|--------|---------|----------|
| S | Small | < 1 day |
| M | Medium | 1-3 days |
| L | Large | 1-2 weeks |
| XL | Extra Large | > 2 weeks |
