# External Integrations

**Analysis Date:** 2026-01-30

## APIs & External Services

**LLM Services:**
- **vLLM** - Text generation inference server
  - Gateway URL: `LLM_SERVICE_URL` / `LLM_GATEWAY_URL` (port 8004 via host.docker.internal:11434)
  - Proxy: Rust LLM Gateway (`crates/rag-llm-gateway/`) wraps vLLM with authentication and rate limiting
  - Supports OpenAI-compatible chat completions API
  - Models: `llama3.1:8b`, `qwen2.5:14b`, `llama3.2:3b` (configurable via `LLM_MODEL`)
  - Deployment: Native Ollama (local dev), Docker container (vLLM), or managed service (production)

- **Ollama** - Local LLM serving (development)
  - Endpoint: `http://host.docker.internal:11434` (Apple Silicon native, not Docker)
  - Alternative: Docker-based fallback commented in docker-compose.yml
  - Note: Cannot use Docker GPU access on Apple Silicon; requires native installation

**Embedding Services:**
- **Embedding Service** (Rust) - `crates/rag-embedding/`
  - HTTP Endpoint: `EMBEDDING_SERVICE_URL` (port 8080)
  - API: OpenAI-compatible `/v1/embeddings` endpoint
  - Model: `all-MiniLM-L6-v2` (384 dimensions, configurable via `EMBEDDING_MODEL`)
  - Supports: `sentence-transformers/all-MiniLM-L6-v2`, BAAI BGE models
  - Implementation: fastembed (ONNX-based) via Rust
  - Batch processing: Max 32 texts per request (configurable `EMBEDDING_BATCH_SIZE`)
  - Used by: Retrieval Service for query embeddings, Ingestion Service for document embeddings

- **fastembed Library** (ONNX inference)
  - Local embedding computation (no external API calls)
  - Supports CPU-only inference with thread pooling

**Reranker Service:**
- **Cross-Encoder Reranker** - BAAI/bge-reranker-v2-m3
  - Endpoint: `RERANKER_GATEWAY_URL` / `RERANKER_SERVICE_URL`
  - Implementation: ONNX-based via Rust LLM Gateway (`crates/rag-llm-gateway/`)
  - Disabled by default (`RERANKER_ENABLED=false`)
  - Used by: Retrieval Service for result re-ranking after RRF fusion

## Data Storage

**Databases:**

**PostgreSQL** (Metadata, Conversations, Evaluations)
- Connection: `postgresql+asyncpg://` (Rust), `postgresql+asyncpg://` (Python async)
- Connection Pool: deadpool (Rust), sqlalchemy with asyncpg (Python)
- Client: `sqlx` (Rust), `asyncpg` (Python), `sqlalchemy` 2.0+ (Python ORM)
- Port: 5432
- Database: `ragpipeline` (default)
- Schema Location: `services/orchestrator/shared/database/models/`
- Migrations: Alembic in `services/orchestrator/shared/database/migrations/versions/`
- Tables:
  - `source_documents` - Document metadata with tenant isolation
  - `chunks` - Document chunks with embedding metadata
  - `embedding_jobs` - Re-embedding job tracking
  - `retrieval_logs` - Query audit trail
  - `conversations` / `messages` - Chat history
  - `eval_datasets` / `eval_examples` / `eval_runs` - Evaluation framework

**Vector Store - Qdrant** (Semantic Search)
- Connection: `qdrant-client` 1.7.0 (Rust), HTTP client (Python)
- Endpoint: `QDRANT_URL` (port 6333 for HTTP, 6334 for gRPC)
- Collection: `documents` (default)
- Vector dimensions: 384 (all-MiniLM-L6-v2)
- Distance metric: Cosine similarity
- Index: HNSW with m=16, ef_construct=100
- Payload fields: `tenant_id`, `document_id`, `chunk_index`, `source_type`, `allowed_groups`, `created_at`
- Also: `video_chunks` collection for video transcript indexing

