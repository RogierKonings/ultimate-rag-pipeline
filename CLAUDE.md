# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ultimate RAG Pipeline is a production-grade Retrieval-Augmented Generation (RAG) architecture designed to be modular, observable, and data-centric. The system cleanly separates ingestion, retrieval, orchestration, and evaluation concerns, enabling independent scaling and component swapping.

## Technology Stack

- **Language**: Python 3.11+
- **API Framework**: FastAPI + Pydantic v2
- **Task Queue**: Celery + Redis
- **Vector Database**: Qdrant (HNSW for semantic search)
- **Keyword Search**: OpenSearch (BM25)
- **Metadata DB**: PostgreSQL 16+ (asyncpg)
- **Object Storage**: MinIO (S3-compatible)
- **Cache**: Redis
- **Orchestration**: LangGraph (LangChain)
- **LLM Serving**: vLLM (production), Ollama (local dev)
- **Embedding Model**: BAAI/bge-large-en-v1.5 (1024 dimensions)
- **Reranker**: BAAI/bge-reranker-v2-m3

## Essential Commands

### Development Environment

```bash
# Initial setup - starts infrastructure services and initializes databases
make dev

# Start infrastructure services only (postgres, redis, qdrant, opensearch, minio)
make up

# Start all services including application services
make up-all

# Stop all services
make down

# View logs from all services
make logs

# View logs from specific service
make logs-<service-name>  # e.g., make logs-ingestion-service

# Check service status
make status

# Check health endpoints
make health

# Clean environment and remove volumes
make clean
```

### Testing and Linting

```bash
# Run tests for all services
make test

# Run linting for all services
make lint

# Run tests inside specific service container
docker-compose exec ingestion-service pytest
docker-compose exec retrieval-service pytest tests/test_hybrid_search.py  # specific test file
```

### Database Operations

```bash
# Run database migrations
cd services/shared/database/migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Check current migration version
alembic current

# Rollback migration
alembic downgrade -1
```

### Kubernetes Deployment

```bash
# Apply base resources
kubectl apply -k k8s/base

# Apply development overlay
kubectl apply -k k8s/overlays/dev

# Apply production overlay
kubectl apply -k k8s/overlays/prod

# Check pods in namespace
kubectl get pods -n rag-pipeline

# View service logs
kubectl logs -n rag-pipeline deployment/ingestion-service -f

# Bootstrap OpenSearch (development)
make opensearch-bootstrap

# Bootstrap MinIO
make minio-bootstrap

# Manual PostgreSQL backup
make postgres-backup-manual
```

## Architecture

### Core Services

The system consists of four microservices with distinct responsibilities:

1. **Ingestion Service** (port 8001)
   - Document loading from various sources (files, databases, APIs, web)
   - Chunking with configurable strategies (recursive, semantic, document-structure)
   - Embedding generation (batched, parallelized)
   - Multi-store indexing (Qdrant vectors, OpenSearch keywords, PostgreSQL metadata)
   - Celery workers handle async ingestion jobs

2. **Retrieval Service** (port 8002)
   - Hybrid search combining semantic (Qdrant) and keyword (OpenSearch) search
   - Query preprocessing and expansion
   - Reciprocal Rank Fusion (RRF) for result merging
   - Cross-encoder reranking
   - ACL enforcement based on user context

3. **Orchestrator Service** (port 8003)
   - LangGraph-based stateful workflows
   - Intent classification and routing
   - RAG vs direct LLM decision logic
   - Prompt construction with Jinja2 templates
   - Response validation and guardrails
   - Citation extraction and alignment

4. **LLM Gateway** (port 8004)
   - vLLM for production (OpenAI-compatible API)
   - Ollama for local development
   - Model routing and request batching

### Shared Module Architecture

The `services/shared/` directory contains reusable components:

- **database/**: SQLAlchemy models, migrations (Alembic), connection pooling
- **vectorstore/**: Qdrant client abstraction
- **search/**: OpenSearch client with index management
- **cache/**: Redis clients for embedding cache, query cache
- **storage/**: MinIO/S3 client for object storage

All services import from shared using relative paths (e.g., `from shared.database.models import SourceDocument`).

### Data Flow

```
1. Document → Ingestion → Celery Worker → Chunking → Embedding → Qdrant + OpenSearch + PostgreSQL
2. Query → Orchestrator → Intent Classification
3. Orchestrator → Retrieval → Hybrid Search (Vector + Keyword) → RRF → Reranking → Top-K
4. Orchestrator → Prompt Builder → LLM Gateway → Response with Citations
```

### Key Architectural Patterns

- **Multi-tenancy**: All data is tenant-scoped with `tenant_id` throughout the stack
- **Hybrid retrieval**: Semantic search (Qdrant) + Keyword search (OpenSearch) fused with RRF
- **Caching layers**:
  - Embedding cache (content hash → vector)
  - Query cache (query + filters → results)
  - Response cache (conversation context → LLM output)
- **Async-first**: All services use FastAPI with async/await and asyncpg for PostgreSQL
- **Observability**: OpenTelemetry instrumentation for distributed tracing (Jaeger), Prometheus metrics, structured logging

## Database Schema

### PostgreSQL Tables

Core tables (see `services/shared/database/models/`):

- **source_documents**: Metadata for ingested documents with tenant isolation, content hashing for deduplication, ACL fields (`visibility`, `allowed_groups`)
- **chunks**: Document chunks with embedding metadata, references parent document
- **embedding_jobs**: Track re-embedding jobs when changing models
- **retrieval_logs**: Query audit trail with latency metrics
- **conversations** / **messages**: Chat history storage
- **eval_datasets** / **eval_examples** / **eval_runs**: Evaluation framework for Ragas metrics

### Qdrant Collections

- Collection name: `documents`
- Vector size: 1024 (BGE-large dimensions)
- Distance metric: Cosine similarity
- Payload schema includes: `tenant_id`, `document_id`, `chunk_index`, `source_type`, `allowed_groups`, `created_at`
- HNSW index configuration: `m=16`, `ef_construct=100`

### OpenSearch Indices

- Standard analyzer with English stopwords
- Fields: `chunk_id`, `document_id`, `tenant_id`, `content` (text), `title`, `source_uri`, `allowed_groups`
- BM25 ranking for keyword search

## Development Guidelines

### Working with Services

Each service follows a consistent structure:
```
service-name/
├── api/
│   ├── routes.py       # FastAPI endpoints
│   └── schemas.py      # Pydantic request/response models
├── [domain-logic]/     # Service-specific business logic
├── requirements.txt
├── Dockerfile
└── tests/
```

### Adding New Endpoints

1. Define Pydantic schemas in `api/schemas.py`
2. Implement route handlers in `api/routes.py` with async functions
3. Use dependency injection for database sessions, clients
4. Return proper HTTP status codes and structured error responses
5. Add OpenTelemetry spans for observability

### Database Migrations

Migrations live in `services/shared/database/migrations/versions/`:
- Use Alembic for schema changes
- Always test migrations with upgrade/downgrade
- Include both DDL and DML in same migration if needed
- Follow naming convention: `{number}_{description}.py`

### Environment Variables

Services read configuration from environment variables defined in `.env.example`:
- Database URLs use asyncpg dialect: `postgresql+asyncpg://...`
- All services share common vars but can override
- Sensitive values (API keys, passwords) must never be committed

### Testing Strategy

- Unit tests: Mock external dependencies (databases, vector stores)
- Integration tests: Use docker-compose services with test fixtures
- Test files in `tests/` directory parallel to source structure
- Use pytest fixtures defined in `conftest.py` for common setup
- See `docs/integration-test-patterns.md` for testing guidance

### Chunking Configuration

Default chunking strategy is recursive with:
- Target: 300 tokens (~200-400 optimal range)
- Max: 512 tokens
- Overlap: 50 tokens (10-20%)
- Separators: `["\n\n", "\n", ". ", " "]`
- Preserve section headings and document hierarchy

### Embedding Best Practices

- For BGE models, add instruction prefix to queries: `"Represent this sentence for searching relevant passages: {query}"`
- Documents are embedded WITHOUT prefix
- Normalize embeddings (cosine similarity requires unit vectors)
- Batch embedding requests (default: 32 per batch)
- Cache embeddings by content hash to avoid re-computing

### Retrieval Pipeline Tuning

Hybrid search parameters:
- Retrieve top-50 from both semantic and keyword search
- RRF constant `k=60`
- Default weights: semantic=0.7, keyword=0.3
- Rerank top-50 to final top-10
- Apply ACL filters AFTER reranking to preserve quality

Performance targets (p95):
- Query embedding: 20ms
- Semantic search: 50ms
- Keyword search: 30ms
- Reranking: 150ms
- LLM generation: 1500ms
- Total E2E: 2000ms

## Project Structure

```
ultimate-rag-pipeline/
├── services/
│   ├── ingestion/         # Document ingestion service
│   ├── retrieval/         # Hybrid search service
│   ├── orchestrator/      # RAG orchestration with LangGraph
│   ├── embedding/         # Embedding model serving
│   └── shared/            # Shared libraries (DB models, clients)
├── k8s/
│   ├── base/             # Base Kubernetes manifests
│   └── overlays/         # Environment-specific overlays (dev/prod)
├── docs/                 # Architecture and operational docs
├── workflow/             # Epics and user stories
├── scripts/              # Initialization and utility scripts
├── config/               # Service configuration files
├── init-scripts/         # Database initialization SQL
├── docker-compose.yml    # Local development setup
├── Makefile             # Development commands
└── .env.example         # Environment variable template
```

## Common Development Workflows

### Adding a New Document Source

1. Create connector in `services/ingestion/connectors/`
2. Inherit from `BaseConnector` (see `base.py`)
3. Implement `fetch()` and `list_documents()` methods
4. Add connector type to API schemas
5. Write integration tests in `connectors/tests/`
6. Update Celery tasks to handle new source type

### Changing Embedding Models

1. Update `EMBEDDING_MODEL` in `.env`
2. Create embedding job via API: `POST /api/v1/ingest/reembed`
3. Job will re-process all chunks with new model
4. Update Qdrant collection if vector size changes
5. Update model dimension in `services/shared/vectorstore/qdrant_client.py`

### Adding New Evaluation Metrics

1. Add dataset: `POST /api/v1/eval/datasets`
2. Add examples with ground truth
3. Run evaluation job (see `docs/architecture.md` for Ragas integration)
4. Results stored in `eval_runs` table with metrics JSON

### Debugging Retrieval Quality

1. Check retrieval logs in PostgreSQL: `SELECT * FROM retrieval_logs WHERE tenant_id = ... ORDER BY created_at DESC`
2. Use debug output from retrieval API response (`debug.semantic_results`, `debug.after_fusion`, etc.)
3. Adjust hybrid search weights in request options
4. Verify ACL filters aren't removing relevant results
5. Test with reranker disabled to isolate issues

## Service URLs (Local Development)

- PostgreSQL: `localhost:5432` (user: raguser, db: ragpipeline)
- Qdrant: `http://localhost:6333`
- OpenSearch: `http://localhost:9200`
- OpenSearch Dashboards: `http://localhost:5601`
- Redis: `localhost:6379` (password: ragredis)
- MinIO Console: `http://localhost:9001` (user: minioadmin)
- Ingestion API: `http://localhost:8001`
- Retrieval API: `http://localhost:8002`
- Orchestrator API: `http://localhost:8003`
- Embedding Service: `http://localhost:8080`
- LLM Gateway: `http://localhost:8004` (Ollama: actual port 11434)

## Additional Resources

- Architecture documentation: `docs/architecture.md` (comprehensive reference)
- Kubernetes setup: `docs/infrastructure/kubernetes-setup.md`
- Integration testing: `docs/integration-test-patterns.md`
- Health check spec: `docs/health-check-specification.md`
- Deployment runbook: `docs/infrastructure/deployment-runbook.md`
