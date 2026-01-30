# Codebase Concerns

**Analysis Date:** 2026-01-30

## Tech Debt

### Stub/Placeholder Implementations

**Query Expansion Not Implemented:**
- Issue: Query expansion feature exists but returns empty results, effectively disabled
- Files: `crates/rag-retrieval/src/query/expander.rs` (lines 342-355)
- Impact: LLM-based query expansion cannot generate alternative search terms. This reduces retrieval quality for complex queries that would benefit from semantic rephrasing.
- Fix approach: Implement actual LLM call to gateway, parse response to extract 3-5 alternative queries per input

**Cache Lookup Not Implemented:**
- Issue: Query result caching is stubbed with `cache_hit = false` always returning cache miss
- Files: `crates/rag-retrieval/src/hybrid/pipeline.rs` (lines 554-557)
- Impact: Zero cache hits means 100% of queries hit search backends even for identical queries. Doubles latency for repeated queries.
- Fix approach: Implement cache key generation (hash of query+filters), Redis cache lookup before search, cache storage after reranking (lines 743)

**HyDE (Hypothetical Document Embeddings) Not Implemented:**
- Issue: Feature flagged and stubbed to return None, generator not called
- Files: `crates/rag-retrieval/src/hybrid/pipeline.rs` (lines 602-603)
- Impact: Cannot generate synthetic documents for improved semantic search on complex queries
- Fix approach: Implement async LLM generator, integrate with embedding client for document generation

**Video Embedding Generation Placeholder:**
- Issue: Generates fake embeddings based on content hash instead of calling embedding service
- Files: `crates/rag-video/src/pipeline/executor.rs` (lines 432-443)
- Impact: Video chunks cannot be properly retrieved by semantic search, all similarity scores will be meaningless
- Fix approach: Implement HTTP client call to embedding service (8080) with proper error handling

### Document Management API Stubs

**Ingestion Service Document Operations Not Implemented:**
- Issue: Multiple document endpoints return empty/error responses or no-ops
- Files: `crates/rag-ingestion/src/api/routes/documents.rs` (lines 64-175)
  - `list_documents`: Returns empty list (line 64)
  - `get_sync_status`: Returns empty response (line 83)
  - `get_document`: Always returns 404 (line 100)
  - `delete_document`: Returns 404 (line 114)
  - `batch_delete_documents`: Returns all items as not found (line 141)
  - `reindex_document`: Returns stub job ID (line 172)
- Impact: Cannot list, retrieve, delete, or manage documents via API. Users have no visibility into ingested documents.
- Fix approach: Implement database queries for each endpoint using existing document schema

**Ingest Routes Job Tracking Stubbed:**
- Issue: Routes accept ingest requests but don't spawn actual processing tasks
- Files: `crates/rag-ingestion/src/api/routes/ingest.rs` (lines 38, 66, 185, 220)
- Impact: Ingest API endpoints return immediately with job IDs but never process documents. Documents are never indexed.
- Fix approach: Spawn async worker tasks via Redis queue, implement task handler pipeline

### Missing Metrics Collection

**Query Metrics Incomplete:**
- Issue: Multiple TODO placeholders for metrics that never get populated
- Files: `services/orchestrator/api/routes/query.py` (lines 277, 284-285)
  - `tenant_tier`: Hardcoded to "standard" instead of fetching from tenant config
  - `component_timings`: Empty dict instead of per-node timings from workflow
  - `context_relevance_score`: Always None instead of getting from reranker scores
- Impact: Metrics are incomplete, making it impossible to measure query quality and identify degradation
- Fix approach: Extract timing from workflow state dict, add reranker score to context, load tenant tier from config service

---

## Known Bugs

### Cache Key Generation Missing

**Redis Cache Invalidation Problem:**
- Problem: Cache operations reference undefined key generation logic
- Files: `crates/rag-retrieval/src/query/cache.rs` (line 388 comment)
- Trigger: When trying to clear specific cached queries or implement cache expiration
- Workaround: Rely on TTL expiration only, no targeted cache invalidation possible
- Fix: Implement deterministic cache key generation from query+filters+weights

### Query Expansion Expansion Terms Unused

**Expanded Terms Dead Code:**
- Problem: Query expansion generates terms but they're never used in search
- Files: `crates/rag-retrieval/src/hybrid/pipeline.rs` (line 599)
  - `let _ = &expanded_terms;` suppresses unused variable warning
  - Expanded terms exist in debug output but aren't passed to search functions
- Trigger: When expansion is enabled, generated terms don't affect search results
- Workaround: Disable expansion feature since it has no effect
- Fix: Pass expanded_terms to searcher and incorporate into hybrid search

