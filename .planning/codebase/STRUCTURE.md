# Codebase Structure

**Analysis Date:** 2026-01-30

## Directory Layout

```
ultimate-rag-pipeline/
├── crates/                          # Rust workspace (polyrepo pattern)
│   ├── rag-types/                   # Shared types (Document, Chunk, SearchResult, etc.)
│   ├── rag-config/                  # Configuration loading and validation
│   ├── rag-auth/                    # JWT authentication and token handling
│   ├── rag-telemetry/               # OpenTelemetry, tracing, Prometheus
│   ├── rag-cache/                   # Redis caching client
│   ├── rag-database/                # PostgreSQL connection pooling
│   ├── rag-storage/                 # S3/MinIO object storage client
│   ├── rag-secrets/                 # Secrets management (Vault, K8s, env)
│   ├── rag-encryption/              # AES-GCM field-level encryption
│   ├── rag-tenant/                  # Multi-tenancy configuration service
│   ├── rag-vectorstore/             # Qdrant vector database client
│   ├── rag-search/                  # OpenSearch BM25 keyword search client
│   ├── rag-ingestion/               # Document ingestion pipeline service
│   ├── rag-retrieval/               # Hybrid retrieval service (semantic + keyword)
│   ├── rag-embedding/               # Embedding service (ONNX, OpenAI API)
│   ├── rag-llm-gateway/             # Unified LLM/reranker/embedding gateway
│   ├── rag-video/                   # Video processing (frames, OCR, transcription)
│   ├── Cargo.toml                   # Workspace manifest
│   └── Cargo.lock                   # Dependency lockfile (committed)
├── services/
│   └── orchestrator/                # Python orchestration service (LangGraph)
│       ├── api/                     # FastAPI routes and dependency injection
│       │   ├── routes/              # Endpoint handlers (query.py, sessions.py, health.py)
│       │   ├── models/              # Pydantic request/response schemas
│       │   ├── middleware/          # CORS, auth, logging middleware
│       │   ├── app.py               # FastAPI application factory
│       │   └── dependencies.py      # Dependency injection setup
│       ├── workflow/                # LangGraph workflow orchestration
│       │   ├── graph.py             # StateGraph definition and compilation
│       │   ├── state.py             # RAGState TypedDict schema
│       │   └── nodes/               # Workflow node implementations
│       │       ├── input_validation.py   # PII, injection, length checks
│       │       ├── routing.py            # Intent classification, strategy selection
│       │       ├── retrieval.py          # Call retrieval service
│       │       ├── multi_retrieval.py    # Multi-step retrieval decomposition
│       │       ├── prompt_building.py    # Context formatting, template rendering
│       │       ├── generation.py         # LLM call with streaming
│       │       ├── output_validation.py  # Harmful content, PII leakage detection
│       │       └── cache_check.py        # Query result caching (not in basic path)
│       ├── routing/                 # Query classification and routing
│       │   ├── router.py            # QueryRouter orchestrator
│       │   ├── classifiers.py       # Intent, complexity, strategy classifiers
│       │   └── models.py            # RoutingResult, QueryIntent, RoutingStrategy enums
│       ├── prompts/                 # Prompt templates and building
│       │   ├── builder.py           # PromptBuilder Jinja2 integration
│       │   ├── templates.py         # RAG, no_context, follow_up, citations templates
│       │   └── context.py           # Context formatting utilities
│       ├── gateway/                 # LLM and embedding service clients
│       │   ├── client.py            # ModelGateway async HTTP client
│       │   ├── streaming.py         # SSE stream parsing and event handling
│       │   └── models.py            # ChatMessage, ChatCompletionRequest/Response
│       ├── guardrails/              # Input/output validation and safety
│       │   ├── pipeline.py          # GuardrailPipeline orchestrator
│       │   ├── input.py             # PII, injection detection
│       │   ├── output.py            # Harmful content, hallucination filtering
│       │   └── detection.py         # Regex-based detection patterns
│       ├── memory/                  # Session and conversation management
│       │   ├── session.py           # SessionManager async interface
│       │   ├── store.py             # RedisSessionStore implementation
│       │   ├── persistence.py       # PostgresConversationStore (fallback)
│       │   ├── summarizer.py        # HistorySummarizer for long conversations
│       │   └── models.py            # Message, ConversationSession TypedDicts
│       ├── streaming/               # Server-Sent Events support
│       │   ├── manager.py           # StreamManager (event generation, batching)
│       │   ├── models.py            # StreamEvent, StreamEventType enums
│       │   ├── validation.py        # EventSequenceValidator
│       │   ├── metrics.py           # TTFTTracker (time-to-first-token)
│       │   └── buffer.py            # TokenBuffer for event batching
│       ├── resilience/              # Circuit breakers and fallback handlers
│       │   ├── circuit_breaker.py   # CircuitBreaker state machine
│       │   ├── fallbacks.py         # FallbackHandlers for LLM, retrieval, embedding
│       │   ├── degradation.py       # DegradationManager service status
│       │   └── config.py            # Resilience threshold configuration
│       ├── observability/           # Logging, tracing, metrics
│       │   ├── otel/                # OpenTelemetry setup and auto-instrumentation
│       │   ├── correlation.py       # Request ID propagation
│       │   └── metrics.py           # Prometheus collectors
│       ├── audit/                   # Audit logging and compliance
│       │   └── __init__.py          # AuditMiddleware for request tracking
│       ├── shared/                  # Shared Python modules (multi-service reuse)
│       │   ├── database/            # SQLAlchemy models, Alembic migrations
│       │   │   ├── models/          # Document, Chunk, Conversation, EvalRun models
│       │   │   ├── migrations/      # Alembic version history
│       │   │   └── __init__.py      # Session factory, engine initialization
│       │   ├── security/            # JWT, encryption, RBAC, PII detection
│       │   │   ├── jwt/             # Token generation, validation
│       │   │   ├── encryption/      # Field-level encryption utilities
│       │   │   ├── rbac/            # Role-based access control
│       │   │   ├── pii/             # PII detection patterns
│       │   │   ├── acl/             # Document-level ACL enforcement
│       │   │   └── secrets/         # Secrets retrieval integration
│       │   ├── tenant/              # Tenant configuration service
│       │   └── generated/           # Generated types from schemas (gRPC/protobuf)
│       ├── config.py                # OrchestratorConfig settings class
│       ├── run.py                   # Application entry point (uvicorn)
│       ├── __init__.py              # Package init
│       ├── tests/                   # 883 unit tests (96% coverage)
│       ├── requirements.txt         # Python dependencies
│       └── Dockerfile              # Container image definition
├── docs/                            # Architecture and operational documentation
│   ├── architecture.md              # System design and data flow
│   ├── infrastructure/              # Kubernetes, deployment, networking
│   ├── retrieval-service/           # Retrieval service specifics
│   ├── ingestion-service/           # Ingestion service specifics
│   ├── orchestrator-service/        # Orchestrator service specifics
│   ├── embedding-service/           # Embedding service documentation
│   ├── llm-gateway/                 # LLM gateway documentation
│   ├── observability/               # Prometheus, Jaeger, logging
│   ├── security/                    # JWT, encryption, multi-tenancy
│   ├── testing/                     # Integration test patterns
│   ├── runbooks/                    # Operational procedures
│   └── plans/                       # Planning documents (migrations, features)
├── k8s/                             # Kubernetes manifests
│   ├── base/                        # Base resources (deployments, services, configmaps)
│   └── overlays/                    # Environment-specific patches (dev/prod)
├── config/                          # Service configuration files
│   ├── prometheus/                  # Prometheus scrape configs
│   ├── grafana/                     # Grafana dashboard JSON definitions
│   └── qdrant/                      # Qdrant snapshots and config
├── scripts/                         # Initialization and utility scripts
├── init-scripts/                    # Database initialization SQL
├── docker-compose.yml               # Local development environment
├── Makefile                         # Development commands (make dev, make test, etc.)
├── CLAUDE.md                        # Project guidelines for Claude
└── README.md                        # Project overview and quick start
```

