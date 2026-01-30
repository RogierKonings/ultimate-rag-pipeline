# Technology Stack

**Analysis Date:** 2026-01-30

## Languages

**Primary:**
- **Rust** 1.75+ - Core ingestion, retrieval, embedding, and LLM gateway services (`crates/rag-*`)
- **Python** 3.11+ - Orchestrator service with LangGraph workflows (`services/orchestrator/`)

**Secondary:**
- **JavaScript/TypeScript** - Frontend application (`frontend/`)

## Runtime

**Environment:**
- **Rust**: Tokio async runtime (1.35+) for all Rust services
- **Python**: CPython 3.11+ with asyncio for async operations
- **Container**: Docker and Docker Compose for local development and CI/CD

**Package Manager:**
- **Rust**: Cargo (workspace-based monorepo, resolver="2")
- **Python**: pip with requirements.txt
- **Lockfiles**: Present (Cargo.lock for Rust, pip freeze for Python)

## Frameworks

**Core:**
- **Axum** 0.7 - HTTP server framework for all Rust services (ingestion, retrieval, embedding, LLM gateway)
- **FastAPI** 0.104+ - HTTP server framework for Python orchestrator service
- **LangGraph** 0.0.40+ - Stateful workflow orchestration for RAG pipeline nodes
- **Tokio** 1.35 - Async runtime for Rust services with "full" feature set
- **SQLAlchemy** 2.0+ - ORM for Python database interactions

**API/Serialization:**
- **serde** 1.0 - Rust serialization framework with derive macros
- **Pydantic** 2.5+ - Python data validation and settings management
- **serde_json** 1.0 - Rust JSON handling
- **JSON** - Standard format for all API requests/responses

**Testing:**
- **pytest** 7.4+ - Python test runner
- **pytest-asyncio** 0.21+ - Async test support
- **pytest-cov** 4.1+ - Code coverage reporting
- **tokio-test** 0.4 - Rust async testing utilities
- **Criterion** 0.5 - Rust benchmarking framework
- **proptest** 1.4 - Property-based testing for Rust

**Build/Dev:**
- **cargo** - Rust package manager and build tool
- **Alembic** - Database migration tool for Python services
- **Moon** - Monorepo task orchestration (see Makefile)
- **docker-compose** 3.8+ - Local development orchestration

## Key Dependencies

**Critical - Data Storage:**
- **PostgreSQL** 16+ - Metadata, conversations, evaluations; connection via `sqlx` (Rust) and `asyncpg` (Python)
  - Rust: `sqlx` 0.8 with postgres, uuid, chrono, json, macros features
  - Python: `asyncpg` 0.29+
- **Qdrant** 1.16.3+ - Vector database for semantic search (HNSW index)
  - Rust: `qdrant-client` pinned to 1.7.0 for API stability
  - Vector dimensions: 384 (all-MiniLM-L6-v2, configurable)
- **OpenSearch** 2.11.1 - Full-text keyword search (BM25 ranking)
  - Python: `opensearch-py` 2.4+
  - Rust: `opensearch` 2.2
- **Redis** 7-alpine - Caching, session storage, async job queue
  - Rust: `redis` 0.24/0.25 with tokio-comp and connection-manager
  - Python: `redis` 5.0+

**Critical - ML/Embeddings:**
- **fastembed** 4 - ONNX-based local text embeddings (Rust service)
  - Model: `sentence-transformers/all-MiniLM-L6-v2` (384 dims, default)
  - Alternative: `BAAI/bge-large-en-v1.5` or `BAAI/bge-reranker-v2-m3`
- **tokenizers** 0.19 - Hugging Face tokenizer library for cross-encoder reranking

**Critical - HTTP/Networking:**
- **reqwest** 0.11-0.12 - Async HTTP client (Rust services)
- **httpx** 0.25+ - Async HTTP client (Python orchestrator)
- **axum** 0.7 - HTTP framework with tower middleware
- **tower** 0.4/0.5 - Tower middleware ecosystem
- **tower-http** 0.5 - HTTP middleware (CORS, tracing, timeouts)

**Infrastructure - File Storage:**
- **aws-sdk-s3** 1.72.0 - AWS S3 / MinIO object storage client (Rust)
  - Also: `aws-config` 1.5.17, `aws-smithy-runtime-api`, `aws-smithy-types`
  - Used for document storage and backups
- **minio** container (RELEASE.2024-01-01) - S3-compatible object storage

**Infrastructure - Observability:**
- **opentelemetry** 0.22 - Distributed tracing (trace + metrics features)
- **opentelemetry_sdk** 0.22 - OpenTelemetry SDK with rt-tokio, trace, metrics
- **opentelemetry-otlp** 0.15 - OTLP exporter for Jaeger (gRPC via tonic)
- **tracing** 0.1 - Structured logging framework (Rust)
- **tracing-subscriber** 0.3 - Log filtering and formatting with json output
- **tracing-opentelemetry** 0.23 - Bridge between tracing and OpenTelemetry
- **prometheus** 0.13 - Metrics exposition and collection
- **structlog** 23.2+ - Structured logging for Python

**Infrastructure - Security:**
- **jsonwebtoken** 9.3 - JWT token handling and validation (Rust)
- **python-jose[cryptography]** 3.3+ - JWT support (Python)
- **PyJWT** 2.8+ - JWT library for Python
- **aes-gcm** 0.10 - AES-GCM authenticated encryption (Rust)
- **ring** 0.17 - Cryptographic operations (Rust)
- **argon2** 0.5 (optional) - Password hashing (Rust)
- **hkdf** 0.12 - HKDF key derivation (Rust)
- **sha2** 0.10 - SHA2 hashing (Rust)
- **presidio-analyzer** 2.2+ - PII detection (Python)
- **presidio-anonymizer** 2.2+ - PII anonymization (Python)

