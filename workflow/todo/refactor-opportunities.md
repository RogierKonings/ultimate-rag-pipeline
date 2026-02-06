# Codebase Refactor Opportunities

After scanning the entire codebase across Rust crates, Python orchestrator, infrastructure, and cross-cutting concerns, here are the findings organized by priority.

---

## ~~CRITICAL - Configuration Inconsistencies~~ RESOLVED

### ~~1. Embedding model three-way mismatch~~ DONE

- **Fixed:** `.env.base` updated to `EMBEDDING_MODEL=all-MiniLM-L6-v2` (384 dimensions), matching docker-compose and Qdrant collections.

### ~~2. Qdrant port mismatch across config files~~ DONE

- **Fixed:** `.env.local` and `.env.docker` updated to use gRPC port 6334. Makefile health check uses REST port 6333 (correct for HTTP health checks, added clarifying comment). `scripts/dev-health.py` also correctly uses REST 6333 for HTTP health probes.

---

## ~~HIGH - Rust Crate Duplication~~ RESOLVED

### ~~3. Duplicated HTTP client setup (8+ locations)~~ DONE

- **Fixed:** Created `rag-config::http` module with `build_http_client()` and `build_http_client_with_timeout()`. Updated rag-ingestion, rag-retrieval (embedding, reranking, hyde), and rag-llm-gateway to use the shared builder. Remaining: rag-secrets/vault.rs and rag-video/transcription.rs (don't depend on rag-config yet).

### ~~4. Duplicated retry logic with exponential backoff~~ DONE

- **Fixed:** Created `rag-config::retry::RetryPolicy` with configurable exponential backoff and ±25% jitter. Includes `execute()` method for async retry with retryable error classification. Updated rag-ingestion and rag-retrieval (embedding, reranking) to use `RetryPolicy`.

### ~~5. Inconsistent `reqwest` versions across workspace~~ DONE

- **Fixed:** Added `reqwest = { version = "0.12", ... }` to `[workspace.dependencies]` in workspace Cargo.toml. All 6 crates (rag-ingestion, rag-retrieval, rag-video, rag-auth, rag-llm-gateway, rag-secrets) now use `reqwest = { workspace = true }`.

### ~~6. Inconsistent API error types across services~~ DONE

- **Fixed:** Created shared `ApiError`, `ErrorResponse`, `ErrorBody` in `rag-types` with `axum` feature flag. Updated rag-ingestion and rag-retrieval to re-export from rag-types. Embedding and LLM gateway intentionally keep OpenAI-compatible error format.

---

## HIGH - Python Orchestrator Issues — PARTIALLY RESOLVED (#7 done, #8-#9 remaining)

### ~~7. Mixed logging: `logging` vs `structlog`~~ DONE

- **Fixed:** Converted 62 Python files from `import logging` / `logging.getLogger(__name__)` to `import structlog` / `structlog.get_logger(__name__)`. 5 logging infrastructure files (`observability/logging/` and `audit/logger.py`) intentionally kept with stdlib `logging` as they extend `logging.Handler`/`logging.Filter` classes.

### 8. URL configuration duplication in `services/orchestrator/config/urls.py` (566 lines)
~25 getter functions follow the identical pattern:
```python
def get_service_url() -> str:
    explicit = os.getenv("SERVICE_URL")
    if explicit: return explicit
    host = _get_host("service")
    port = _get_port("service")
    return f"http://{host}:{port}"
```

**Fix:** Single `_get_service_url(service_key, explicit_env)` factory function.

### 9. Broken symlink causing tooling failures
`services/orchestrator/orchestrator` is a symlink pointing to `.` (itself), causing `OSError: Too many levels of symbolic links` during directory traversal.

**Fix:** Remove the symlink.

---

## MEDIUM - Cross-Cutting Concerns

### ~~10. Health check response formats differ across all services~~ DONE

- **Fixed:** Created shared `HealthResponse`, `ComponentHealth`, `LivenessResponse`, `ReadinessResponse` in `rag-types`. Updated rag-ingestion, rag-retrieval, and rag-embedding to use the shared types with builder pattern (`healthy()`, `degraded()`, `with_component()`, `with_capability()`). Python orchestrator retains its own Pydantic model but follows the same field structure.

### 11. Dual auth systems never integrated
- **Rust**: `rag-auth` crate with full JWT/RBAC implementation
- **Python**: `shared/security/` with 12 subdirectories (acl, jwt, rbac, pii, encryption, secrets, tls...)
- These implement the same concepts independently without a shared contract

**Fix:** Define auth token format once; have Python validate Rust-issued JWTs (or vice versa).

### 12. Search type duplication between shared and service crates
- `rag-types` defines `SearchRequest`, `SearchMode`, `SearchResult`
- `rag-retrieval` API layer redefines `RetrieveRequest`, `RetrieveResponse`, `RetrievedDocument` with nearly identical structure

**Fix:** Use `rag-types::SearchRequest` directly in the retrieval API layer.

### 13. Large files in retrieval crate
| File | Lines | Issue |
|------|-------|-------|
| `crates/rag-retrieval/src/acl/filter.rs` | 1,204 | Filter building + Qdrant/OpenSearch conversion |
| `crates/rag-retrieval/src/hybrid/pipeline.rs` | 955 | Pipeline orchestration + response building |
| `crates/rag-retrieval/src/api/types.rs` | 912 | Types + validation mixed |

**Fix:** Split into focused sub-modules.

---

## MEDIUM - Infrastructure

### 14. Missing K8s application service manifests
`k8s/base/` only has infrastructure (postgres, qdrant, opensearch, redis, minio). No Deployment manifests for the 5 application services (ingestion, retrieval, orchestrator, embedding, llm-gateway).

### 15. Duplicate ResourceQuota definitions
- `k8s/base/namespace.yaml`: 40Gi memory limit
- `k8s/base/resource-quota.yaml`: 80Gi memory limit

### 16. Missing resource limits for app services in docker-compose
Only ingestion and retrieval have `deploy.resources` defined. Embedding, orchestrator, and frontend have none.

### 17. Documentation drift
- `docs/moon-monorepo.md` lists crates that don't exist (rag-video, rag-encryption, rag-tenant, rag-secrets in docs but not all actually present)
- ~~CLAUDE.md says default embedding model is `all-MiniLM-L6-v2` but `.env.base` says `BAAI/bge-large-en-v1.5`~~ FIXED (`.env.base` now matches)
- Health check spec defines `/health/startup` endpoint that no service implements

---

## LOW - Cleanup Opportunities

### 18. Dead code warnings in `crates/rag-cache/src/cache.rs`
`DEFAULT_TTL` constant, `new()`, `with_ttl()` methods flagged as unused.

### 19. Mixed type hint styles in Python (187 `Optional/Union` vs 1,126 `| None`)
Standardize on PEP 604 (`| None`) syntax.

### 20. TODOs in production code
`services/orchestrator/api/routes/query.py`:
- Line 195: `tenant_tier="standard",  # TODO: Get from tenant config`
- Line 197: `component_timings={},  # TODO: Collect from workflow state`
- Line 199: `context_relevance_score=None,  # TODO: Get from reranker scores`

### 21. Duplicate query normalization
Identical `normalize_query()` (trim + lowercase) exists in both:
- `crates/rag-retrieval/src/cache/keys.rs`
- `crates/rag-retrieval/src/query/cache.rs`

---

## Recommended Refactor Order

1. ~~**Config consistency** (#1, #2) - prevents runtime failures~~ DONE
2. ~~**Shared Rust utilities** (#3, #4, #5) - reduces duplication before new features~~ DONE
3. ~~**API error standardization** (#6, #10) - improves cross-service debugging~~ DONE
4. ~~**Python logging** (#7) - fixes silent failures in orchestrator~~ DONE
5. **URL config cleanup** (#8) and **symlink** (#9) - quick wins
6. **Auth integration** (#11) and **type dedup** (#12) - architectural alignment
7. **K8s and docs** (#14-#17) - when preparing for production deployment