**Search Engine - OpenSearch** (Keyword Search)
- Connection: `opensearch` 2.2 (Rust), `opensearch-py` 2.4+ (Python)
- Endpoint: `OPENSEARCH_URL` (port 9200)
- Index: `documents` (default, configurable via `OPENSEARCH_INDEX`)
- Analyzer: English with stopwords
- Fields: `chunk_id`, `document_id`, `tenant_id`, `content`, `title`, `source_uri`, `allowed_groups`
- Ranking: BM25 (default)
- Dashboard: OpenSearch Dashboards at port 5601
- Security: Disabled in dev, requires credentials in production

**File Storage:**

**MinIO** (S3-compatible Object Storage)
- Endpoint: `MINIO_ENDPOINT` (port 9000 for API, 9001 for console)
- Protocol: HTTP (dev) or HTTPS (prod)
- Client: AWS SDK for S3 via `aws-sdk-s3` (Rust)
- Credentials: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
- Default Bucket: `documents`
- Used for: Document storage, backups, model caches
- Console: `http://localhost:9001` with minio admin credentials

**AWS S3** (Production Alternative)
- SDK: `aws-sdk-s3`, `aws-config` (Rust)
- Authentication: IAM roles or access keys
- Compatible client implementation in `crates/rag-storage/`

**Caching:**

**Redis** (Multi-purpose Cache)
- Connection: `redis://` URL with password authentication
- Endpoint: `REDIS_HOST` (localhost), `REDIS_PORT` (6379)
- Password: `REDIS_PASSWORD` (required)
- Features:
  - **Session Cache**: User session state (TTL: `REDIS_DEFAULT_TTL` = 3600s)
  - **Query Cache**: Query results (tenant-specific)
  - **Embedding Cache**: Content hash → embedding vector
  - **Job Queue**: Async ingestion tasks with priority and DLQ
  - **Rate Limiting**: Token bucket per tenant
- Databases:
  - DB 0: Celery broker (async task queue)
  - DB 1: Celery results
  - DB 2: Application cache (default)
- Configuration: Maxmemory=512MB, LRU eviction, AOF persistence
- Client: `redis` 0.24/0.25 (Rust), `redis` 5.0+ (Python)

## Authentication & Identity

**Auth Provider:**
- **Custom JWT-based** - No external identity provider
  - Implementation: `crates/rag-auth/` (Rust), `shared/security/` (Python)
  - Token Format: JSON Web Token (HS256 or RS256)
  - Library: `jsonwebtoken` 9.3 (Rust), `PyJWT` 2.8+ (Python)
  - Secret: `JWT_SECRET` environment variable
  - Algorithm: `JWT_ALGORITHM` (default: HS256)
  - Claim Validation: Includes `tenant_id`, `user_id`, `scopes`
  - Token Blocklist: Redis-backed token revocation

**API Key Authentication:**
- Header: `Authorization: Bearer {api_key}`
- Storage: Environment variable `API_KEY`
- Validation: Direct string comparison or database lookup

**RBAC (Role-Based Access Control):**
- Implementation: `crates/rag-auth/` (ACL middleware)
- Resource Types: Collections, documents, queries
- Roles: User-defined with scope patterns
- Enforcement: Pre-retrieval filtering in `crates/rag-retrieval/`

**Secrets Management:**
- **Vault** - Hashicorp Vault support (optional)
  - Client: `reqwest` HTTP client to Vault API
  - Implementation: `crates/rag-secrets/` with Vault adapter
- **Kubernetes Secrets** - K8s native (optional feature)
  - Client: `kube` 0.93 with `k8s-openapi` 0.22
  - Implementation: `crates/rag-secrets/` with K8s adapter
- **Environment Variables** - Fallback default
  - Loaded via `dotenvy` 0.15

## Monitoring & Observability

**Error Tracking:**
- Not detected - No external error tracking service (Sentry, etc.) in configuration
- Local logging via structured logs to stdout/stderr