## Directory Purposes

**crates/**
- Purpose: Rust microservices and shared libraries using workspace pattern
- Contains: Service binaries (`src/bin/main.rs`), libraries (`src/lib.rs`), tests
- Key files: Each crate has `Cargo.toml`, `src/lib.rs`, `src/bin/main.rs`

**services/orchestrator/**
- Purpose: Python-based orchestration layer coordinating the RAG pipeline
- Contains: FastAPI server, LangGraph workflows, session management, guardrails
- Key files: `run.py` (entry), `api/app.py` (server), `workflow/graph.py` (state machine)

**services/orchestrator/shared/**
- Purpose: Reusable Python modules shared across orchestrator and potentially other services
- Contains: Database models (SQLAlchemy), migrations (Alembic), security utilities (JWT, encryption, RBAC, PII)
- Key files: `database/models/__init__.py` (all ORM models), `database/migrations/versions/` (schema)

**docs/**
- Purpose: Architecture, design decisions, operational procedures
- Contains: Architecture diagrams, deployment guides, runbooks, performance tuning
- Key files: `architecture.md` (comprehensive reference), `infrastructure/kubernetes-setup.md`

**k8s/**
- Purpose: Infrastructure-as-code for Kubernetes deployments
- Contains: Deployments, services, configmaps, secrets, persistent volume claims
- Key files: `base/ingestion-service.yaml`, `overlays/prod/kustomization.yaml`

**config/**
- Purpose: Configuration files for external services (Prometheus, Grafana, Qdrant)
- Contains: YAML configs, dashboard definitions
- Key files: `prometheus/prometheus.yml` (scrape targets), `grafana/dashboards/`

**scripts/**
- Purpose: Initialization, migration, and utility scripts
- Contains: Database bootstrap, index creation, health check utilities
- Key files: Scripts for creating Qdrant collections, OpenSearch indices

## Key File Locations

**Entry Points:**

- **Ingestion Service:** `crates/rag-ingestion/src/bin/main.rs`
- **Retrieval Service:** `crates/rag-retrieval/src/bin/main.rs`
- **Embedding Service:** `crates/rag-embedding/src/bin/main.rs`
- **LLM Gateway:** `crates/rag-llm-gateway/src/bin/main.rs`
- **Orchestrator Service:** `services/orchestrator/run.py`

**Configuration:**

- **Rust services:** Environment variables loaded in `crates/rag-config/src/` with validation
- **Python services:** `services/orchestrator/config.py` (Pydantic settings)
- **Shared config:** `.env`, `.env.example` (project root)
- **Database migrations:** `services/orchestrator/shared/database/migrations/versions/`

**Core Logic:**

- **Ingestion:** `crates/rag-ingestion/src/` (parsers, chunking, indexing, worker)
- **Retrieval:** `crates/rag-retrieval/src/hybrid/` (HybridSearcher), `crates/rag-retrieval/src/fusion/` (RRF/Linear/DBSF)
- **Orchestration:** `services/orchestrator/workflow/graph.py` (LangGraph), `services/orchestrator/routing/router.py` (routing)
- **Prompting:** `services/orchestrator/prompts/templates.py` (Jinja2 templates)

**Testing:**

- **Rust tests:** `crates/rag-*/tests/` (integration tests), `crates/rag-*/src/` (unit tests with `#[cfg(test)]`)
- **Python tests:** `services/orchestrator/tests/` (pytest, 883 tests, 96% coverage)
- **Test fixtures:** `services/orchestrator/tests/fixtures/` (factory functions)
- **Test configuration:** `pytest.ini`, `conftest.py`

