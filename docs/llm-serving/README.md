# LLM Serving Layer Documentation

The LLM Serving Layer provides a unified, OpenAI-compatible API gateway for all language model operations in the RAG pipeline. It encompasses vLLM for text generation, dedicated embedding and reranker services, and a secure gateway with authentication and rate limiting.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Service Components](#service-components)
  - [vLLM Service](#vllm-service)
  - [Embedding Service](#embedding-service)
  - [Reranker Service](#reranker-service)
  - [Gateway Service](#gateway-service)
- [Security](#security)
  - [Authentication](#authentication)
  - [Rate Limiting](#rate-limiting)
- [Configuration Management](#configuration-management)
- [Health & Monitoring](#health--monitoring)
- [Resource Management](#resource-management)
- [API Reference](#api-reference)
- [Deployment](#deployment)
- [Performance Tuning](#performance-tuning)

---

## Architecture Overview

```
                                 ┌─────────────────────────────────────────────────────────────┐
                                 │                    LLM Serving Layer                         │
                                 ├─────────────────────────────────────────────────────────────┤
                                 │                                                             │
   ┌──────────────┐              │  ┌─────────────────────────────────────────────────────┐   │
   │   Clients    │              │  │                   Gateway Service                    │   │
   │  (Services,  │──────────────┼─▶│  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │   │
   │   Users)     │              │  │  │  Auth   │─▶│  Rate    │─▶│  OpenAI-Compatible │  │   │
   └──────────────┘              │  │  │Middleware│  │ Limiter  │  │      Router        │  │   │
                                 │  │  └─────────┘  └──────────┘  └────────────────────┘  │   │
                                 │  └───────────────────────┬──────────────┬──────────────┘   │
                                 │                          │              │                   │
                                 │            ┌─────────────┼──────────────┼─────────────┐    │
                                 │            │             │              │             │    │
                                 │            ▼             ▼              ▼             │    │
                                 │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │    │
                                 │  │    vLLM      │ │  Embedding   │ │  Reranker    │  │    │
                                 │  │   Service    │ │   Service    │ │   Service    │  │    │
                                 │  │              │ │              │ │              │  │    │
                                 │  │ Qwen2.5-7B   │ │ BGE-large    │ │BGE-reranker  │  │    │
                                 │  │  Instruct    │ │   en-v1.5    │ │   v2-m3      │  │    │
                                 │  │              │ │              │ │              │  │    │
                                 │  │  Port: 8000  │ │  Port: 8001  │ │  Port: 8002  │  │    │
                                 │  └──────────────┘ └──────────────┘ └──────────────┘  │    │
                                 │                                                      │    │
                                 │  ┌────────────────────────────────────────────────┐ │    │
                                 │  │              Shared Infrastructure              │ │    │
                                 │  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │ │    │
                                 │  │  │ Metrics  │  │  Health  │  │   Config     │  │ │    │
                                 │  │  │Collector │  │ Checker  │  │   Manager    │  │ │    │
                                 │  │  └──────────┘  └──────────┘  └──────────────┘  │ │    │
                                 │  └────────────────────────────────────────────────┘ │    │
                                 └─────────────────────────────────────────────────────────────┘
```

### Service Ports

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Gateway | 8004 | HTTP/HTTPS | Unified API entry point |
| vLLM | 8000 | HTTP | Text generation (internal) |
| Embedding | 8001 | HTTP | Vector embedding (internal) |
| Reranker | 8002 | HTTP | Cross-encoder reranking (internal) |

---

## Service Components

### vLLM Service

High-throughput text generation service using vLLM with an OpenAI-compatible API.

**Model:** `Qwen/Qwen2.5-7B-Instruct` (configurable)

**Features:**
- Continuous batching for maximum throughput
- PagedAttention for efficient memory management
- Tensor parallelism support for multi-GPU
- Streaming responses with Server-Sent Events
- OpenAI-compatible `/v1/chat/completions` endpoint

**Configuration:**

```yaml
# vllm/config/serving_config.yaml
model:
  name: "Qwen/Qwen2.5-7B-Instruct"
  tensor_parallel_size: 1
  max_model_len: 8192
  gpu_memory_utilization: 0.90
  dtype: "auto"

serving:
  host: "0.0.0.0"
  port: 8000
  max_num_seqs: 256
  max_num_batched_tokens: 32768

generation:
  default_temperature: 0.7
  default_max_tokens: 2048
  default_top_p: 0.95
```

**Health Endpoints:**
- `GET /health` - Basic health check
- `GET /health/ready` - Model loaded and ready

---

### Embedding Service

Dedicated embedding service using sentence-transformers with batching optimization.

**Model:** `BAAI/bge-large-en-v1.5` (1024 dimensions)

**Features:**
- Intelligent request batching (configurable batch size)
- Dynamic padding for variable-length inputs
- Mean pooling with normalization
- Query instruction prefixing for BGE models
- Connection pooling for concurrent requests

**API:**

```python
POST /v1/embeddings
{
    "model": "BAAI/bge-large-en-v1.5",
    "input": ["text to embed", "another text"],
    "encoding_format": "float"  # or "base64"
}
```

**Response:**

```python
{
    "object": "list",
    "data": [
        {"object": "embedding", "index": 0, "embedding": [0.123, ...]},
        {"object": "embedding", "index": 1, "embedding": [0.456, ...]}
    ],
    "model": "BAAI/bge-large-en-v1.5",
    "usage": {"prompt_tokens": 12, "total_tokens": 12}
}
```

**Configuration:**

```yaml
model:
  name: "BAAI/bge-large-en-v1.5"
  device: "cuda"  # or "cpu"
  normalize: true

batching:
  max_batch_size: 32
  max_wait_time_ms: 50
  dynamic_batching: true
```

---

### Reranker Service

Cross-encoder reranking service for improving retrieval precision.

**Model:** `BAAI/bge-reranker-v2-m3`

**Features:**
- Pairwise relevance scoring
- Batch processing for efficiency
- Top-N filtering with scores
- Multi-document comparison

**API:**

```python
POST /v1/rerank
{
    "model": "BAAI/bge-reranker-v2-m3",
    "query": "What is machine learning?",
    "documents": [
        "Machine learning is a subset of AI...",
        "The weather today is sunny...",
        "Deep learning uses neural networks..."
    ],
    "top_n": 2
}
```

**Response:**

```python
{
    "object": "rerank",
    "results": [
        {"index": 0, "relevance_score": 0.95, "document": {...}},
        {"index": 2, "relevance_score": 0.87, "document": {...}}
    ],
    "model": "BAAI/bge-reranker-v2-m3",
    "usage": {"total_tokens": 156}
}
```

---

### Gateway Service

Unified API gateway providing authentication, rate limiting, and routing.

**Features:**
- OpenAI-compatible API contract
- JWT and API key authentication
- Per-tenant and per-user rate limiting
- Request/response logging
- Security headers
- CORS support

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Text generation (streaming supported) |
| `/v1/embeddings` | POST | Generate embeddings |
| `/v1/rerank` | POST | Rerank documents |
| `/v1/models` | GET | List available models |
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/metrics` | GET | Prometheus metrics |

---

## Security

### Authentication

The gateway supports two authentication methods:

#### JWT Authentication (RS256)

```yaml
# Environment variables
AUTH_ENABLED: "true"
JWT_ALGORITHM: "RS256"
JWT_ISSUER: "https://auth.example.com"
JWT_AUDIENCE: "llm-gateway"
JWKS_URL: "https://auth.example.com/.well-known/jwks.json"
```

**Token Claims:**

```json
{
    "sub": "user-123",
    "tenant_id": "tenant-456",
    "roles": ["user", "admin"],
    "scopes": ["llm:read", "llm:write"]
}
```

**Headers:**

```
Authorization: Bearer <jwt-token>
```

#### API Key Authentication

```yaml
# Configure in gateway config
api_keys:
  sk-abc123:
    tenant_id: "tenant-456"
    user_id: "api-user-1"
    roles: ["api"]
```

**Headers:**

```
X-API-Key: sk-abc123
```

#### Auth Context Propagation

After authentication, context is propagated via headers to downstream services:

```
X-Tenant-ID: tenant-456
X-User-ID: user-123
X-Roles: user,admin
X-Auth-Method: jwt
```

---

### Rate Limiting

Token bucket rate limiting with per-tenant and per-user quotas.

**Configuration:**

```yaml
rate_limiting:
  default_rpm: 60          # Requests per minute
  default_tpm: 100000      # Tokens per minute
  burst_multiplier: 1.5    # Allow 1.5x burst

  tenant_rpm:
    premium: 500
    enterprise: 1000

  user_rpm:
    power-user: 200
```

**Response Headers:**

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1704067200
Retry-After: 30  # When rate limited
```

**Rate Limit Response (429):**

```json
{
    "error": {
        "message": "Rate limit exceeded",
        "type": "rate_limit_error",
        "code": "rate_limit_exceeded"
    }
}
```

---

## Configuration Management

Dynamic configuration with hot reload support.

### Configuration Structure

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
      top_p: 0.95

  embedding-primary:
    type: embedding
    model_id: "BAAI/bge-large-en-v1.5"
    endpoint_url: "http://embedding-service:8001"

  reranker-primary:
    type: reranker
    model_id: "BAAI/bge-reranker-v2-m3"
    endpoint_url: "http://reranker-service:8002"
```

### A/B Testing

Support for model comparison experiments:

```yaml
ab_tests:
  - name: "model-comparison"
    enabled: true
    model_a: "vllm-primary"
    model_b: "vllm-experimental"
    traffic_split: 0.1  # 10% to model_b
    start_time: "2024-01-01T00:00:00Z"
    end_time: "2024-01-31T00:00:00Z"
```

### Configuration API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/config` | GET | Get current configuration |
| `/config/endpoints` | GET | List model endpoints |
| `/config/endpoints/{name}` | PUT | Update endpoint |
| `/config/reload` | POST | Reload from file |
| `/config/rollback/{version}` | POST | Rollback to version |

---

## Health & Monitoring

### Health Checks

**Liveness Probe:**
```
GET /health/live
Response: {"status": "ok"}
```

**Readiness Probe:**
```
GET /health/ready
Response: {
    "status": "healthy",
    "service_name": "llm-gateway",
    "model_loaded": true,
    "components": [
        {"name": "vllm", "status": "healthy", "latency_ms": 15.2},
        {"name": "embedding", "status": "healthy", "latency_ms": 8.5},
        {"name": "reranker", "status": "healthy", "latency_ms": 12.1}
    ]
}
```

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `llm_request_total` | Counter | Total requests by service, endpoint, status |
| `llm_request_latency_seconds` | Histogram | Request latency distribution |
| `llm_tokens_processed_total` | Counter | Tokens processed (prompt/completion) |
| `llm_active_requests` | Gauge | Currently processing requests |
| `llm_queue_size` | Gauge | Pending requests in queue |
| `llm_model_loaded` | Gauge | Model load status (0/1) |
| `llm_gpu_memory_used_bytes` | Gauge | GPU memory utilization |
| `llm_time_to_first_token_seconds` | Histogram | TTFT for streaming |
| `llm_batch_size` | Histogram | Request batch sizes |

### Grafana Dashboard

A pre-configured dashboard is available at `monitoring/grafana/dashboards/llm-overview.json`.

**Panels:**
- Service Health Status
- Request Rate & Latency (p50, p95, p99)
- Time to First Token (TTFT)
- Token Throughput
- GPU Memory & Utilization
- Error Rates by Type
- Queue Size & Active Requests

### Alerting Rules

Prometheus alerting rules in `monitoring/prometheus/rules.yaml`:

| Alert | Severity | Condition |
|-------|----------|-----------|
| LLMServiceDown | critical | Health check failing > 1m |
| HighLatency | warning | p95 latency > 5s for 5m |
| HighErrorRate | critical | Error rate > 15% for 5m |
| GPUMemoryHigh | warning | GPU memory > 90% |
| QueueBacklog | warning | Queue size > 100 for 5m |
| LowThroughput | warning | Throughput dropped > 50% |

### Anomaly Detection

Automatic anomaly detection for:

- **Latency spikes** (Z-score > 3.0)
- **Error rate increases** (> 15% threshold)
- **Memory trends** (consistent increase over time)

---

## Resource Management

### GPU Monitoring

```python
from resource_management import GPUMonitor

monitor = GPUMonitor()
stats = monitor.get_stats()
# Returns: memory_used, memory_total, utilization, temperature
```

### Cost Tracking

```python
from resource_management import CostTracker

tracker = CostTracker(config)
tracker.record_usage(
    model_id="qwen2.5-7b",
    prompt_tokens=1000,
    completion_tokens=500,
    tenant_id="tenant-123"
)

summary = tracker.get_cost_summary()
# Returns: costs by model, tenant, time period
```

### Batch Optimization

Automatic batch size optimization based on:
- GPU memory availability
- Current latency SLO
- Request queue depth
- Historical throughput data

---

## API Reference

### Chat Completions

```bash
curl -X POST http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "model": "qwen2.5-7b-instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7,
    "max_tokens": 1024,
    "stream": false
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8004/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "model": "qwen2.5-7b-instruct",
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "stream": true
  }'
```

### Embeddings

```bash
curl -X POST http://localhost:8004/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "model": "bge-large-en-v1.5",
    "input": ["Hello, world!", "How are you?"]
  }'
```

### Reranking

```bash
curl -X POST http://localhost:8004/v1/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "model": "bge-reranker-v2-m3",
    "query": "What is machine learning?",
    "documents": ["ML is...", "Weather is...", "AI includes..."],
    "top_n": 2
  }'
```

---

## Deployment

### Local Development (Docker Compose)

```bash
cd llm-serving

# With GPU support
docker-compose up -d

# CPU-only mode
docker-compose -f docker-compose.cpu.yml up -d
```

### Kubernetes

```bash
# Apply namespace and base resources
kubectl apply -f vllm/k8s/namespace.yaml
kubectl apply -f vllm/k8s/

# Deploy embedding and reranker services
kubectl apply -f embedding-service/k8s/
kubectl apply -f reranker-service/k8s/

# Deploy gateway
kubectl apply -f gateway/k8s/
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_URL` | `http://localhost:8000` | vLLM service URL |
| `EMBEDDING_URL` | `http://localhost:8001` | Embedding service URL |
| `RERANKER_URL` | `http://localhost:8002` | Reranker service URL |
| `AUTH_ENABLED` | `false` | Enable JWT authentication |
| `RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `RATE_LIMIT_RPM` | `60` | Requests per minute |
| `RATE_LIMIT_TPM` | `100000` | Tokens per minute |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Performance Tuning

### Latency Targets

| Operation | Target (p95) | Max (p99) |
|-----------|--------------|-----------|
| Embedding (single) | 20ms | 50ms |
| Embedding (batch 32) | 100ms | 200ms |
| Reranking (10 docs) | 150ms | 300ms |
| LLM TTFT | 200ms | 500ms |
| LLM generation | 1500ms | 3000ms |

### Throughput Optimization

1. **Batching**: Increase `max_batch_size` for embedding/reranker
2. **Concurrency**: Adjust `max_num_seqs` in vLLM config
3. **GPU memory**: Tune `gpu_memory_utilization` (0.85-0.95)
4. **Tensor parallelism**: Use multiple GPUs with `tensor_parallel_size`

### Memory Management

- Monitor GPU memory via Prometheus metrics
- Set appropriate `max_model_len` based on use case
- Enable KV cache quantization for memory savings
- Use PagedAttention (default in vLLM)

---

## Directory Structure

```
llm-serving/
├── config/
│   ├── defaults/           # Default configurations
│   ├── models.py           # Pydantic config models
│   ├── manager.py          # Configuration manager
│   └── router.py           # Model routing logic
├── embedding-service/
│   ├── api/                # FastAPI application
│   ├── core/               # Embedding logic, batching
│   └── k8s/                # Kubernetes manifests
├── reranker-service/
│   ├── api/                # FastAPI application
│   ├── core/               # Reranking logic
│   └── k8s/                # Kubernetes manifests
├── gateway/
│   ├── api/                # FastAPI gateway
│   ├── clients/            # Service clients
│   ├── security/           # Auth, rate limiting
│   └── k8s/                # Kubernetes manifests
├── monitoring/
│   ├── health.py           # Health checker
│   ├── metrics.py          # Prometheus metrics
│   ├── anomaly.py          # Anomaly detection
│   ├── prometheus/         # Alert rules
│   └── grafana/            # Dashboards
├── resource_management/
│   ├── gpu_monitor.py      # GPU stats
│   ├── cost_tracker.py     # Usage tracking
│   └── batch_optimizer.py  # Dynamic batching
├── vllm/
│   ├── config/             # vLLM configuration
│   ├── scripts/            # Warmup, benchmark
│   └── k8s/                # Kubernetes manifests
├── tests/
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── docker-compose.yml      # GPU development
└── docker-compose.cpu.yml  # CPU-only development
```

---

## Implementation Status

All user stories for Epic 5 (LLM Serving Layer) have been implemented:

| Wave | Component                      | User Story | Status |
| ---- | ------------------------------ | ---------- | ------ |
| 1    | vLLM Deployment                | US-5.1     | Done   |
| 1    | Embedding Service              | US-5.2     | Done   |
| 1    | Reranker Service               | US-5.3     | Done   |
| 2    | Model Configuration            | US-5.4     | Done   |
| 2    | Resource Management            | US-5.5     | Done   |
| 3    | Health & Monitoring            | US-5.6     | Done   |
| 4    | Unified OpenAI Gateway         | US-5.7     | Done   |
| 4    | Auth & Rate Limiting           | US-5.8     | Done   |

For detailed implementation plans and user stories, see `workflow/done/05-llm-serving/`.

---

## Related Documentation

- [Architecture Overview](../architecture.md)
- [Health Check Specification](../health-check-specification.md)
- [Kubernetes Setup](../infrastructure/kubernetes-setup.md)
- [GPU Workloads Runbook](../infrastructure/gpu-workloads-runbook.md)
- [Epic 5 Implementation Plan](../../workflow/done/05-llm-serving/implementation-plan.md)
