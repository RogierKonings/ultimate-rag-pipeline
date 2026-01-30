# Rust Migration Plan for services/shared

## Overview

This document outlines the plan to migrate `services/shared/` code to Rust, keeping only Python code needed by the orchestrator service (which remains in Python).

## Current State Analysis

### Rust Crates Already Implemented

| Crate | Covers |
|-------|--------|
| `rag-types` | Core types (Document, Chunk, Embedding, Video, Search, IDs, Errors) |
| `rag-config` | Timeouts, common config, ingestion/retrieval config |
| `rag-database` | PostgreSQL pool, connection, document/chunk repositories |
| `rag-cache` | Redis client, embedding cache, key builder |
| `rag-storage` | S3/MinIO client |
| `rag-search` | OpenSearch client, query builder, models |
| `rag-vectorstore` | Qdrant client, filters, models |
| `rag-auth` | JWT handler, claims, blocklist, service auth |
| `rag-telemetry` | Tracing, metrics initialization |
| `rag-ingestion` | Full service (PII detection, chunking, parsers, worker) |
| `rag-retrieval` | Full service (ACL, fusion, reranking, hybrid search) |

### services/shared Categories

#### Category 1: Already in Rust (DELETE Python)

These modules are fully implemented in Rust crates and can be deleted:

| Python Module | Rust Equivalent | Action |
|---------------|-----------------|--------|
| `shared/cache/redis_client.py` | `rag-cache/src/client.rs` | Delete |
| `shared/cache/embedding_cache.py` | `rag-cache/src/embedding.rs` | Delete |
| `shared/cache/key_builder.py` | `rag-cache/src/keys.rs` | Delete |
| `shared/cache/query_cache.py` | `rag-retrieval/src/cache/` | Delete |
| `shared/storage/s3_client.py` | `rag-storage/src/client.rs` | Delete |
| `shared/search/opensearch_client.py` | `rag-search/src/client.rs` | Delete |
| `shared/search/index_manager.py` | `rag-search/src/` | Delete |
| `shared/vectorstore/qdrant_client.py` | `rag-vectorstore/src/client.rs` | Delete |
| `shared/vectorstore/collection_manager.py` | `rag-vectorstore/src/` | Delete |
| `shared/config/timeouts.py` | `rag-config/src/timeouts.rs` | Delete |

#### Category 2: Move to Orchestrator (Python-only)

These modules are only used by the Python orchestrator service:

| Module | Reason | Action |
|--------|--------|--------|
| `shared/observability/` | OTel Python SDK, Phoenix, LangGraph callbacks | Move to `services/orchestrator/observability/` |
| `shared/security/audit/` | FastAPI middleware, SQLAlchemy-based | Move to `services/orchestrator/audit/` |
| `shared/observability/correlation/` | FastAPI middleware for correlation IDs | Move to `services/orchestrator/correlation/` |
| `shared/observability/phoenix/` | Phoenix LLM observability (Python-only) | Move to `services/orchestrator/phoenix/` |
| `shared/observability/evaluation/` | Ragas evaluation framework | Move to `services/orchestrator/evaluation/` |
| `shared/observability/otel/` | Python OTel setup, span names | Move to `services/orchestrator/otel/` |
| `shared/config/urls.py` | URL helpers | Move to `services/orchestrator/config/` |
| `shared/config/defaults.py` | Chunking/embedding/retrieval defaults | Move to `services/orchestrator/config/` |
| `shared/config/validation.py` | Config validation | Move to `services/orchestrator/config/` |
| `shared/resilience/` | Async retry logic | Move to `services/orchestrator/resilience/` |

#### Category 3: Needs Rust Implementation

These modules need to be rewritten in Rust for use by Rust services:

| Module | Rust Crate | Priority | Complexity |
|--------|------------|----------|------------|
| `shared/security/rbac/` | `rag-auth` (extend) | High | Medium |
| `shared/security/encryption/` | New: `rag-encryption` | Medium | Medium |
| `shared/security/secrets/` | New: `rag-secrets` | Medium | High |
| `shared/security/tls/` | `rag-config` (extend) | Low | Low |
| `shared/database/models/user.py` | `rag-database` (extend) | High | Medium |
| `shared/database/models/audit.py` | `rag-database` (extend) | Medium | Low |
| `shared/database/models/video.py` | `rag-database` (extend) | High | Medium |
| `shared/database/models/usage.py` | `rag-database` (extend) | Low | Low |
| `shared/database/models/feedback.py` | `rag-database` (extend) | Low | Low |
| `shared/tenant/config_service.py` | New: `rag-tenant` | High | Medium |

#### Category 4: Keep as Infrastructure

These are infrastructure/deployment concerns that stay as-is:

| Module | Reason |
|--------|--------|
| `shared/database/migrations/` | Alembic migrations (infrastructure) |
| `shared/observability/alerting/` | Alertmanager configs (YAML) |
| `shared/observability/grafana/` | Grafana dashboards (JSON) |

---

## Migration Phases

### Phase 1: Delete Already-Migrated Python Code

**Goal:** Remove Python code that has Rust equivalents

**Tasks:**
1. Delete `services/shared/cache/` (entire directory)
2. Delete `services/shared/storage/` (entire directory)
3. Delete `services/shared/search/` (entire directory)
4. Delete `services/shared/vectorstore/` (entire directory)
5. Delete `services/shared/config/timeouts.py`
6. Update any remaining Python imports that referenced these

**Verification:**
- Run `cargo test` for all Rust crates
- Ensure orchestrator doesn't import deleted modules

---

### Phase 2: Move Orchestrator-Only Code

**Goal:** Move Python modules only used by orchestrator to `services/orchestrator/`

**Tasks:**

1. **Move observability modules:**
   ```
   services/shared/observability/ → services/orchestrator/observability/
   ```
   - Keep: `otel/`, `phoenix/`, `evaluation/`, `correlation/`, `metrics/`, `logging/`
   - Delete: `grafana/`, `alerting/` (move to `k8s/` or `config/`)

2. **Move security/audit:**
   ```
   services/shared/security/audit/ → services/orchestrator/audit/
   ```

3. **Move config helpers:**
   ```
   services/shared/config/urls.py → services/orchestrator/config/urls.py
   services/shared/config/defaults.py → services/orchestrator/config/defaults.py
   services/shared/config/validation.py → services/orchestrator/config/validation.py
   ```

4. **Move resilience:**
   ```
   services/shared/resilience/ → services/orchestrator/resilience/
   ```

5. **Update all imports in orchestrator:**
   - Change `from shared.X` to relative imports

**Verification:**
- Run orchestrator tests: `cd services/orchestrator && pytest`
- Ensure all imports resolve correctly

---

### Phase 3: Extend rag-database with Additional Models

**Goal:** Add missing database models to Rust

**Tasks:**

1. **User management models** (`rag-database/src/models/`):
   - `user.rs` - User, Group, Tenant, ApiKey, Role
   - `user_repository.rs` - CRUD operations

2. **Video models** (if not already complete):
   - `video.rs` - SourceVideo, VideoTranscript, VideoKeyframe
   - `video_repository.rs` - CRUD operations

3. **Audit models:**
   - `audit.rs` - AuditLog model
   - `audit_repository.rs` - CRUD operations

4. **Usage tracking:**
   - `usage.rs` - TokenUsage, TenantQuota
   - `usage_repository.rs` - CRUD operations

5. **Feedback models:**
   - `feedback.rs` - QueryFeedback
   - `feedback_repository.rs` - CRUD operations

**Files to create/modify:**
```
crates/rag-database/src/
├── models/
│   ├── mod.rs (update)
│   ├── user.rs (new)
│   ├── video.rs (new or update)
│   ├── audit.rs (new)
│   ├── usage.rs (new)
│   └── feedback.rs (new)
├── repositories/
│   ├── mod.rs (update)
│   ├── user_repository.rs (new)
│   ├── video_repository.rs (new)
│   ├── audit_repository.rs (new)
│   ├── usage_repository.rs (new)
│   └── feedback_repository.rs (new)
```