**Shared Modules:**

- **Types:** `crates/rag-types/src/` (Document, Chunk, SearchResult, IDs)
- **Auth:** `crates/rag-auth/src/` (JWT), `services/orchestrator/shared/security/` (encryption, RBAC, PII)
- **Database:** `services/orchestrator/shared/database/` (models, migrations)
- **Telemetry:** `crates/rag-telemetry/src/` (OpenTelemetry setup)

## Naming Conventions

**Files:**

- **Rust services:** `src/bin/main.rs` (binary entry), `src/lib.rs` (library), `src/{module}/mod.rs` (module exports)
- **Rust tests:** `{name}.rs` with `#[cfg(test)]` blocks at file end, or `tests/{name}.rs` for integration tests
- **Python modules:** `{module_name}.py` (snake_case), `{module}/__init__.py` (package)
- **Python tests:** `test_{module}.py` (pytest discovery), or `{module}_test.py`
- **Config files:** YAML for k8s, TOML for Rust (Cargo.toml), JSON for Grafana dashboards

**Directories:**

- **Service crates:** `crates/rag-{service-name}/` (e.g., `rag-ingestion`, `rag-retrieval`)
- **Feature modules:** `src/{feature}/` (e.g., `src/fusion/`, `src/hybrid/`, `src/acl/`)
- **Test directories:** `tests/` at workspace root (integration tests), or `src/` for unit tests
- **API routes:** `api/routes/` with `{endpoint}.py` per major endpoint
- **Workflow nodes:** `workflow/nodes/{node_name}.py` (e.g., `routing.py`, `retrieval.py`)

