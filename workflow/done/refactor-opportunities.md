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

## ~~HIGH - Python Orchestrator Issues~~ RESOLVED

### ~~7. Mixed logging: `logging` vs `structlog`~~ DONE

- **Fixed:** Converted 62 Python files from `import logging` / `logging.getLogger(__name__)` to `import structlog` / `structlog.get_logger(__name__)`. 5 logging infrastructure files (`observability/logging/` and `audit/logger.py`) intentionally kept with stdlib `logging` as they extend `logging.Handler`/`logging.Filter` classes.

### ~~8. URL configuration duplication in `services/orchestrator/config/urls.py`~~ DONE

- **Fixed:** Created `_make_service_url(env_var, host_key, port_key)` factory function. 15 standard getter functions now delegate to it, reducing the file from 566 to ~390 lines. Special cases (postgres, redis, celery, qdrant_grpc, minio, llm_gateway) retain custom logic. All function signatures and return values unchanged.

### ~~9. Broken symlink causing tooling failures~~ DONE

- **Fixed:** Removed the `services/orchestrator/orchestrator` symlink that pointed to `.` (itself).

---

## MEDIUM - Cross-Cutting Concerns

### ~~10. Health check response formats differ across all services~~ DONE

- **Fixed:** Created shared `HealthResponse`, `ComponentHealth`, `LivenessResponse`, `ReadinessResponse` in `rag-types`. Updated rag-ingestion, rag-retrieval, and rag-embedding to use the shared types with builder pattern (`healthy()`, `degraded()`, `with_component()`, `with_capability()`). Python orchestrator retains its own Pydantic model but follows the same field structure.

### ~~11. Dual auth systems never integrated~~ DONE

- **Fixed:** Aligned Rust `rag-auth` Role enum with Python's 8-role hierarchy (anonymous, user, analyst, engineer, tenant_admin, admin, super_admin, service). Added backward-compatible `FromStr` mapping for legacy role names (reader→user, writer→engineer). Updated `is_admin()` to recognize `tenant_admin`. Token claims structure (sub, tenant_id, roles, groups, permissions, token_type) was already wire-compatible between Rust and Python — both serialize as the same JWT payload. Both sides use RS256 with matching issuer/audience defaults.

### ~~12. Search type duplication between shared and service crates~~ DONE

- **Fixed:** Removed duplicate `SearchMode` enum from `rag-retrieval/src/types.rs`. It now re-exports `rag_types::SearchMode` as the single canonical definition. Added `uses_semantic()` and `uses_keyword()` helper methods to the rag-types version. API-layer request/response types (`RetrieveRequest`, `RetrieveResponse`) intentionally kept separate since they have HTTP-specific validation and slightly different field types.

### ~~13. Large files in retrieval crate~~ DONE

- **Fixed:** Split three large files into focused sub-modules:
  - `acl/filter.rs` (1,204 lines) → `acl/types.rs` (filter primitives: `MatchType`, `FilterCondition`, `UnifiedFilter`, `HasACLFields`) + `acl/filter.rs` (ACL logic + tests)
  - `hybrid/pipeline.rs` (955 lines) → `hybrid/pipeline_config.rs` (`PipelineConfig`, `SearchOptions`, `SearchPipelineResponse`) + `hybrid/pipeline.rs` (`SearchPipeline`, `SearchPipelineBuilder`, helpers)
  - `api/types.rs` (783 lines) → `api/requests.rs` (`RetrieveRequest`, `MultiQueryRequest`), `api/responses.rs` (`RetrievedDocument`, `RetrieveResponse`, `SearchMetrics`, `DebugInfo`), `api/validation.rs` (`ValidationError`). Thin `api/types.rs` re-exports all types for backward compatibility.

---

## ~~MEDIUM - Infrastructure~~ RESOLVED

### ~~14. Missing K8s application service manifests~~ DONE

- **Fixed:** Created Deployment + Service manifests for all 5 application services (ingestion, retrieval, orchestrator, embedding, llm-gateway) under `k8s/`. Added ServiceAccounts for embedding-service and llm-gateway to `rbac.yaml`. Updated `kustomization.yaml` to include all app service directories.