---

## Security Considerations

### Debug Logging in Production

**DEBUG Log Level Set by Default in Docker:**
- Risk: Debug logs expose internal query details, tenant data, and system state
- Files:
  - `docker-compose.yml` (line 245): `LOG_LEVEL=DEBUG`
  - `.env.base` (line 119): `DEBUG=true`
  - `.env.docker` (line 86, 94): `INGESTION_DEBUG=true`, `RETRIEVAL_LOG_LEVEL=DEBUG`
  - `k8s/overlays/dev/kustomization.yaml` (line 16): `LOG_LEVEL=DEBUG`
- Current mitigation: None - production deployment would use same defaults
- Recommendations:
  - Set `LOG_LEVEL=INFO` in production configs
  - Implement separate config for prod vs dev environments
  - Never commit debug=true to production overlay
  - Add pre-deployment validation to fail if LOG_LEVEL != INFO in prod

### Hardcoded Default Credentials

**Default Service Credentials Exposed:**
- Risk: Docker compose and examples use default/weak credentials
- Files:
  - `docker-compose.yml` (lines 116-117): MinIO `minioadmin/minioadmin123`
  - `docker-compose.yml` (line 30): PostgreSQL `ragpass` default password
  - `.env.example` (lines 27-42): All default credentials documented
  - `.env.base` (lines 41-42): `REDIS_PASSWORD=ragredis` in base config
- Current mitigation: `.env.example` is not committed to runtime
- Recommendations:
  - Document that `.env` must never be committed
  - Generate random credentials in setup scripts
  - Add pre-commit hook to catch `.env` files
  - Use secrets management (AWS Secrets Manager, HashiCorp Vault) for prod

### OpenSearch Security Disabled

**OpenSearch Plugin Security Disabled:**
- Risk: Production deployment exposes unprotected search index with document content
- Files: `docker-compose.yml` (line 57): `DISABLE_SECURITY_PLUGIN=true`
- Current mitigation: Only in docker-compose for local dev
- Recommendations:
  - Implement OpenSearch authentication in production k8s manifests
  - Add role-based access control (RBAC) for tenant isolation
  - Verify security plugin enabled in production kustomization

### PII Detection Has Coverage Gaps

