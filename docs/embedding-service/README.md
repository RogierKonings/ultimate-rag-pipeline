# Embedding Service

> **Version:** 1.0.0
> **Status:** Production
> **Last Updated:** January 2026

## Overview

The Embedding Service provides a dedicated, OpenAI-compatible API for generating text embeddings. It runs as a standalone microservice using sentence-transformers, enabling semantic search across the RAG pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Embedding Service                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   FastAPI Application                     │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │   │
│  │  │  /v1/embeddings │  │   /health     │  │  /v1/models │  │   │
│  │  │   (POST)       │  │   (GET)       │  │   (GET)     │  │   │
│  │  └───────────────┘  └───────────────┘  └─────────────┘  │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                   │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │                  Thread Pool Executor                      │   │
│  │            (Async CPU-bound operations)                    │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                   │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │               SentenceTransformer Model                    │   │
│  │                  all-MiniLM-L6-v2                         │   │
│  │                   (384 dimensions)                         │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Service Details

| Property | Value |
|----------|-------|
| **Service Name** | `embedding-service` |
| **Container Name** | `rag-embedding` |
| **Port** | 8080 |
| **Default Model** | `all-MiniLM-L6-v2` |
| **Vector Dimensions** | 384 |
| **Max Batch Size** | 32 |

## API Reference

### Generate Embeddings

**Endpoint:** `POST /v1/embeddings`

Generate embeddings for input text(s). This endpoint is compatible with the OpenAI embeddings API.

**Request:**

```json
{
    "input": "text to embed",
    "model": "all-MiniLM-L6-v2",
    "encoding_format": "float"
}
```

Or with multiple texts:

```json
{
    "input": ["first text", "second text", "third text"],
    "model": "all-MiniLM-L6-v2"
}
```

**Response:**

```json
{
    "data": [
        {
            "embedding": [0.123, -0.456, ...],
            "index": 0,
            "object": "embedding"
        }
    ],
    "model": "all-MiniLM-L6-v2",
    "object": "list",
    "usage": {
        "prompt_tokens": 4,
        "total_tokens": 4
    }
}
```

**cURL Example:**

```bash
curl -X POST "http://localhost:8080/v1/embeddings" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What is machine learning?",
    "model": "all-MiniLM-L6-v2"
  }'
```

### Health Check

**Endpoint:** `GET /health`

Returns service health status including model information.

**Response:**

```json
{
    "status": "healthy",
    "model": "all-MiniLM-L6-v2",
    "dimension": 384,
    "max_batch_size": 32
}
```

### List Models

**Endpoint:** `GET /v1/models`

Returns available embedding models (OpenAI compatibility).

**Response:**

```json
{
    "object": "list",
    "data": [
        {
            "id": "all-MiniLM-L6-v2",
            "object": "model",
            "owned_by": "local",
            "metadata": {
                "dimension": 384,
                "max_batch_size": 32
            }
        }
    ]
}
```

### Service Info

**Endpoint:** `GET /`

Returns basic service information and available endpoints.

**Response:**

```json
{
    "service": "embedding-service",
    "version": "1.0.0",
    "model": "all-MiniLM-L6-v2",
    "endpoints": {
        "embeddings": "/v1/embeddings",
        "models": "/v1/models",
        "health": "/health"
    }
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | `all-MiniLM-L6-v2` | Sentence-transformers model to use |
| `MAX_BATCH_SIZE` | `32` | Maximum texts per request |
| `TOKENIZERS_PARALLELISM` | `false` | Disable tokenizer parallelism warnings |

### Supported Models

The service supports any sentence-transformers compatible model. Common options:

| Model | Dimensions | Size | Use Case |
|-------|------------|------|----------|
| `all-MiniLM-L6-v2` | 384 | ~80MB | Fast, general-purpose (default) |
| `all-mpnet-base-v2` | 768 | ~420MB | Higher quality, slower |
| `BAAI/bge-small-en-v1.5` | 384 | ~130MB | BGE small model |
| `BAAI/bge-base-en-v1.5` | 768 | ~440MB | BGE base model |
| `BAAI/bge-large-en-v1.5` | 1024 | ~1.3GB | Highest quality, requires more memory |

> **Note:** When changing models, ensure the Qdrant collection dimensions match.

## Docker Compose Configuration

```yaml
embedding-service:
  build:
    context: ./services/embedding
    dockerfile: Dockerfile.cpu
  container_name: rag-embedding
  ports:
    - "8080:8080"
  environment:
    - MODEL_NAME=all-MiniLM-L6-v2
    - MAX_BATCH_SIZE=32
  volumes:
    - model_cache:/root/.cache/huggingface
  networks:
    - rag-network
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 60s
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: 4G
      reservations:
        memory: 2G
  profiles:
    - app