**Application Logic:**
- **langchain-core** 0.1+ - LangChain core utilities for prompt/output parsing
- **openai** 1.6+ - OpenAI Python SDK (used by orchestrator for API compatibility)
- **tenacity** 8.2+ - Retry logic with exponential backoff
- **tiktoken** 0.5+ - Token counting for LLMs
- **Jinja2** 3.1+ - Template engine for prompt rendering
- **apscheduler** 3.10+ - Background task scheduling (conversation summarization, cleanup)
- **sse-starlette** 1.8+ - Server-Sent Events streaming (Python)

**Document Processing:**
- **pdf-extract** 0.8 - PDF parsing (Rust)
- **quick-xml** 0.31 - XML parsing for DOCX support (Rust)
- **zip** 0.6 - ZIP archive handling for DOCX (Rust)
- **scraper** 0.20 - HTML parsing and CSS selectors (Rust)
- **ego-tree** 0.6 - DOM tree representation (Rust)
- **pulldown-cmark** 0.12 - Markdown parsing (Rust)
- **serde_yaml** 0.9 - YAML parsing (Rust and Python)

**Utilities:**
- **uuid** 1.6 - UUID generation (v4, serde support)
- **chrono** 0.4 - DateTime handling with serde
- **bytes** 1.5 - Byte buffer utilities
- **futures** 0.3 - Async/await utilities
- **rayon** 1.8/1.10 - Parallel data processing
- **unicode-normalization** 0.1 - Unicode text normalization
- **unicode-segmentation** 1.10 - Unicode text segmentation
- **mime_guess** 2.0 - MIME type detection
- **regex** 1.10 - Regular expressions
- **lazy_static** 1.4 - Static lazy initialization
- **async-trait** 0.1 - Async trait support
- **sha2**, **hex** - Hashing for cache keys

**Validation:**
- **validator** 0.18 - Field validation with derive macros
- **thiserror** 1.0 - Ergonomic error handling
- **anyhow** 1.0 - Flexible error handling

**Kubernetes Support (Optional):**
- **kube** 0.93 (optional feature: kubernetes) - Kubernetes client for secrets
- **k8s-openapi** 0.22 v1_29 (optional) - Kubernetes API types
- **reqwest** with rustls-tls - TLS support for Kubernetes

## Configuration

**Environment:**
- **.env.example** - Template for all configuration variables
- **.env** file structure:
  - `.env.base` - Shared defaults across all environments
  - `.env.local` / `.env.docker` / `.env.k8s` - Environment-specific URLs
  - Generated via `make env-local`, `make env-docker`, `make env-frontend`
- **Config files:**
  - `config/qdrant/config.yaml` - Qdrant service configuration
  - `crates/*/src/config.rs` - Rust configuration modules
  - `services/orchestrator/config/*.py` - Python configuration modules
  - `services/orchestrator/shared/database/migrations/` - Alembic migrations

**Key Configuration Variables:**
- Database: `DATABASE_URL`, `DATABASE_URL_SYNC`, `POSTGRES_*`
- Redis: `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`
- Qdrant: `QDRANT_URL`, `QDRANT_COLLECTION`
- OpenSearch: `OPENSEARCH_URL`, `OPENSEARCH_INDEX`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`
- MinIO: `MINIO_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_DEFAULT_BUCKET`
- ML: `EMBEDDING_MODEL`, `EMBEDDING_SERVICE_URL`, `RERANKER_MODEL`, `LLM_MODEL`, `LLM_SERVICE_URL`
- Services: `INGESTION_SERVICE_URL`, `RETRIEVAL_SERVICE_URL`, `ORCHESTRATOR_SERVICE_URL`
- Auth: `JWT_SECRET`, `API_KEY`
- Observability: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `LOG_LEVEL`

**Build Configuration:**
- `Cargo.toml` (workspace root) - Rust workspace configuration with shared dependencies
- `Cargo.toml` (per crate) - Individual crate configurations
- `pyproject.toml` - Python project configuration (if present)
- `Dockerfile` files in `crates/*/Dockerfile` for service containers

## Platform Requirements

**Development:**
- **OS**: macOS (Apple Silicon with native Ollama), Linux, Windows with WSL
- **Rust**: 1.75+ (toolchain specified in `rust-toolchain.toml`)
- **Python**: 3.11+
- **Docker**: 20.10+ with Docker Compose 3.8+
- **Memory**: 4+ GB RAM recommended
- **Disk**: 50+ GB for vector index data and model cacks
- **GPU**: Optional (CUDA for vLLM acceleration; Apple Silicon uses Metal via native Ollama)

**Production:**
- **Deployment**: Kubernetes with kustomize overlays (base, dev, prod)
  - Base manifests: `k8s/base/`
  - Overlays: `k8s/overlays/dev/` and `k8s/overlays/prod/`
- **Container Registry**: Docker images for all services
- **Database**: PostgreSQL 16+ (managed service or pod)
- **Vector Store**: Qdrant (single-node or cluster)
- **Search**: OpenSearch (cluster recommended for HA)
- **Cache**: Redis (single instance or cluster with sentinel)
- **Storage**: S3 or MinIO (must be externally accessible)
- **LLM**: vLLM service or managed API
- **Orchestrator**: Python FastAPI service with async worker pool
- **Ingestion**: Rust async service with Redis worker queue
- **Retrieval**: Rust async service with HTTP/gRPC endpoints

## Versioning

**Workspace Version:** 0.1.0
**Edition:** Rust 2021
**Rust Version:** 1.75 minimum
**License:** MIT

---

*Stack analysis: 2026-01-30*