**SSN and Credit Card Patterns Incomplete:**
- Risk: Some PII formats won't be detected due to regex gaps
- Files: `services/orchestrator/guardrails/detection.py` (lines 87-99)
  - SSN pattern requires dashes/spaces (won't match `123456789`)
  - Credit card patterns require separators (won't match continuous 16-digit)
  - No detection for: Bank account numbers, routing numbers, passport numbers
- Current mitigation: PII detection runs but is incomplete
- Recommendations:
  - Add patterns for continuous digit sequences (12-16 digits)
  - Add international phone formats
  - Add bank account patterns (US routing/account)
  - Validate patterns against OWASP PII list

### JWT Token Blocklist Not Implemented

**Token Revocation Missing:**
- Risk: Logged-out tokens remain valid until natural expiration
- Files: `workflow/done/07-security-compliance/US-7.1-jwt-authentication.md` (line 599)
- Current mitigation: None - stateless JWT means logout is client-only
- Recommendations:
  - Implement Redis-based token blocklist
  - Add logout endpoint that adds token to blocklist
  - Check blocklist on every protected request
  - Set blocklist TTL to token expiration time

---

## Performance Bottlenecks

### Vector Similarity Computation Not Optimized

**Embedding Normalization May Be Missing:**
- Problem: Cosine similarity requires unit vectors; if embeddings aren't normalized, scores will be incorrect
- Files: `crates/rag-retrieval/src/hybrid/pipeline.rs` (line 613-616) - embedding client called but normalization not shown
- Cause: Depends on embedding service normalization behavior
- Improvement path:
  - Verify embedding service normalizes outputs (fastembed should)
  - Add normalization in retrieval service as safety net
  - Document assumption in architecture

### Reranking Bottleneck

**Cross-Encoder Batch Size Fixed:**
- Problem: Reranker processes top-50 documents sequentially for each query
- Files: Configuration suggests batch processing but actual implementation details unknown
- Cause: ONNX-based reranker may not support large batches
- Improvement path:
  - Profile reranker latency on typical batch sizes
  - Implement adaptive batching based on document count
  - Consider async reranking while user sees partial results
  - Target: Reranking should be <150ms (8000ms timeout budget)

### Memory Cache Not Integrated

**Query Caching Not Working:**
- Problem: Redis connection exists but cache lookups never execute
- Files: `crates/rag-retrieval/src/hybrid/pipeline.rs` (lines 554-557)
- Cause: Cache lookup stubbed
- Improvement path: Implement full cache pipeline with:
  - Cache key generation (query hash + filter hash)
  - TTL based on query type (short for time-sensitive, long for reference)
  - Cache invalidation on document updates
  - Metrics for cache hit rate

---

## Fragile Areas

### Hybrid Search Fusion Algorithm

**Files:** `crates/rag-retrieval/src/hybrid/mod.rs` and fusion logic

**Why fragile:**
- Reciprocal Rank Fusion (RRF) combines two independently ranked lists
- Weight parameter (semantic 0.7 / keyword 0.3) is hardcoded, not adaptive
- If semantic or keyword search returns 0 results, RRF breaks (division by zero risk)
- No handling for tied scores during reranking

**Safe modification:**
- Always test with edge cases: empty semantic results, empty keyword results, identical scores
- Verify RRF formula preserves ranking quality when weights change
- Add logging for fusion metrics (before/after scores)
- Test coverage: 3 integration tests exist but missing edge cases

### LLM Gateway Fallback Chain

**Files:** `services/orchestrator/resilience/fallbacks.py` and circuit breaker

**Why fragile:**
- Circuit breaker state machine has 3 states (closed/open/half-open)
- Timeout during half-open can cause state corruption
- No validation that fallback handlers exist before calling
- Fallback response "I apologize..." is indistinguishable from real LLM response

**Safe modification:**
- All circuit state transitions must be atomic
- Add validation in constructor that all fallback handlers are callable
- Implement fallback context (prefix with `[Fallback Mode]` for transparency)
- Test coverage: Exists but missing concurrent state transition tests

### Session Memory Store Coordination

**Files:** `services/orchestrator/memory/session.py` and `memory/persistence.py`

**Why fragile:**
- Sessions can exist in 3 places: Redis (cache), PostgreSQL (persistent), in-memory
- No guaranteed consistency between layers
- Redis TTL expiration happens independently of PostgreSQL cleanup
- No transaction guarantees if service crashes during write

**Safe modification:**
- Always read from PostgreSQL as source of truth on Redis miss
- Implement dual-write pattern: update both Redis and Postgres in transaction
- Add integrity checks (verify session exists in expected store before use)
- Test coverage: Exists but missing failure scenario tests

**Test coverage:** Missing tests for:
- Redis connection loss during session update
- PostgreSQL connection loss during persistence
- Session state mismatch between Redis/Postgres

---

## Scaling Limits

### Ingestion Queue Unbounded Memory

**Resource:** Redis-backed async worker system

**Current capacity:** Default Redis maxmemory: 512MB

**Limit:** Will hit 512MB with ~100k pending ingestion jobs (assuming ~5KB per job metadata)

**Scaling path:**
- Implement job batching (group small documents)
- Add Dead Letter Queue (DLQ) handler for failed jobs
- Implement job priority (FIFO vs priority queue)
- Monitor queue depth, alert at 70% capacity
- Consider separate Redis instance for job queue

### Vector Database Collection Size

**Resource:** Qdrant HNSW index

**Current capacity:** Untested, depends on storage but assume 10M vectors addressable

**Limit:** Beyond 10M vectors, search latency degrades, index rebuild becomes expensive

**Scaling path:**
- Implement collection sharding by tenant
- Archive old documents to separate collection
- Monitor query latency, auto-shard when p95 > 100ms
- Budget for index rebuild time when adding fields

### PostgreSQL Connection Pool

**Resource:** asyncpg connection pool

**Current capacity:** Default pool size 20 connections

**Limit:** 20 concurrent requests max, queries queue after that

**Scaling path:**
- Monitor pool exhaustion via metrics
- Increase pool size but verify DB can handle connections
- Implement connection multiplexing (pgBouncer)
- Add query timeout and priority queueing

---

## Dependencies at Risk

### Fastembed ONNX Runtime Compatibility

**Package:** fastembed crate + ONNX Runtime

**Risk:** ONNX Runtime 1.17+ has breaking changes in threading model, may cause deadlocks in async context

**Impact:** Embedding service hangs on high concurrency (>100 concurrent requests)

**Current mitigation:** spawn_blocking used for CPU-bound operations

**Migration plan:**
- Monitor for deadlock issues at load
- Consider alternative: `sentence-transformers` Python library with PyO3 FFI
- Ensure spawn_blocking thread pool sized correctly (default: num_cpus * 2)

### LangGraph Version Lock

**Package:** LangGraph Python dependency

**Risk:** Major version bump (0.x to 1.x) planned for Q2 2025, will require rewrite of workflow graph

**Impact:** Orchestrator workflow incompatible, must upgrade and retest all 883 tests

**Current mitigation:** Lock to 0.x in requirements.txt

**Migration plan:**
- Plan upgrade after 1.0 release is stable (3+ months)
- Allocate 2-3 weeks for migration and testing
- Test new graph API in branch before merging
- Document state machine changes for new version

### Qdrant API Stability

**Package:** Qdrant vector database

**Risk:** Qdrant 1.x roadmap includes breaking changes to payload schema (filtering logic), may break document filtering

**Impact:** Document ACL filtering breaks, potential data visibility issues

**Current mitigation:** Payload schema is stable in 1.16.3

**Migration plan:**
- Pin Qdrant version in docker-compose
- Monitor release notes for breaking changes
- Test new versions in staging before production upgrade
- Implement schema migration if payload filtering changes

---

## Missing Critical Features

### Document ACL Filtering Not Enforced

**Problem:** ACL fields exist in Qdrant (`visibility`, `allowed_groups`) but filtering not implemented in search

**Blocks:** Multi-tenant document access control, cannot safely share documents

**Workaround:** Apply ACL in orchestrator service after retrieval (inefficient)

**Priority:** High - security critical for multi-tenant deployments

### Query Expansion Integration Incomplete

**Problem:** Query expander exists but results never used in search

**Blocks:** Cannot improve recall on ambiguous queries

**Workaround:** Users must phrase queries very specifically

**Priority:** Medium - improves UX but not blocking

### Reranker Score Extraction Missing

**Problem:** Reranker runs but scores not returned to caller

**Blocks:** Cannot track context relevance metrics or filter low-quality results

**Workaround:** Trust top-K from reranker without quality visibility

**Priority:** Medium - affects observability

---

## Test Coverage Gaps

### Ingestion Service API Not Tested

**Untested area:** All document management endpoints (list, get, delete, reindex)

**Files:** `crates/rag-ingestion/src/api/routes/documents.rs` (entire file)

**Risk:** Endpoints return mock data, would immediately fail in integration

**Priority:** High - critical path for document lifecycle management

### Cache Invalidation Not Tested

**Untested area:** Cache eviction, TTL expiration, key collision handling

**Files:** `crates/rag-retrieval/src/query/cache.rs` (entire invalidation logic)

**Risk:** Cache corruption or stale results in production

**Priority:** High - affects consistency

### Video Ingestion Pipeline Not Tested

**Untested area:** Video chunking, transcription, embedding generation

**Files:** `crates/rag-video/src/pipeline/executor.rs` (lines 427-443)

**Risk:** Video feature completely untested, would fail on first use

**Priority:** Medium - feature is new, not production-critical yet

### Fallback Behavior Under Load Not Tested

**Untested area:** Circuit breaker behavior with concurrent failures

**Files:** `services/orchestrator/resilience/circuit_breaker.py`

**Risk:** Circuit may get stuck open or exhibit race conditions

**Priority:** High - resilience critical under failure

### Multi-Tenant Isolation Not Tested

**Untested area:** Tenant field propagation through all services, ACL enforcement

**Files:** All services

**Risk:** Potential data leakage between tenants

**Priority:** Critical - security issue

---

## Deployment Concerns

### Missing Ingestion Service Dockerfile

**Issue:** Ingestion service Rust code complete but no Dockerfile provided

**Files:** `docker-compose.yml` (lines 145-174) - Dockerfile reference commented out with TODO

**Current situation:** Cannot deploy ingestion service in Docker, must run manually

**Fix:** Create `crates/rag-ingestion/Dockerfile` with:
- Multi-stage build (Rust build + runtime)
- Proper health check
- Environment variable defaults

### Kubernetes Deployment Missing LLM Gateway

**Issue:** LLM Gateway service (port 8004) in docker-compose but not in k8s manifests

**Files:** `k8s/base/` - no deployment for llm-gateway

**Current situation:** K8s deployments cannot use LLM Gateway, must fall back to direct Ollama

**Fix:** Add LLM Gateway deployment to base manifests with:
- Ingress routing
- Service definition
- ConfigMap for model configuration

### Database Migration Manual Process

**Issue:** Alembic migrations must be run manually before deployment

**Files:** Migrations in `services/orchestrator/shared/database/migrations/versions/`

**Current situation:** Deployment runbook requires manual migration step, risk of skipped upgrades

**Fix:**
- Add init container to orchestrator deployment that runs migrations
- Implement migration validation in health checks
- Add version check to fail startup if migration pending

---

*Concerns audit: 2026-01-30*