```

## Dockerfile

The service uses a CPU-optimized Dockerfile (`Dockerfile.cpu`):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Pin numpy < 2 for PyTorch 2.2 compatibility
RUN pip install --no-cache-dir \
    "numpy<2" \
    torch==2.2.0 \
    sentence-transformers==2.7.0 \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.0 \
    pydantic==2.8.0

COPY . .

ENV PYTHONPATH=/app
ENV TOKENIZERS_PARALLELISM=false

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Integration with Other Services

### Retrieval Service

The Retrieval Service connects to the Embedding Service to generate query embeddings for semantic search.

**Configuration in `services/retrieval/config.py`:**

```python
# Embedding service (separate from LLM Gateway)
embedding_service_url: str = "http://embedding-service:8080"

# Embedding settings
embedding_model: str = "all-MiniLM-L6-v2"
embedding_dimension: int = 384
embedding_prefix: str = ""  # MiniLM doesn't use query prefix
```

### Ingestion Service

The Ingestion Service uses the same model (or a compatible service) to generate embeddings during document indexing.

**Vector Store Configuration:**

The Qdrant `video_chunks` collection must match the embedding dimensions:

```python
# In services/ingestion/processors/video/qdrant_indexer.py
VECTOR_SIZE = 384  # Must match embedding model dimensions
```

## Performance

### Latency Benchmarks

| Operation | Latency (p50) | Latency (p95) |
|-----------|---------------|---------------|
| Single text embedding | 15ms | 30ms |
| Batch of 10 texts | 50ms | 100ms |
| Batch of 32 texts | 150ms | 250ms |

### Memory Usage

| Model | Idle Memory | Peak Memory |
|-------|-------------|-------------|
| `all-MiniLM-L6-v2` | ~300MB | ~800MB |
| `BAAI/bge-large-en-v1.5` | ~1.5GB | ~3GB |

## Troubleshooting

### Common Issues

#### 1. NumPy Compatibility Error

**Error:** `Embedding generation failed: Numpy is not available`

**Solution:** Ensure `numpy<2` is installed. PyTorch 2.2 is not compatible with NumPy 2.x.

```dockerfile
RUN pip install --no-cache-dir "numpy<2"
```

#### 2. Container Crashes During Inference (Exit Code 139)

**Cause:** Memory issues or PyTorch compatibility problems.

**Solutions:**
- Increase container memory limit
- Use a smaller model like `all-MiniLM-L6-v2`
- Ensure compatible package versions

#### 3. Model Loading Timeout

**Cause:** First-time model download takes too long.

**Solution:** Pre-cache models in a volume:

```yaml
volumes:
  - model_cache:/root/.cache/huggingface
```

#### 4. DNS Resolution Failure

**Error:** `socket.gaierror: [Errno -2] Name or service not known`

**Cause:** Embedding service not running or network issues.

**Solution:** Ensure embedding service is healthy before starting dependent services:

```bash
docker-compose --profile app up -d embedding-service
# Wait for healthy status
docker-compose --profile app up -d retrieval-service
```

### Logs

View service logs:

```bash
docker logs rag-embedding -f
```

Example healthy startup logs:

```
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:main:Loading embedding model: all-MiniLM-L6-v2
INFO:sentence_transformers.SentenceTransformer:Load pretrained SentenceTransformer: all-MiniLM-L6-v2
INFO:sentence_transformers.SentenceTransformer:Use pytorch device_name: cpu
INFO:main:Model loaded in 1.76s. Embedding dimension: 384
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

## Development

### Local Testing

```bash
# Build the service
docker-compose build embedding-service

# Start the service
docker-compose --profile app up -d embedding-service

# Test the endpoint
curl http://localhost:8080/health

curl -X POST http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": "test query"}'
```

### Running Without Docker

```bash
cd services/embedding

# Install dependencies
pip install "numpy<2" torch==2.2.0 sentence-transformers==2.7.0 \
    fastapi==0.111.0 uvicorn[standard]==0.30.0 pydantic==2.8.0

# Set environment variables
export MODEL_NAME=all-MiniLM-L6-v2
export MAX_BATCH_SIZE=32

# Run the service
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Related Documentation

- [Architecture Overview](../architecture.md)
- [LLM Serving Layer](../llm-serving/README.md)
- [Retrieval Service](../retrieval-service/README.md)
- [Health Check Specification](../health-check-specification.md)