## Where to Add New Code

**New Feature (e.g., new retrieval algorithm):**
- Primary code: `crates/rag-retrieval/src/` (create new module like `src/my_algorithm/`)
- Tests: `crates/rag-retrieval/tests/test_my_algorithm.rs` (integration) + `src/my_algorithm.rs` with `#[test]` (unit)
- API exposure: Add route handler in `crates/rag-retrieval/src/api/routes.rs`

**New Orchestrator Workflow Node:**
- Implementation: `services/orchestrator/workflow/nodes/{node_name}.py`
- Update: `services/orchestrator/workflow/state.py` (RAGState if new fields needed)
- Update: `services/orchestrator/workflow/graph.py` (add node to StateGraph)
- Tests: `services/orchestrator/tests/test_workflow_{node_name}.py`

**New Ingestion Document Source (Connector):**
- Implementation: `crates/rag-ingestion/src/connectors/{source_name}.rs`
- Trait impl: Implement `Connector` trait from `crates/rag-ingestion/src/connectors/mod.rs`
- Tests: `crates/rag-ingestion/tests/test_{source_name}.rs`
- Registration: Add to connector dispatcher in `crates/rag-ingestion/src/api/routes.rs`

**New Database Model:**
- Definition: `services/orchestrator/shared/database/models/{entity}.py` (SQLAlchemy)
- Migration: `alembic revision --autogenerate -m "add {entity} table"`
- File location: `services/orchestrator/shared/database/migrations/versions/{timestamp}_{description}.py`
- Test: `services/orchestrator/tests/test_database_{entity}.py`

**New Shared Rust Library (cross-service):**
- Create: `crates/rag-{feature}/` with `Cargo.toml`, `src/lib.rs`
- Register: Add to `[workspace.members]` in root `crates/Cargo.toml`
- Export types: Use `pub use` in `src/lib.rs` for public API
- Tests: `tests/` directory at crate root

**Utilities/Helpers:**
- Shared Python helpers: `services/orchestrator/shared/{domain}/__init__.py`
- Shared Rust helpers: `crates/rag-types/src/` (if domain-agnostic) or feature crate
- Service-specific helpers: Keep in service directory, don't expose via shared

## Special Directories

**crates/target/**
- Purpose: Build artifacts (compiled binaries, object files)
- Generated: Yes (created by `cargo build`)
- Committed: No (in `.gitignore`)

**services/orchestrator/shared/generated/**
- Purpose: Auto-generated code from schemas (gRPC, protobuf)
- Generated: Yes (created by build scripts)
- Committed: No (gitignored, regenerated on build)

**services/orchestrator/shared/database/migrations/versions/**
- Purpose: Alembic migration history (version control for schema)
- Generated: Partially (created by `alembic revision --autogenerate`)
- Committed: Yes (required for reproducible deployments)

**.moon/**
- Purpose: Moon monorepo task runner configuration
- Generated: No
- Committed: Yes (task definitions, workspace config)

**.planning/codebase/**
- Purpose: GSD codebase analysis documents (this file location)
- Generated: Yes (created by GSD mapping commands)
- Committed: No (transient documentation)

---

*Structure analysis: 2026-01-30*