### ~~15. Duplicate ResourceQuota definitions~~ DONE

- **Fixed:** Removed duplicate ResourceQuota and LimitRange from `k8s/base/namespace.yaml`. The canonical definitions in `k8s/base/resource-quota.yaml` are now the single source of truth.

### ~~16. Missing resource limits for app services in docker-compose~~ DONE

- **Fixed:** Added `deploy.resources` (limits + reservations) for orchestrator-service (1G/256M), embedding-service (2G/512M), and frontend (256M/64M) in `docker-compose.yml`.

### ~~17. Documentation drift~~ DONE

- `docs/moon-monorepo.md` — verified all 17 listed crates actually exist in `crates/` (not a real issue)
- ~~CLAUDE.md says default embedding model is `all-MiniLM-L6-v2` but `.env.base` says `BAAI/bge-large-en-v1.5`~~ FIXED (`.env.base` now matches)
- **Fixed:** CLAUDE.md referenced wrong env var `MODEL_NAME`, corrected to `EMBEDDING_MODEL`
- **Fixed:** Health check spec updated to mark `/health/startup` as recommended (not required) with a note to use `/health` for startup probes when not implemented

---

## ~~LOW - Cleanup Opportunities~~ RESOLVED

### ~~18. Dead code warnings in `crates/rag-cache/src/cache.rs`~~ DONE

- **Fixed:** The crate was restructured — `cache.rs` no longer exists. `DEFAULT_TTL` was replaced by `CacheConfig::default_ttl_secs` with proper serde defaults. `new()` and `with_ttl()` are now part of `CacheConfig`. No dead code warnings remain.

### ~~19. Mixed type hint styles in Python (187 `Optional/Union` vs 1,126 `| None`)~~ DONE

- **Fixed:** Converted all 7 non-migration Python files from `Optional[X]` to PEP 604 `X | None` syntax. Added `from __future__ import annotations` to enable forward-reference support. Files updated: `observability/metrics/registry.py`, `observability/phoenix/tracer.py`, `shared/security/rbac/tenant.py`, `shared/security/jwt/handler.py`, `shared/security/rbac/permissions.py`, `shared/security/rbac/roles.py`, `shared/database/models/user.py`. Alembic migrations intentionally left unchanged.

### ~~20. TODOs in production code~~ DONE

- **Fixed:** Resolved all 3 TODOs in `services/orchestrator/api/routes/query.py`:
  - `tenant_tier`: Now extracted from `query_request.options.get("tenant_tier", "standard")`, defaulting to "standard"
  - `component_timings`: Now populated from workflow `result.get("timing", {})` (per-stage latency dict)
  - `context_relevance_score`: Now computed from top document score `documents[0].get("score")`

### ~~21. Duplicate query normalization~~ DONE

- **Fixed:** Extracted shared `normalize_query()` into `crates/rag-retrieval/src/utils.rs`. Both `cache/keys.rs` (`CacheKeyBuilder::hash_query`) and `query/cache.rs` (`QueryCache::hash_query`) now call `crate::utils::normalize_query()`. All 383 tests pass.

---

## Recommended Refactor Order

1. ~~**Config consistency** (#1, #2) - prevents runtime failures~~ DONE
2. ~~**Shared Rust utilities** (#3, #4, #5) - reduces duplication before new features~~ DONE
3. ~~**API error standardization** (#6, #10) - improves cross-service debugging~~ DONE
4. ~~**Python logging** (#7) - fixes silent failures in orchestrator~~ DONE
5. ~~**URL config cleanup** (#8) and **symlink** (#9) - quick wins~~ DONE
6. ~~**Auth integration** (#11) and **type dedup** (#12) - architectural alignment~~ DONE
7. ~~**K8s and docs** (#14-#17) - when preparing for production deployment~~ DONE
8. ~~**Cleanup** (#18-#21) - dead code, type hints, TODOs, deduplication~~ DONE