---

### Phase 4: Extend rag-auth with RBAC

**Goal:** Add role-based access control to Rust auth crate

**Tasks:**

1. **Add RBAC types:**
   ```rust
   // crates/rag-auth/src/rbac/mod.rs
   pub mod permission;
   pub mod role;
   pub mod service;
   pub mod middleware;
   ```

2. **Implement Permission enum:**
   ```rust
   pub enum Permission {
       DocumentRead,
       DocumentWrite,
       DocumentDelete,
       QueryExecute,
       AdminAccess,
       // ...
   }
   ```

3. **Implement Role hierarchy:**
   ```rust
   pub enum Role {
       Reader,
       Writer,
       Admin,
       SuperAdmin,
   }
   ```

4. **Add authorization service:**
   ```rust
   pub struct AuthorizationService { ... }
   impl AuthorizationService {
       pub fn check_permission(&self, claims: &TokenClaims, perm: Permission) -> Result<()>;
       pub fn check_role(&self, claims: &TokenClaims, role: Role) -> Result<()>;
       pub fn check_tenant(&self, claims: &TokenClaims, tenant_id: &TenantId) -> Result<()>;
   }
   ```

5. **Add Axum middleware:**
   ```rust
   pub fn require_permission(permission: Permission) -> impl Layer;
   pub fn require_role(role: Role) -> impl Layer;
   ```

---

### Phase 5: Create rag-tenant Crate

**Goal:** Tenant configuration management for multi-tenancy

**Tasks:**

1. **Create new crate:**
   ```
   crates/rag-tenant/
   ├── Cargo.toml
   └── src/
       ├── lib.rs
       ├── config.rs      # TenantIndexConfig
       ├── service.rs     # TenantConfigService
       ├── cache.rs       # Redis-backed cache
       └── error.rs
   ```

2. **Implement TenantIndexConfig:**
   ```rust
   pub struct TenantIndexConfig {
       pub tenant_id: TenantId,
       pub qdrant_collection: String,
       pub opensearch_index: String,
       pub isolation_mode: IsolationMode,
   }
   ```

3. **Implement TenantConfigService:**
   ```rust
   pub struct TenantConfigService {
       db_pool: PgPool,
       cache: RedisClient,
   }

   impl TenantConfigService {
       pub async fn get_config(&self, tenant_id: &TenantId) -> Result<TenantIndexConfig>;
       pub async fn create_config(&self, config: TenantIndexConfig) -> Result<()>;
       pub async fn invalidate_cache(&self, tenant_id: &TenantId) -> Result<()>;
   }
   ```

---

### Phase 6: Create rag-secrets Crate (Optional)

**Goal:** Secrets management (Vault, K8s) for Rust services

**Tasks:**

1. **Create new crate:**
   ```
   crates/rag-secrets/
   ├── Cargo.toml
   └── src/
       ├── lib.rs
       ├── config.rs
       ├── vault.rs       # HashiCorp Vault client
       ├── k8s.rs         # Kubernetes secrets
       ├── env.rs         # Environment variables
       └── error.rs
   ```

2. **Implement SecretsProvider trait:**
   ```rust
   #[async_trait]
   pub trait SecretsProvider: Send + Sync {
       async fn get_secret(&self, key: &str) -> Result<String>;
       async fn get_secret_optional(&self, key: &str) -> Result<Option<String>>;
   }
   ```

3. **Implement providers:**
   - `VaultProvider` - HashiCorp Vault (using `vaultrs` crate)
   - `K8sProvider` - Kubernetes secrets (using `kube` crate)
   - `EnvProvider` - Environment variables (fallback)

---

### Phase 7: Create rag-encryption Crate (Optional)

**Goal:** Field-level encryption for sensitive data

