# Embedding Service

> **Version:** 1.0.0
> **Status:** Production
> **Last Updated:** January 2026
> **Language:** Rust

## Overview

The Embedding Service provides a dedicated, OpenAI-compatible API for generating text embeddings. It runs as a standalone Rust microservice using ONNX-based inference via the `fastembed` crate, enabling high-performance semantic search across the RAG pipeline.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                      Embedding Service                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Axum HTTP Application                   │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │   │
│  │  │  /v1/embeddings │  │   /health     │  │  /v1/models │  │   │
│  │  │   (POST)       │  │   (GET)       │  │   (GET)     │  │   │
│  │  └───────────────┘  └───────────────┘  └─────────────┘  │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                   │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │               Tokio spawn_blocking Pool                    │   │
│  │            (Async CPU-bound operations)                    │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                   │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │                  fastembed (ONNX Runtime)                  │   │
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
| **Implementation** | `crates/rag-embedding/` |

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
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model ID to use |
| `EMBEDDING_BATCH_SIZE` | `32` | Maximum texts per request |
| `EMBEDDING_HOST` | `0.0.0.0` | Server bind address |
| `EMBEDDING_PORT` | `8080` | Server port |
| `RUST_LOG` | `info` | Log level filter |

### Supported Models

The service supports the following ONNX-compatible models via `fastembed`:

| Model | Dimensions | Use Case |
|-------|------------|----------|
| `all-MiniLM-L6-v2` | 384 | Fast, general-purpose (default) |
| `BAAI/bge-small-en-v1.5` | 384 | BGE small model |

> **Note:** When changing models, ensure the Qdrant collection dimensions match.

## Project Structure

```text
crates/rag-embedding/
├── Cargo.toml
├── src/
│   ├── bin/
│   │   └── main.rs          # Service entry point
│   ├── lib.rs               # Library exports
│   ├── config.rs            # Configuration management
│   ├── model.rs             # fastembed model wrapper
│   ├── error.rs             # Error types
│   └── api/
│       ├── mod.rs           # API module exports
│       ├── routes.rs        # Axum route handlers
│       ├── types.rs         # Request/response types
│       ├── state.rs         # Application state
│       └── error.rs         # API error handling
```

## Key Implementation Details

### Thread-Safe Model Wrapper

The embedding model is wrapped in an `Arc<TextEmbedding>` for thread-safe sharing:

```rust
pub struct EmbeddingModelWrapper {
    inner: Arc<TextEmbedding>,
    model_id: String,
    dimensions: usize,
}
```

### Async CPU-bound Operations

Embedding generation runs in a blocking task pool to avoid blocking the Tokio runtime:

```rust
let embeddings = tokio::task::spawn_blocking(move || model.embed(&texts))
    .await
    .map_err(|e| ApiError::internal(format!("Task failed: {e}")))?
    .map_err(ApiError::from)?;
```

### L2 Normalization

Embeddings are automatically L2-normalized by `fastembed`, making them suitable for cosine similarity searches.

## Docker Compose Configuration

```yaml
embedding-service:
  build:
    context: .
    dockerfile: crates/rag-embedding/Dockerfile
  container_name: rag-embedding
  ports:
    - "8080:8080"
  environment:
    - EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
    - EMBEDDING_BATCH_SIZE=32
    - RUST_LOG=info
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
        memory: 2G
      reservations:
        memory: 1G
  profiles:
    - app
```

## Dockerfile

The service uses a multi-stage Rust build:

```dockerfile
# Build stage
FROM rust:1.83-slim AS builder

WORKDIR /app
COPY . .

RUN cargo build --release -p rag-embedding

# Runtime stage
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/embedding-service /usr/local/bin/

ENV RUST_LOG=info
EXPOSE 8080

CMD ["embedding-service"]
```

## Integration with Other Services

### Retrieval Service

The Retrieval Service connects to the Embedding Service to generate query embeddings for semantic search.

**Configuration:**

```rust
// In crates/rag-retrieval/src/config.rs
pub struct RetrievalConfig {
    /// Embedding service URL
    pub embedding_service_url: String,  // Default: "http://embedding-service:8080"
    /// Embedding model name
    pub embedding_model: String,        // Default: "all-MiniLM-L6-v2"
    /// Embedding dimensions
    pub embedding_dimension: usize,     // Default: 384
}
```

### Ingestion Service

The Ingestion Service uses the Embedding Service to generate embeddings during document indexing.

**Vector Store Configuration:**

The Qdrant `documents` collection must match the embedding dimensions:

```rust
// In crates/rag-ingestion/src/indexing/qdrant.rs
const VECTOR_SIZE: usize = 384;  // Must match embedding model dimensions
```

## Performance

### Latency Benchmarks

| Operation | Latency (p50) | Latency (p95) |
|-----------|---------------|---------------|
| Single text embedding | 10ms | 20ms |
| Batch of 10 texts | 35ms | 70ms |
| Batch of 32 texts | 100ms | 180ms |

### Memory Usage

| Model | Idle Memory | Peak Memory |
|-------|-------------|-------------|
| `all-MiniLM-L6-v2` | ~200MB | ~500MB |
| `BAAI/bge-small-en-v1.5` | ~250MB | ~600MB |

## Troubleshooting

### Common Issues

#### 1. Model Download Timeout

**Error:** Model download takes too long on first startup

**Solution:** Pre-cache models in a volume:

```yaml
volumes:
  - model_cache:/root/.cache/huggingface
```

#### 2. Memory Pressure

**Cause:** Batch size too large or concurrent requests

**Solutions:**

- Reduce `EMBEDDING_BATCH_SIZE`
- Increase container memory limit
- Add request queue/rate limiting

#### 3. DNS Resolution Failure

**Error:** `failed to lookup address: embedding-service`

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

```text
2026-01-30T10:00:00.000Z  INFO embedding_service: Starting Rust Embedding Service v1.0.0
2026-01-30T10:00:00.001Z  INFO rag_embedding::config: Configuration loaded model="sentence-transformers/all-MiniLM-L6-v2" max_batch_size=32
2026-01-30T10:00:00.002Z  INFO rag_embedding::model: Loading embedding model: sentence-transformers/all-MiniLM-L6-v2
2026-01-30T10:00:01.500Z  INFO rag_embedding::model: Model loaded in 1.50s. Embedding dimension: 384
2026-01-30T10:00:01.501Z  INFO embedding_service: Embedding service listening on 0.0.0.0:8080
```

## Development

### Running Tests

```bash
# Run all tests
cd crates && cargo test -p rag-embedding

# Run with verbose output
cd crates && cargo test -p rag-embedding -- --nocapture

# Run specific test
cd crates && cargo test -p rag-embedding test_model_type_dimensions
```

### Local Development

```bash
# Build the service
cd crates && cargo build -p rag-embedding

# Run locally
cd crates && cargo run -p rag-embedding

# Or run the release build
cd crates && cargo run --release -p rag-embedding
```

### Code Quality

```bash
# Lint with clippy
cd crates && cargo clippy -p rag-embedding -- -D warnings

# Format code
cd crates && cargo fmt -p rag-embedding
```

## Related Documentation

- [Architecture Overview](../architecture.md)
- [Retrieval Service](../retrieval-service/README.md)
- [Ingestion Service](../ingestion-service/README.md)
- [Health Check Specification](../health-check-specification.md)
