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

### Hybrid Retrieval
- Semantic search via Qdrant (HNSW indexing, cosine similarity)
- Keyword search via OpenSearch (BM25 with fuzzy matching)
- Reciprocal Rank Fusion (RRF) for result combination
- Cross-encoder reranking for precision improvement
- Query preprocessing with expansion and HyDE support

### RAG Orchestration
- LangGraph-based stateful workflows
- Intelligent query routing (simple, complex, no-retrieval strategies)
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
cp .env.example .env
# Edit .env with your configuration
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

5. **Access the services**

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

Copy `.env.example` to `.env` and configure:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://raguser:ragpass@localhost:5432/ragpipeline

# Vector Store
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=documents

# Search
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=documents

# Cache
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=ragredis

# Object Storage
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123

# Embedding
EMBEDDING_SERVICE_URL=http://localhost:8080
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5

# LLM
LLM_SERVICE_URL=http://localhost:8004
LLM_MODEL=llama3.1:8b

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
LOG_LEVEL=INFO

# Security
JWT_SECRET=your-jwt-secret-change-in-production
```

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
- Multi-store indexing (Qdrant, OpenSearch, PostgreSQL)
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
- ACL enforcement based on user context
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

### Orchestrator Service

**Port:** 8003

Central coordination layer managing the complete query lifecycle.

**Features:**
- LangGraph-based stateful workflows
- Intelligent query routing (simple, complex, no-retrieval)
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
- API key support for service-to-service communication
- Redis-backed token blocklist for revocation

### Authorization
- Role-based access control (RBAC) with 9 predefined roles
- Document-level ACLs with visibility levels
- Mandatory tenant isolation on all operations

### Data Protection
- AES-256-GCM field encryption for sensitive data
- TLS 1.3 for all network communication
- Encrypted storage volumes (EBS, GCE PD)
- MinIO server-side encryption

### Audit & Compliance
- Tamper-evident audit logging with hash chaining
- PII detection and redaction
- SOC 2 Type II, GDPR, HIPAA compliance support

[Full Security Documentation](docs/security/README.md)

---

## Observability

### Distributed Tracing
- OpenTelemetry instrumentation across all services
- Jaeger for trace visualization
- RAG-specific semantic attributes

### Metrics
- Prometheus metrics following `rag_<subsystem>_<metric>_<unit>` naming
- Pre-defined SLOs with burn rate alerting
- Key metrics: query latency, TTFT, cache hit rate, error rate

### Dashboards
- **RAG Pipeline Overview**: Request rate, latency, errors
- **Retrieval Service**: Search strategy comparison, reranking metrics
- **LLM Service**: Model performance, token throughput, costs
- **SLO Dashboard**: Compliance gauges, error budget, burn rates

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
| [Retrieval Service](docs/retrieval-service/README.md) | Hybrid search and reranking |
| [Orchestrator Service](docs/orchestrator-service/README.md) | RAG workflow orchestration |
| [LLM Serving](docs/llm-serving/README.md) | Model serving infrastructure |
| [Security](docs/security/README.md) | Security and compliance |
| [Observability](docs/observability/README.md) | Tracing, metrics, logging |
| [Kubernetes Setup](docs/infrastructure/kubernetes-setup.md) | K8s deployment guide |
| [Health Checks](docs/health-check-specification.md) | Health endpoint specification |
| [Integration Tests](docs/integration-test-patterns.md) | Testing patterns and guidelines |

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