**Logs:**
- **Structured Logging** (Rust):
  - Framework: `tracing` 0.1 + `tracing-subscriber` 0.3
  - Format: JSON with trace_id correlation
  - Levels: INFO (default), DEBUG, WARN, ERROR
  - Control: `LOG_LEVEL` and `RUST_LOG` env vars
  - Output: stdout/stderr, collected by container runtime

- **Structured Logging** (Python):
  - Framework: `structlog` 23.2+
  - Format: JSON with context propagation
  - Integration: OpenTelemetry instrumentation
  - Output: stdout/stderr

**Distributed Tracing:**
- **OpenTelemetry** (OTEL):
  - Exporter: OTLP gRPC (via `opentelemetry-otlp` 0.15)
  - Endpoint: `OTEL_EXPORTER_OTLP_ENDPOINT` (default: http://localhost:4317)
  - Service Name: `OTEL_SERVICE_NAME` (default: rag-pipeline)
  - SDK: `opentelemetry` 0.22 + `opentelemetry_sdk` 0.22
  - Instrumentation:
    - FastAPI: `opentelemetry-instrumentation-fastapi` 0.42b0
    - httpx: `opentelemetry-instrumentation-httpx` 0.42b0
    - asyncpg: `opentelemetry-instrumentation-asyncpg` 0.42b0
    - Redis: `opentelemetry-instrumentation-redis` 0.42b0
  - Backend: Jaeger (expected consumer at OTEL endpoint)
  - Spans: Per-node in workflow, per-request in services

**Metrics:**
- **Prometheus**:
  - Library: `prometheus` 0.13 (Rust)
  - Format: Prometheus exposition format
  - Metrics Exposed:
    - Request latency (per endpoint)
    - Token counts (TTFT, generation time)
    - Cache hit/miss rates
    - Circuit breaker state
    - Vector store query latency
    - Embedding inference time
  - Scrape Endpoint: `/metrics` (port varies per service)
  - Python client: `prometheus-client` 0.19+

**Health Checks:**
- HTTP Endpoints:
  - `/health` - Detailed component status
  - `/health/live` - Kubernetes liveness probe
  - `/health/ready` - Kubernetes readiness probe
- Checked Components: Redis, PostgreSQL, Qdrant, OpenSearch, LLM Gateway, Retrieval Service

## CI/CD & Deployment

**Hosting:**
- **Local Development**: Docker Compose (docker-compose.yml)
- **Kubernetes**: Kustomize-based manifests
  - Base: `k8s/base/`
  - Overlays: `k8s/overlays/dev/`, `k8s/overlays/prod/`
  - Applied via: `kubectl apply -k k8s/overlays/{dev,prod}`

**CI Pipeline:**
- **GitHub Actions** (inferred from .github/ directory structure)
- **Local CI**: `moon ci` command (Moon task runner)
- Testing: `moon run :test`, `moon run :lint`
- Build: Cargo for Rust, pip for Python

**Container Registry:**
- Docker images built locally for all services
- Dockerfiles: `crates/rag-*/Dockerfile` and `services/orchestrator/Dockerfile`

**Build Tools:**
- **Moon** - Monorepo task orchestration
  - Config: `moon.yml` (root) + per-project configs
  - Commands: `moon run`, `moon project-graph`, `moon ci`
- **Makefile** - Development convenience commands
  - `make dev` - Start all services with initialization
  - `make up` - Start infrastructure only
  - `make test` - Run all tests
  - `make lint` - Run linters
  - `make health` - Check service health

## Environment Configuration

**Required env vars (Critical):**
- `POSTGRES_URL` / `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `QDRANT_URL` - Qdrant vector store URL
- `OPENSEARCH_URL` - OpenSearch endpoint
- `MINIO_ENDPOINT` - MinIO S3-compatible endpoint
- `EMBEDDING_SERVICE_URL` - Embedding service HTTP endpoint
- `LLM_SERVICE_URL` / `LLM_GATEWAY_URL` - LLM service endpoint
- `JWT_SECRET` - JWT signing secret
- `API_KEY` - API authentication key
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OpenTelemetry collector endpoint

**Secrets location:**
- Environment variables (`.env` file, not committed)
- Kubernetes Secrets (in production)
- HashiCorp Vault (optional, via `rag-secrets` crate)
- AWS Secrets Manager (optional alternative)

**Generated configs:**
- `.env` file generated by `make env-local`, `make env-docker`, `make env-frontend`
- Source templates: `.env.example`, `.env.base`
- Per-environment overrides: `.env.local`, `.env.docker`, `.env.k8s`

## Webhooks & Callbacks

**Incoming:**
- Not detected - No webhook endpoints configured in codebase
- API is request-response only, no external webhook callbacks

**Outgoing:**
- Not detected - No outbound webhook delivery system implemented
- Services use HTTP client requests only (to LLM, embedding services, etc.)

## LLM Model Integrations

**Model APIs:**
- **OpenAI-Compatible Interface** - vLLM and Ollama expose OpenAI-compatible API
  - Endpoint: `{LLM_GATEWAY_URL}/v1/chat/completions`
  - Client: `openai` Python library (1.6+)
  - Models Supported:
    - `meta-llama/Llama-3.1-8B-Instruct` (default)
    - `meta-llama/Llama-3.1-70B-Instruct` (large)
    - `meta-llama/Llama-3.2:3b` (fallback)
    - `qwen2.5:14b` (medium)
    - Configurable via `LLM_MODEL`, `ORCHESTRATOR_DEFAULT_MODEL`, etc.
  - Response Format: JSON with `usage` metadata
  - Streaming: SSE format via `sse-starlette` 1.8+
  - Timeout: `LLM_GATEWAY_TIMEOUT_MS` / `ORCHESTRATOR_LLM_TIMEOUT_MS`

**Embedding Model:**
- **sentence-transformers/all-MiniLM-L6-v2**
  - Dimensions: 384
  - Distance: Cosine similarity
  - Used for: Document and query embeddings
  - Deployment: Local ONNX inference (fastembed) or remote service
  - Alternative Models: `BAAI/bge-large-en-v1.5`, `BAAI/bge-reranker-v2-m3`

## Integration Flow Overview

```
Document Ingestion:
1. User → Orchestrator (POST /api/v1/ingest)
2. Ingestion Service → Parse (PDF/DOCX/HTML/MD)
3. Ingestion Service → Chunk (recursive with overlap)
4. Ingestion Service → Embedding Service (batch requests)
5. Embedding Service → fastembed (ONNX CPU inference)
6. Ingestion Service → Redis Queue (async worker)
7. Ingestion Service → Qdrant (vector index)
8. Ingestion Service → OpenSearch (keyword index)
9. Ingestion Service → PostgreSQL (metadata)
10. Ingestion Service → MinIO (document storage)

Query Processing:
1. User → Orchestrator (POST /api/v1/query or /query/stream)
2. Orchestrator → Routing (intent classification)
3. Orchestrator → Retrieval Service (hybrid search)
4. Retrieval Service → Embedding Service (query embedding)
5. Retrieval Service → Qdrant (semantic search)
6. Retrieval Service → OpenSearch (keyword search)
7. Retrieval Service → RRF Fusion (merge rankings)
8. Retrieval Service → LLM Gateway (reranker)
9. Retrieval Service → PostgreSQL (ACL checks, results logging)
10. Orchestrator → Prompt Builder (Jinja2 templates)
11. Orchestrator → LLM Gateway (vLLM/Ollama proxy)
12. Orchestrator → Redis (session cache)
13. Orchestrator → PostgreSQL (conversation store)
14. Orchestrator → User (streaming or batch response)
```

---

*Integration audit: 2026-01-30*
