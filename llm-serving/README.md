# LLM Serving Layer

Production-grade LLM serving infrastructure for the RAG pipeline, providing high-throughput inference for language models, embeddings, and reranking.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM Serving Layer                        │
├─────────────────┬─────────────────┬─────────────────────────┤
│     vLLM        │   Embedding     │     Reranker            │
│   (Port 8000)   │  (Port 8001)    │   (Port 8002)           │
│                 │                 │                         │
│ OpenAI-compat   │ BGE-large-en    │ BGE-reranker-v2-m3      │
│ Chat/Completions│ 1024 dimensions │ Cross-encoder scoring   │
└─────────────────┴─────────────────┴─────────────────────────┘
```

## Services

| Service | Port | Model | Purpose |
|---------|------|-------|---------|
| vLLM | 8000 | Qwen/Qwen2.5-7B-Instruct | Chat completions |
| Embedding | 8001 | BAAI/bge-large-en-v1.5 | Vector embeddings (1024d) |
| Reranker | 8002 | BAAI/bge-reranker-v2-m3 | Document reranking |

## Quick Start

### Prerequisites

- Docker with NVIDIA GPU support (for GPU mode)
- Docker Compose v2+
- NVIDIA drivers and CUDA toolkit

### Running with GPU

```bash
cd llm-serving

# Build and start all services
docker-compose up -d --build

# Check service health
curl http://localhost:8000/health  # vLLM
curl http://localhost:8001/health  # Embedding
curl http://localhost:8002/health  # Reranker

# View logs
docker-compose logs -f
```

### Running without GPU (CPU mode)

```bash
# Use CPU-only configuration (Ollama for LLM)
docker-compose -f docker-compose.cpu.yml up -d --build

# Pull a model in Ollama
docker exec ollama ollama pull qwen2.5:7b
```

## API Usage

### vLLM - Chat Completions

```python
import httpx

