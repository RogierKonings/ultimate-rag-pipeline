# Ultimate RAG Pipeline

A production-grade Retrieval-Augmented Generation (RAG) architecture that is modular, observable, and data-centric. The system cleanly separates ingestion, retrieval, orchestration, and evaluation concerns, enabling independent scaling and component swapping.

## Table of Contents

- [Overview](#overview)
- [Key Capabilities](#key-capabilities)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Quick Start](#quick-start)
  - [Environment Configuration](#environment-configuration)
- [Services](#services)
  - [Ingestion Service](#ingestion-service)
  - [Retrieval Service](#retrieval-service)
  - [Orchestrator Service](#orchestrator-service)
  - [LLM Serving Layer](#llm-serving-layer)
- [Data Flow](#data-flow)
- [API Reference](#api-reference)
- [Deployment](#deployment)
  - [Local Development](#local-development)
  - [Kubernetes](#kubernetes)
- [Security](#security)
- [Observability](#observability)
- [Testing](#testing)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

The Ultimate RAG Pipeline provides enterprise-ready RAG capabilities with:

- **Hybrid Search**: Combines semantic (vector) and keyword (BM25) search with Reciprocal Rank Fusion
- **Cross-Encoder Reranking**: Improves retrieval precision using state-of-the-art reranker models
- **Multi-Tenant Architecture**: Complete tenant isolation with fine-grained access controls
- **Comprehensive Observability**: Distributed tracing, metrics, structured logging, and RAG-specific evaluation
- **Production Security**: JWT authentication, RBAC, document-level ACLs, encryption at rest and in transit

---

## Key Capabilities

### Document Ingestion
- Multiple source connectors (filesystem, S3, databases, web crawlers, APIs)
- Intelligent document parsing (PDF, DOCX, HTML, Markdown, plain text)
- Configurable chunking strategies (recursive, semantic, hierarchical)
- Automated metadata enrichment and PII detection
- Async processing with Celery for scalable ingestion

### Video RAG Pipeline

- Multi-modal video processing (transcription, vision, OCR)
- Scene-based chunking with temporal alignment
- Whisper transcription with word-level timestamps
- Vision analysis via LLaVA/GPT-4V for scene descriptions
- Hybrid search across video content with timeline responses
- On-demand clip generation with MinIO caching
- Full video CRUD with cascade deletion

### Hybrid Retrieval
- Semantic search via Qdrant (HNSW indexing, cosine similarity)
- Keyword search via OpenSearch (BM25 with fuzzy matching)
- Reciprocal Rank Fusion (RRF) for result combination
- Cross-encoder reranking for precision improvement
- Query preprocessing with expansion and HyDE support

### RAG Orchestration
- LangGraph-based stateful workflows
- Intelligent query routing (simple, complex, multi-hop, comparison, aggregation, no-retrieval strategies)
- Multi-hop query decomposition with parallel sub-question retrieval
- CRAG-style answer verification with claim extraction and validation
- Jinja2 prompt templates with context management
- Input/output guardrails (PII detection, injection prevention)
- Streaming responses with Server-Sent Events

### LLM Serving
- High-throughput inference via vLLM (production) or Ollama (development)
- OpenAI-compatible API gateway
- Dedicated embedding and reranker services
- JWT authentication and per-tenant rate limiting
- GPU resource management and cost tracking

### Security & Compliance
- JWT authentication with RS256 signing
- Role-based access control (RBAC) with 9 predefined roles
- Document-level ACLs with visibility levels (public, private, group, restricted)
- AES-256-GCM field encryption
- Tamper-evident audit logging with hash chaining
- PII detection and redaction via Microsoft Presidio
- SOC 2, GDPR, and HIPAA compliance support

### Cost-Aware Retrieval & Model Tiering
- Dynamic retrieval parameters based on query type and tenant tier
- LLM model tiering (small/medium/large) for cost optimization:
  - Small: llama3.2:3b (3B params) - simple queries, basic tenants
  - Medium: llama3.1:8b (8B params) - standard complexity
  - Large: qwen2.5:14b (14B params) - complex analytical, premium tenants
- Answer-level caching for instant repeated query responses
- Per-tenant token usage accounting with quota enforcement
- Configurable tenant tiers: basic, standard, premium

### Observability
- Distributed tracing with OpenTelemetry and Jaeger
- Prometheus metrics with RAG-specific SLOs
- Structured JSON logging with Loki integration
- Pre-configured Grafana dashboards
- Automated RAG quality evaluation with Ragas

---

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Client Applications                    │
                    └─────────────────────────────┬───────────────────────────┘
                                                  │
                                                  ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              Orchestrator Service (:8003)                          │
│   LangGraph Workflow | Query Router | Prompt Builder | Guardrails | Streaming     │
└────────────────────────────────┬──────────────────────────────────┬───────────────┘
                                 │                                  │
                                 ▼                                  ▼
┌────────────────────────────────────────────────┐  ┌─────────────────────────────────┐
│          Retrieval Service (:8002)              │  │    LLM Gateway (:8004)           │
│  Query Preprocessing | Hybrid Search | Rerank  │  │  vLLM | Embedding | Reranker    │
└───────────┬─────────────────────┬──────────────┘  └─────────────────────────────────┘
            │                     │
            ▼                     ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────────────────────┐
│  Qdrant (:6333)   │  │ OpenSearch (:9200)│  │       Ingestion Service (:8001)        │
│  Vector Search    │  │  Keyword Search   │  │  Connectors | Parsers | Chunking      │
└───────────────────┘  └───────────────────┘  └───────────────────┬───────────────────┘
                                                                  │
                                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Storage Layer                                           │
│   PostgreSQL (:5432)  │  Redis (:6379)  │  MinIO (:9000)  │  Qdrant  │  OpenSearch  │
│   Metadata & Audit    │  Cache & Queue  │  Object Storage │  Vectors │  Keywords    │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Core Pipeline Stages

| Stage | Purpose | Key Outputs |
|-------|---------|-------------|
| **Ingestion** | Load, chunk, embed, and index documents | Vectors + metadata in stores |
| **Retrieval** | Find relevant context for queries | Ranked document chunks |
| **Orchestration** | Coordinate LLM calls and business logic | Generated responses |
| **Evaluation** | Measure and improve system quality | Metrics, feedback loops |

---

## Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Language** | Python 3.11+ | Ecosystem maturity, ML library support |
| **API Framework** | FastAPI + Pydantic v2 | Async support, auto OpenAPI docs |
| **Task Queue** | Celery + Redis | Distributed ingestion, re-embedding jobs |
| **Vector Database** | Qdrant | High-performance HNSW, excellent filtering |
| **Keyword Search** | OpenSearch | BM25, rich analyzers, production-ready |
| **Metadata DB** | PostgreSQL 16+ | ACID, JSON support, mature tooling |
| **Object Storage** | MinIO / S3 | Raw document storage |
| **Cache** | Redis | Query cache, embedding cache |
| **Orchestration** | LangGraph | Stateful workflows, graph-based control |
| **LLM Serving** | vLLM | High-throughput, OpenAI-compatible API |
| **Embedding Model** | BAAI/bge-large-en-v1.5 | Top MTEB performance, MIT license |
| **Reranker** | BAAI/bge-reranker-v2-m3 | Cross-encoder, multilingual |
| **Tracing** | OpenTelemetry + Jaeger | Distributed tracing |
| **Metrics** | Prometheus + Grafana | Dashboards, alerting |
| **Evaluation** | Ragas | RAG-specific quality metrics |

---

## Getting Started

### Prerequisites

- **Docker** and **Docker Compose** (v2.20+)
- **Python 3.11+** (for local development)
- **Make** (for development commands)
- **kubectl** and **helm** (for Kubernetes deployment)
- **GPU with CUDA** (optional, for vLLM)

### Quick Start

1. **Clone the repository**

```bash
git clone https://github.com/your-org/ultimate-rag-pipeline.git
cd ultimate-rag-pipeline
```

2. **Set up environment variables**

```bash
# For local development (services run on host, localhost URLs)
make env-local

# For Docker Compose (services run in containers, service name URLs)
make env-docker
```

3. **Start the development environment**

```bash
# Start infrastructure services (PostgreSQL, Redis, Qdrant, OpenSearch, MinIO)
make dev

# Or start all services including application services
make up-all
```

4. **Verify services are running**

```bash
make status
make health
```

5. **Run database migrations**

The PostgreSQL database requires schema migrations before the services can function properly.

```bash
# From the project root, run migrations using Alembic
cd services/shared/database/migrations
alembic upgrade head
```

**Note:** The migrations use the `INGESTION_DATABASE_URL` environment variable. For local development with Docker:

- If running from host: `postgresql://raguser:ragpass@localhost:5432/ragpipeline`
- If running from container: `postgresql://raguser:ragpass@postgres:5432/ragpipeline`

You can also run migrations explicitly with the database URL:

```bash
cd services/shared/database/migrations
INGESTION_DATABASE_URL=postgresql://raguser:ragpass@localhost:5432/ragpipeline alembic upgrade head
```

**Migration commands:**

```bash
# Check current migration version
alembic current

# Upgrade to latest
alembic upgrade head

# Rollback one version
alembic downgrade -1

# View migration history
alembic history

# Create a new migration (auto-generate from models)
alembic revision --autogenerate -m "Description of changes"
```

1. **Access the services**

| Service | URL |
|---------|-----|
| Ingestion API | http://localhost:8001 |
| Retrieval API | http://localhost:8002 |
| Orchestrator API | http://localhost:8003 |
| LLM Gateway | http://localhost:8004 |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| OpenSearch | http://localhost:9200 |
| MinIO Console | http://localhost:9001 |

### Environment Configuration

The project uses a profile-based environment configuration system that automatically resolves service URLs based on deployment context.

#### Quick Setup

```bash
# For local development (localhost URLs)
make env-local

# For Docker Compose (service name URLs)
make env-docker

# For frontend development
make env-frontend
```

#### How It Works

Environment configuration is split into three files:

| File | Purpose |
|------|---------|
| `.env.base` | Shared defaults (ports, models, timeouts, credentials) |
| `.env.local` | Localhost URLs for local development |
| `.env.docker` | Docker service name URLs for containerized deployment |

The `make env-*` commands combine these files to generate `.env`:

```
.env = .env.base + .env.local   (for local development)
.env = .env.base + .env.docker  (for Docker Compose)
```

#### DEPLOY_ENV Variable

The `DEPLOY_ENV` variable controls automatic URL resolution in Python services:

| Value | Description | Example URL |
|-------|-------------|-------------|
| `local` | Services run on host machine | `http://localhost:6333` |
| `docker` | Services run in Docker containers | `http://qdrant:6333` |
| `kubernetes` | Services run in Kubernetes | `http://qdrant.rag-pipeline.svc.cluster.local:6333` |

Python services use centralized URL resolution (`services/shared/config/urls.py`) that:
1. First checks for explicit environment variables (e.g., `QDRANT_URL`)
2. Falls back to auto-generated URLs based on `DEPLOY_ENV`

#### Overriding Individual Variables

You can override any variable by setting it directly in your environment or by editing the generated `.env` file:

```bash
# Generate base config
make env-local

# Override specific variables
export QDRANT_URL=http://custom-qdrant:6333
```

#### Key Configuration Variables

```bash
# Database
POSTGRES_USER=raguser
POSTGRES_PASSWORD=ragpass
POSTGRES_DB=ragpipeline

# Vector Store
QDRANT_COLLECTION=documents

# Search
OPENSEARCH_INDEX=documents

# Cache
REDIS_PASSWORD=ragredis

# Object Storage
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin123

# Embedding
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5

# LLM
LLM_MODEL=llama3.1:8b

# Model Tiering (Orchestrator)
ORCHESTRATOR_SMALL_MODEL=llama3.2:3b
ORCHESTRATOR_MEDIUM_MODEL=llama3.1:8b
ORCHESTRATOR_LARGE_MODEL=qwen2.5:14b
ORCHESTRATOR_FALLBACK_MODEL=llama3.2:3b

# Observability
LOG_LEVEL=INFO

# Security
JWT_SECRET=your-jwt-secret-change-in-production
```

See `.env.example` for the complete list of available variables with documentation.

---

## Services

### Ingestion Service

**Port:** 8001

Handles document intake, processing, and indexing.

**Features:**
- Source connectors: filesystem, S3, databases, web crawlers, REST APIs
- Document parsing: PDF, DOCX, HTML, Markdown, plain text
- Chunking strategies: recursive (default), semantic, hierarchical
- Embedding generation with caching
- Multi-store indexing with explicit status tracking and background reconciliation
- Soft-delete propagation across all stores (Qdrant, OpenSearch, PostgreSQL)
- Optional per-tenant index isolation for large tenants
- Per-tenant rate limiting with priority queues (high/normal/low)
- PII detection with Microsoft Presidio
- Async processing via Celery

**Key Endpoints:**
```
POST /api/v1/ingest/sync    # Trigger document ingestion
POST /api/v1/ingest/reembed # Start re-embedding job
GET  /api/v1/ingest/jobs/{id} # Check job status
GET  /api/v1/documents      # List documents
```

[Full Documentation](docs/ingestion-service/README.md)

### Retrieval Service

**Port:** 8002

Core search component implementing hybrid search with reranking.

**Features:**
- Query preprocessing (normalization, classification, expansion, HyDE)
- Hybrid search combining semantic (Qdrant) and keyword (OpenSearch)
- Reciprocal Rank Fusion (RRF) with configurable weights
- Cross-encoder reranking via LLM Gateway
- Circuit breakers with graceful degradation (semantic-only, keyword-only modes)
- Early ACL filtering at query level with safety net verification
- Query and result caching

**Hybrid Search Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| Semantic weight | 0.7 | Weight for vector search in RRF |
| Keyword weight | 0.3 | Weight for BM25 search in RRF |
| RRF constant (k) | 60 | RRF ranking constant |
| Semantic top-k | 50 | Candidates from vector search |
| Keyword top-k | 50 | Candidates from keyword search |
| Rerank top-k | 20 | Candidates for cross-encoder |
| Final top-k | 10 | Results returned to client |

**Key Endpoints:**
```
POST /api/v1/retrieve       # Search for relevant chunks
POST /api/v1/retrieve/multi # Multi-query search
GET  /health                # Health check
```

[Full Documentation](docs/retrieval-service/README.md)

### Video Retrieval

**Included in Retrieval Service (Port 8002)**

Enables semantic search within video content using multi-modal analysis.

**Features:**

- Hybrid search across video chunks (semantic + keyword)
- Timeline-based result grouping by video
- Keyframe previews with presigned URLs
- On-demand clip generation with FFmpeg
- MinIO-backed clip caching with TTL expiration
- RRF fusion and cross-encoder reranking

**Key Endpoints:**

```
POST /api/v1/retrieve/video           # Search across all videos
GET  /api/v1/retrieve/video/{id}      # Search within specific video
GET  /api/v1/videos/{id}/clip         # Generate/retrieve video clip
GET  /api/v1/videos/{id}/chunks       # List video chunks
```

**Video Management (Ingestion Service):**

```
GET    /api/v1/videos                 # List videos with pagination
POST   /api/v1/videos                 # Upload new video
GET    /api/v1/videos/{id}            # Get video details
PUT    /api/v1/videos/{id}            # Update video metadata
DELETE /api/v1/videos/{id}            # Delete with cascade
POST   /api/v1/videos/{id}/reprocess  # Re-process video
```

### Orchestrator Service

**Port:** 8003

Central coordination layer managing the complete query lifecycle.

**Features:**
- LangGraph-based stateful workflows
- Intelligent query routing with multi-hop detection
- Multi-hop query decomposition with parallel sub-question retrieval
- CRAG-style answer verification (claim extraction and validation)
- Jinja2 prompt templates
- Input/output guardrails
- Conversation memory (Redis + PostgreSQL)
- Streaming with SSE and TTFT tracking
- Circuit breakers and graceful degradation

**Routing Strategies:**

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `simple` | Single retrieval pass | Factual questions |
| `complex` | Multi-step retrieval | Analytical queries |
| `multi_hop` | Query decomposition | Sequential reasoning |
| `comparison` | Compare multiple entities | "X vs Y" questions |
| `aggregation` | Collect and summarize | "List all...", "Summarize..." |
| `no_retrieval` | Direct LLM response | Greetings, chitchat |

**Key Endpoints:**
```
POST /api/v1/query          # Synchronous RAG query
POST /api/v1/query/stream   # Streaming RAG query (SSE)
POST /api/v1/feedback       # Submit user feedback
POST /api/v1/sessions       # Create conversation session
```

[Full Documentation](docs/orchestrator-service/README.md)

### LLM Serving Layer

**Port:** 8004 (Gateway)

Unified API gateway for all language model operations.

**Components:**

| Service | Port | Model | Purpose |
|---------|------|-------|---------|
| Gateway | 8004 | - | Unified API entry point |
| vLLM | 8000 | Qwen/Qwen2.5-7B-Instruct | Text generation |
| Embedding | 8001 | BAAI/bge-large-en-v1.5 | Vector embeddings (1024d) |
| Reranker | 8002 | BAAI/bge-reranker-v2-m3 | Cross-encoder reranking |

**Features:**
- OpenAI-compatible API (`/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank`)
- JWT and API key authentication
- Per-tenant rate limiting
- Streaming responses
- Health monitoring and metrics

[Full Documentation](docs/llm-serving/README.md)

---

## Data Flow

### Query Flow

```
1. User Query
   │
   ├──▶ Orchestrator: Input validation & guardrails
   │
   ├──▶ Query Router: Classify intent, select strategy
   │
   ├──▶ Retrieval Service:
   │    ├── Query preprocessing (expansion, HyDE)
   │    ├── Parallel search (semantic + keyword)
   │    ├── RRF fusion
   │    ├── Reranking (cross-encoder)
   │    └── ACL filtering
   │
   ├──▶ Orchestrator: Build prompt with context
   │
   ├──▶ LLM Gateway: Generate response
   │
   └──▶ Orchestrator: Output validation, citation extraction
       │
       └──▶ Response with sources
```

### Ingestion Flow

```
1. Document Source
   │
   ├──▶ Connector: Fetch document
   │
   ├──▶ Parser: Extract text and metadata
   │
   ├──▶ Enrichment: Language detection, PII scan
   │
   ├──▶ Chunking: Split into semantic chunks
   │
   ├──▶ Embedding: Generate vectors (cached)
   │
   └──▶ Index Writers:
       ├── PostgreSQL (metadata, ACLs)
       ├── Qdrant (vectors for semantic search)
       └── OpenSearch (text for keyword search)
```

---

## API Reference

### Query Endpoint

```bash
curl -X POST http://localhost:8003/api/v1/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "query": "How do I reset my SSO password?",
    "tenant_id": "tenant-uuid",
    "options": {
      "max_tokens": 512,
      "temperature": 0.2,
      "include_citations": true
    }
  }'
```

### Streaming Query

```bash
curl -X POST http://localhost:8003/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -H "Accept: text/event-stream" \
  -d '{
    "query": "Explain our refund policy",
    "tenant_id": "tenant-uuid"
  }'
```

### Retrieval

```bash
curl -X POST http://localhost:8002/api/v1/retrieve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "query": "password reset steps",
    "top_k": 10,
    "options": {
      "hybrid": true,
      "use_reranker": true,
      "semantic_weight": 0.7
    }
  }'
```

### Document Ingestion

```bash
curl -X POST http://localhost:8001/api/v1/ingest/sync \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "source_type": "filesystem",
    "source_config": {
      "path": "s3://bucket/documents",
      "recursive": true
    },
    "options": {
      "chunking_strategy": "recursive",
      "target_tokens": 300
    }
  }'
```

---

## Deployment

### Local Development

```bash
# Start infrastructure only
make up

# Start all services
make up-all

# View logs
make logs

# Check status
make status

# Run tests
make test

# Stop everything
make down

# Full cleanup (removes volumes)
make clean
```

### Developer CLI Tools

CLI tools are available for common development operations:

```bash
# Check service health
python scripts/dev-health.py

# Test a RAG query with debug output
python scripts/dev-query.py "What is RAG?" --debug

# Ingest a document
python scripts/dev-ingest.py file document.pdf --wait

# Trigger index reconciliation (dry run)
python scripts/dev-reconcile.py --tenant dev-tenant --dry-run
```

See [scripts/README.md](scripts/README.md) for full documentation.

### Kubernetes

```bash
# Deploy to development
kubectl apply -k k8s/overlays/dev/

# Deploy to production
kubectl apply -k k8s/overlays/prod/

# Bootstrap OpenSearch indices
make opensearch-bootstrap

# Bootstrap MinIO buckets
make minio-bootstrap

# Run database migrations
make postgres-migrate

# Trigger manual backup
make postgres-backup-manual
```

**Resource Requirements:**

| Environment | CPU (total) | Memory (total) | Pods |
|-------------|-------------|----------------|------|
| Development | 4-8 cores | 8-16 Gi | 20 |
| Production | 20-40 cores | 64-128 Gi | 50 |
| GPU (vLLM) | + 1 GPU | + 32 Gi VRAM | +1 |

[Full Kubernetes Setup Guide](docs/infrastructure/kubernetes-setup.md)

---

## Security

The pipeline implements defense-in-depth security:

### Authentication
- JWT tokens with RS256 asymmetric signing
- JWT-based inter-service authentication with RSA-2048 key pairs
- API key support for service-to-service communication
- Redis-backed token blocklist for revocation

### Authorization
- Role-based access control (RBAC) with 9 predefined roles
- Document-level ACLs with visibility levels
- Authorization matrix for service-to-endpoint permissions
- Mandatory tenant isolation on all operations

### Data Protection
- AES-256-GCM field encryption for sensitive data
- TLS 1.3 for all network communication
- SSL/TLS for all database connections (PostgreSQL, Redis, OpenSearch)
- Encrypted storage volumes (EBS, GCE PD)
- MinIO server-side encryption
- Credential sanitization in logs

### Privacy & PII

- Enhanced PII detection and redaction via Microsoft Presidio
- Multiple redaction modes (mask, hash, encrypt, remove, synthetic)
- PII handling at ingestion, query, and response stages
- Per-tenant custom PII patterns

### Secrets Management

- HashiCorp Vault integration for production
- Dynamic credential rotation with zero-downtime
- Kubernetes Secrets support with External Secrets Operator
- Automatic lease renewal and health monitoring

### Audit & Compliance

- Tamper-evident audit logging with SHA-256 hash chaining
- Multi-backend storage (PostgreSQL + OpenSearch)
- REST API for query, export, and chain validation
- SOC 2 Type II, GDPR, HIPAA compliance support

[Full Security Documentation](docs/security/README.md)

---

## Observability

### Correlation ID Propagation
- Strict correlation ID propagation across all services (US-10.3.1)
- Standard headers: `X-Request-ID`, `X-Trace-ID`, `X-Tenant-ID`
- Automatic propagation via HTTP clients and Celery tasks
- All logs joinable by `request_id` for cross-service debugging

### Distributed Tracing
- OpenTelemetry instrumentation across all services
- End-to-end trace hierarchy with consistent span naming (US-10.3.2)
- Jaeger for trace visualization with complete request lifecycle
- RAG-specific semantic attributes
- Traced client wrappers for Qdrant and OpenSearch

### Metrics
- Prometheus metrics following `rag_<subsystem>_<metric>_<unit>` naming
- Business & quality metrics: feedback scores, context relevance, citations (US-10.3.3)
- Per-tenant query success rates and latency tracking
- Key metrics: query latency, TTFT, cache hit rate, error rate

### SLO Definitions & Alerts
- Defined SLOs with automated alerting (US-10.3.4):
  - Retrieval p95 latency < 250ms
  - RAG E2E p95 latency < 2000ms
  - Error rate < 1% per tenant
  - Availability > 99.9%
- Multi-window burn rate alerts with severity escalation
- Error budget tracking with Grafana dashboards

### Dashboards
- **RAG Pipeline Overview**: Request rate, latency, errors
- **Retrieval Service**: Search strategy comparison, reranking metrics
- **LLM Service**: Model performance, token throughput, costs
- **SLO Dashboard**: Compliance gauges, error budget, burn rates
- **RAG Quality Dashboard**: Feedback scores, degradation events

### Evaluation
- Automated RAG quality evaluation with Ragas
- Metrics: context precision, context recall, faithfulness, answer relevancy
- Scheduled weekly evaluations

[Full Observability Documentation](docs/observability/README.md)

---

## Testing

```bash
# Run all tests
make test

# Run tests for specific service
docker-compose exec retrieval-service pytest

# Run specific test file
docker-compose exec retrieval-service pytest tests/test_hybrid_search.py

# Run with coverage
docker-compose exec retrieval-service pytest --cov=. --cov-report=html

# Run E2E smoke tests (requires running services)
pytest tests/e2e/ -v --e2e

# Run E2E tests in Docker
docker-compose -f docker-compose.yml -f tests/e2e/docker-compose.e2e.yaml \
  --profile e2e run --rm e2e-tests
```

### Test Coverage

| Service | Tests | Coverage |
|---------|-------|----------|
| Ingestion | Multiple suites | 90%+ |
| Retrieval | 190+ | 90%+ |
| Orchestrator | 883 | 96% |
| LLM Serving | Multiple suites | 90%+ |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | Comprehensive architecture reference |
| [Ingestion Service](docs/ingestion-service/README.md) | Document processing and indexing |
| [Multi-Store Indexing](docs/ingestion-service/multi-store-indexing.md) | Index status tracking, reconciliation, ACL filtering |
| [Ingestion Rate Limiting](docs/ingestion-service/rate-limiting.md) | Per-tenant rate limiting and priority queues |
| [Retrieval Service](docs/retrieval-service/README.md) | Hybrid search and reranking |
| [Resilience & Degradation](docs/resilience-degradation.md) | Circuit breakers, graceful degradation, timeout policies |
| [Orchestrator Service](docs/orchestrator-service/README.md) | RAG workflow orchestration, answer verification, multi-hop RAG, cost optimization |
| [LLM Serving](docs/llm-serving/README.md) | Model serving infrastructure |
| [Security](docs/security/README.md) | Security and compliance overview |
| [Inter-Service Auth](docs/security/inter-service-authentication.md) | JWT-based service-to-service authentication |
| [Database Security](docs/security/database-security.md) | SSL/TLS for PostgreSQL, Redis, OpenSearch |
| [PII Handling](docs/security/pii-handling.md) | PII detection, redaction modes, compliance |
| [Audit Logging](docs/audit-logging.md) | Hash-chained audit trails, multi-backend storage |
| [Observability](docs/observability/README.md) | Tracing, metrics, logging |
| [Correlation ID Propagation](docs/observability/correlation-id-propagation.md) | Request correlation across services |
| [Trace Hierarchy](docs/observability/trace-hierarchy.md) | Span naming and distributed tracing |
| [Business Metrics](docs/observability/business-quality-metrics.md) | RAG quality and feedback metrics |
| [SLO Definitions](docs/observability/slo-definitions-alerts.md) | Service level objectives and alerts |
| [Kubernetes Setup](docs/infrastructure/kubernetes-setup.md) | K8s deployment guide |
| [Health Checks](docs/health-check-specification.md) | Health endpoint specification |
| [Integration Tests](docs/integration-test-patterns.md) | Testing patterns and guidelines |
| [E2E Smoke Tests](docs/testing/README.md) | End-to-end testing and CI integration |
| [Shared Configuration](docs/shared-configuration.md) | Unified configuration for all services |
| [Developer CLI Tools](docs/developer-cli-tools.md) | CLI tools for debugging and testing |

---

## Performance Targets

| Operation | Target (p95) | Max (p99) |
|-----------|--------------|-----------|
| Query embedding | 20ms | 50ms |
| Semantic search | 50ms | 100ms |
| Keyword search | 30ms | 80ms |
| Reranking | 150ms | 300ms |
| LLM generation | 1500ms | 3000ms |
| **Total E2E** | **2000ms** | **4000ms** |
| TTFT (streaming) | 500ms | 1000ms |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run pre-commit hooks (`pre-commit install && pre-commit run --all-files`)
4. Write tests for your changes
5. Ensure all tests pass (`make test`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Setup

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Install development dependencies
pip install -r requirements-dev.txt

# Run security scans
./scripts/security-scan.sh
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## References

- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [vLLM Documentation](https://docs.vllm.ai/)
- [BGE Embedding Models](https://huggingface.co/BAAI/bge-large-en-v1.5)
- [Ragas Evaluation Framework](https://docs.ragas.io/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
