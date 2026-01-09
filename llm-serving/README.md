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

## Directory Structure

```
llm-serving/
├── vllm/                    # vLLM service (US-5.1)
│   ├── Dockerfile
│   ├── scripts/
│   │   ├── healthcheck.py
│   │   ├── warmup.py
│   │   └── benchmark.py
│   ├── config/
│   └── k8s/
├── embedding-service/        # Embedding service (US-5.2)
│   ├── Dockerfile
│   ├── api/
│   │   ├── main.py
│   │   └── models.py
│   ├── core/
│   │   ├── embedder.py
│   │   └── batching.py
│   └── k8s/
├── reranker-service/         # Reranker service (US-5.3)
│   ├── Dockerfile
│   ├── api/
│   │   ├── main.py
│   │   └── models.py
│   ├── core/
│   │   ├── reranker.py
│   │   └── batching.py
│   └── k8s/
├── gateway/                  # Unified gateway (Wave 4)
├── monitoring/               # Prometheus/Grafana
├── config/                   # Shared configuration
├── tests/
│   └── integration/
├── docker-compose.yml        # GPU mode
└── docker-compose.cpu.yml    # CPU mode
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

## Monitoring

All services expose Prometheus metrics at `/metrics`:

- `embedding_requests_total` - Total embedding requests
- `embedding_request_latency_seconds` - Request latency histogram
- `rerank_requests_total` - Total rerank requests
- `rerank_pairs_per_request` - Pairs per request histogram

## Implementation Status

| Wave | Component | Status |
|------|-----------|--------|
| 1 | vLLM Deployment (US-5.1) | ✅ |
| 1 | Embedding Service (US-5.2) | ✅ |
| 1 | Reranker Service (US-5.3) | ✅ |
| 2 | Model Configuration (US-5.4) | 🔲 |
| 2 | Resource Management (US-5.5) | 🔲 |
| 3 | Health & Monitoring (US-5.6) | 🔲 |
| 4 | Unified Gateway (US-5.7) | 🔲 |
| 4 | Auth & Rate Limiting (US-5.8) | 🔲 |