response = httpx.post(
    "http://localhost:8000/v1/chat/completions",
    json={
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

### Embedding Service

```python
# OpenAI-compatible endpoint
response = httpx.post(
    "http://localhost:8001/v1/embeddings",
    json={
        "model": "BAAI/bge-large-en-v1.5",
        "input": "Your text here",
        "input_type": "query"  # or "passage" for documents
    }
)
embedding = response.json()["data"][0]["embedding"]  # 1024-dim vector
```

### Reranker Service

```python
response = httpx.post(
    "http://localhost:8002/rerank",
    json={
        "query": "What is machine learning?",
        "documents": [
            "Machine learning is a subset of AI.",
            "The weather is nice today.",
            "Deep learning uses neural networks."
        ],
        "top_k": 2  # Return top 2 results
    }
)
results = response.json()["results"]  # Sorted by relevance score
```

## Unified Gateway (Port 8004)

The gateway provides a single OpenAI-compatible entry point for all services with authentication and rate limiting.

### Gateway Endpoints

| Endpoint               | Method | Description                          |
| ---------------------- | ------ | ------------------------------------ |
| `/v1/chat/completions` | POST   | Text generation (streaming supported)|
| `/v1/embeddings`       | POST   | Generate embeddings                  |
| `/v1/rerank`           | POST   | Rerank documents                     |
| `/v1/models`           | GET    | List available models                |
| `/health`              | GET    | Service health status                |
| `/health/live`         | GET    | Liveness probe                       |
| `/health/ready`        | GET    | Readiness probe                      |
| `/metrics`             | GET    | Prometheus metrics                   |

### Using the Gateway

```python
import httpx

# Chat completions via gateway
response = httpx.post(
    "http://localhost:8004/v1/chat/completions",
    headers={"Authorization": "Bearer <token>"},
    json={
        "model": "qwen2.5-7b-instruct",
        "messages": [{"role": "user", "content": "Hello!"}],
        "stream": False
    }
)

# Embeddings via gateway
response = httpx.post(
    "http://localhost:8004/v1/embeddings",
    headers={"Authorization": "Bearer <token>"},
    json={
        "model": "bge-large-en-v1.5",
        "input": ["Hello, world!"]
    }
)

# Reranking via gateway
response = httpx.post(
    "http://localhost:8004/v1/rerank",
    headers={"Authorization": "Bearer <token>"},
    json={
        "model": "bge-reranker-v2-m3",
        "query": "What is ML?",
        "documents": ["ML is...", "Weather is..."],
        "top_n": 1
    }
)
```

## Authentication & Rate Limiting

### JWT Authentication

```yaml
# Environment variables
AUTH_ENABLED: "true"
JWT_ALGORITHM: "RS256"
JWT_ISSUER: "https://auth.example.com"
JWKS_URL: "https://auth.example.com/.well-known/jwks.json"
```

### API Key Authentication

```
X-API-Key: sk-abc123
```

### Rate Limiting

Token bucket rate limiting with per-tenant quotas:

```yaml
RATE_LIMIT_ENABLED: "true"
RATE_LIMIT_RPM: 60        # Requests per minute
RATE_LIMIT_TPM: 100000    # Tokens per minute
```

Rate limit headers in responses:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1704067200
```

## Configuration Management

Dynamic configuration with hot reload and A/B testing support.

### Configuration File

```yaml
# config/defaults/llm.yaml
endpoints:
  vllm-primary:
    type: llm
    model_id: "Qwen/Qwen2.5-7B-Instruct"
    endpoint_url: "http://vllm-service:8000"
    llm_config:
      temperature: 0.7
      max_tokens: 2048

ab_tests:
  - name: "model-comparison"
    enabled: true
    model_a: "vllm-primary"
    model_b: "vllm-experimental"
    traffic_split: 0.1
```

### Configuration API

| Endpoint                     | Method | Description               |
| ---------------------------- | ------ | ------------------------- |
| `/config`                    | GET    | Get current configuration |
| `/config/endpoints`          | GET    | List model endpoints      |
| `/config/endpoints/{name}`   | PUT    | Update endpoint           |
| `/config/reload`             | POST   | Reload from file          |
| `/config/rollback/{version}` | POST   | Rollback to version       |

## Directory Structure

```
llm-serving/
├── vllm/                       # vLLM service (US-5.1)
│   ├── Dockerfile
│   ├── scripts/
│   │   ├── healthcheck.py
│   │   ├── warmup.py
│   │   └── benchmark.py
│   ├── config/
│   │   └── serving_config.yaml
│   └── k8s/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── hpa.yaml
│       └── configmap.yaml
├── embedding-service/          # Embedding service (US-5.2)
│   ├── Dockerfile
│   ├── api/
│   │   ├── main.py
│   │   └── models.py
│   ├── core/
│   │   ├── embedder.py
│   │   └── batching.py
│   └── k8s/
├── reranker-service/           # Reranker service (US-5.3)
│   ├── Dockerfile
│   ├── api/
│   │   ├── main.py
│   │   └── models.py
│   ├── core/
│   │   ├── reranker.py
│   │   └── batching.py
│   └── k8s/
├── gateway/                    # Unified OpenAI Gateway (US-5.7, US-5.8)
│   ├── api/
│   │   ├── main.py             # FastAPI application
│   │   └── routes.py           # API endpoints
│   ├── clients/
│   │   ├── vllm.py             # vLLM client
│   │   ├── embedding.py        # Embedding client
│   │   └── reranker.py         # Reranker client
│   ├── security/
│   │   ├── auth.py             # JWT authentication
│   │   ├── rate_limit.py       # Token bucket rate limiting
│   │   └── middleware.py       # Security middleware
│   └── k8s/
├── monitoring/                 # Health & Monitoring (US-5.6)
│   ├── health.py               # Health checkers
│   ├── metrics.py              # Prometheus metrics
│   ├── anomaly.py              # Anomaly detection
│   ├── models.py               # Data models
│   ├── prometheus/
│   │   └── rules.yaml          # Alert rules
│   └── grafana/
│       └── dashboards/
├── config/                     # Configuration Management (US-5.4)
│   ├── manager.py              # ConfigurationManager
│   ├── models.py               # Config data models
│   ├── router.py               # A/B routing
│   ├── api/
│   │   └── routes.py           # Config API
│   └── defaults/
│       ├── llm.yaml
│       └── kubernetes.yaml
├── resource_management/        # Resource Management (US-5.5)
│   ├── gpu_monitor.py          # GPU stats (nvidia-smi)
│   ├── batch_optimizer.py      # Dynamic batch optimization
│   ├── cost_tracker.py         # Cost allocation
│   └── k8s/
│       ├── hpa-vllm.yaml
│       ├── hpa-embedding.yaml
│       ├── hpa-reranker.yaml
│       ├── resource-quotas.yaml
│       └── priority-classes.yaml
├── tests/
│   ├── unit/
│   └── integration/
├── docker-compose.yml          # GPU mode
└── docker-compose.cpu.yml      # CPU mode
```

## Kubernetes Deployment

```bash
# Create namespace
kubectl apply -f vllm/k8s/namespace.yaml

# Deploy vLLM
kubectl apply -f vllm/k8s/

# Deploy Embedding service
kubectl apply -f embedding-service/k8s/

# Deploy Reranker service
kubectl apply -f reranker-service/k8s/

# Check pods
kubectl get pods -n llm-serving
```

## Performance Targets

| Metric | Target |
|--------|--------|
| LLM Throughput | >100 tokens/sec |
| LLM TTFT | <500ms |
| Embedding (single) | <50ms |
| Embedding (batch 32) | <200ms |
| Reranker (20 pairs) | <100ms |
| GPU Utilization | >70% |

## Testing

```bash
# Run integration tests (requires services running)
cd llm-serving
pytest tests/integration/ -v -m integration

# Run benchmarks
python vllm/scripts/benchmark.py --requests 100 --concurrent 10
```

## Environment Variables

### vLLM
- `MODEL_NAME`: HuggingFace model ID
- `GPU_MEMORY_UTILIZATION`: 0.0-1.0 (default: 0.90)
- `MAX_MODEL_LEN`: Max context length (default: 8192)

### Embedding Service
- `MODEL_NAME`: Sentence-transformers model
- `EMBEDDING_DIM`: Expected dimension (default: 1024)
- `MAX_BATCH_SIZE`: Max batch size (default: 32)
- `USE_FP16`: Enable FP16 (default: true)
- `DEVICE`: cuda or cpu

### Reranker Service
- `MODEL_NAME`: Cross-encoder model
- `MAX_BATCH_SIZE`: Max pairs per batch (default: 32)
- `NORMALIZE_SCORES`: Apply sigmoid (default: false)

### Gateway

- `VLLM_URL`: vLLM service URL (default: `http://localhost:8000`)
- `EMBEDDING_URL`: Embedding service URL (default: `http://localhost:8001`)
- `RERANKER_URL`: Reranker service URL (default: `http://localhost:8002`)
- `AUTH_ENABLED`: Enable JWT authentication (default: false)
- `RATE_LIMIT_ENABLED`: Enable rate limiting (default: true)
- `RATE_LIMIT_RPM`: Requests per minute (default: 60)
- `RATE_LIMIT_TPM`: Tokens per minute (default: 100000)
- `JWT_ISSUER`: Expected JWT issuer
- `JWT_AUDIENCE`: Expected JWT audience
- `JWKS_URL`: JWKS endpoint URL for key validation

## Monitoring

All services expose Prometheus metrics at `/metrics`.

### Core Metrics

| Metric                            | Type      | Description                         |
| --------------------------------- | --------- | ----------------------------------- |
| `llm_requests_total`              | Counter   | Total requests by service/endpoint  |
| `llm_request_latency_seconds`     | Histogram | Request latency distribution        |
| `llm_tokens_processed_total`      | Counter   | Tokens processed (prompt/completion)|
| `llm_active_requests`             | Gauge     | Currently processing requests       |
| `llm_queue_size`                  | Gauge     | Pending requests in queue           |
| `llm_model_loaded`                | Gauge     | Model load status (0/1)             |
| `llm_gpu_memory_used_bytes`       | Gauge     | GPU memory utilization              |
| `llm_time_to_first_token_seconds` | Histogram | TTFT for streaming                  |

### Service-Specific Metrics

- `embedding_requests_total` - Total embedding requests
- `embedding_request_latency_seconds` - Request latency histogram
- `embedding_batch_size` - Batch size histogram
- `rerank_requests_total` - Total rerank requests
- `rerank_pairs_per_request` - Pairs per request histogram

### Alerting Rules

Prometheus alerting rules are defined in `monitoring/prometheus/rules.yaml`:

| Alert              | Severity | Condition                      |
| ------------------ | -------- | ------------------------------ |
| LLMServiceDown     | critical | Health check failing > 1m      |
| LLMHighLatency     | warning  | p95 latency > 5s for 5m        |
| LLMHighErrorRate   | critical | Error rate > 15% for 5m        |
| LLMGPUMemoryHigh   | warning  | GPU memory > 90%               |
| LLMQueueBacklog    | warning  | Queue size > 100 for 5m        |

### Anomaly Detection

The monitoring module includes automatic anomaly detection for:

- **Latency spikes** (Z-score > 3.0)
- **Error rate increases** (> 15% threshold)
- **Memory trends** (consistent increase over time)

## Implementation Status

| Wave | Component | Status |
|------|-----------|--------|
| 1 | vLLM Deployment (US-5.1) | ✅ |
| 1 | Embedding Service (US-5.2) | ✅ |
| 1 | Reranker Service (US-5.3) | ✅ |
| 2 | Model Configuration (US-5.4) | ✅ |
| 2 | Resource Management (US-5.5) | ✅ |
| 3 | Health & Monitoring (US-5.6) | ✅ |
| 4 | Unified Gateway (US-5.7) | ✅ |
| 4 | Auth & Rate Limiting (US-5.8) | ✅ |

**Epic 5 Complete** - All user stories implemented.