**Tasks:**

1. **Create new crate:**
   ```
   crates/rag-encryption/
   ├── Cargo.toml
   └── src/
       ├── lib.rs
       ├── key_manager.rs
       ├── field_encryption.rs
       └── error.rs
   ```

2. **Implement encryption:**
   - Use `ring` or `aes-gcm` crate for AES-256-GCM
   - Key rotation support
   - Integration with rag-secrets for key storage

---

### Phase 8: Cleanup and Final Verification

**Goal:** Remove services/shared entirely

**Tasks:**

1. **Delete remaining shared directories:**
   - `services/shared/security/` (after verifying orchestrator has what it needs)
   - `services/shared/database/` (keep only migrations)
   - `services/shared/tenant/`

2. **Move database migrations:**
   ```
   services/shared/database/migrations/ → migrations/
   ```
   Update `alembic.ini` path accordingly.

3. **Delete empty shared directory:**
   ```
   rm -rf services/shared/
   ```

4. **Update docker-compose.yml:**
   - Remove any shared volume mounts
   - Update Python paths

5. **Update CI/CD:**
   - Remove shared module builds
   - Update test paths

**Verification:**
- All Rust tests pass: `cd crates && cargo test`
- Orchestrator tests pass: `cd services/orchestrator && pytest`
- Docker builds succeed: `docker-compose build`
- Integration tests pass: `make test`

---

## Dependency Graph

```
                    ┌─────────────┐
                    │  rag-types  │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  rag-config   │  │  rag-cache    │  │ rag-telemetry │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  rag-storage  │  │  rag-search   │  │rag-vectorstore│
└───────────────┘  └───────────────┘  └───────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  rag-database │  │   rag-auth    │  │  rag-tenant   │
│    (extend)   │  │   (extend)    │  │    (new)      │
└───────────────┘  └───────────────┘  └───────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
        ▼                                     ▼
┌───────────────┐                    ┌───────────────┐
│ rag-ingestion │                    │ rag-retrieval │
└───────────────┘                    └───────────────┘
```

---

## Timeline Estimate

| Phase | Description | Priority |
|-------|-------------|----------|
| 1 | Delete already-migrated code | High |
| 2 | Move orchestrator-only code | High |
| 3 | Extend rag-database models | High |
| 4 | Extend rag-auth with RBAC | High |
| 5 | Create rag-tenant | Medium |
| 6 | Create rag-secrets | Low |
| 7 | Create rag-encryption | Low |
| 8 | Final cleanup | High |

---

## Risk Mitigation

1. **Database migrations**: Keep Alembic migrations in Python - they're deployment infrastructure, not runtime code.

2. **Gradual migration**: Delete/move modules one at a time, running tests after each change.

3. **Feature flags**: For new Rust implementations, consider feature flags to fall back to Python if issues arise.

4. **Integration tests**: Ensure end-to-end tests cover all migrated functionality.

---

## Files to Delete (Summary)

```
services/shared/
├── cache/                    # DELETE (in rag-cache)
├── storage/                  # DELETE (in rag-storage)
├── search/                   # DELETE (in rag-search)
├── vectorstore/              # DELETE (in rag-vectorstore)
├── config/timeouts.py        # DELETE (in rag-config)
├── resilience/               # MOVE to orchestrator
├── observability/            # MOVE to orchestrator
├── security/audit/           # MOVE to orchestrator
├── security/acl/             # DELETE (in rag-retrieval)
├── security/jwt/             # Partially DELETE (in rag-auth)
├── security/rbac/            # REWRITE in rag-auth
├── security/pii/             # DELETE (in rag-ingestion)
├── security/encryption/      # REWRITE in rag-encryption (optional)
├── security/secrets/         # REWRITE in rag-secrets (optional)
├── security/tls/             # MOVE config to rag-config
├── tenant/                   # REWRITE in rag-tenant
└── database/
    ├── migrations/           # KEEP (infrastructure)
    └── models/               # REWRITE in rag-database
```
