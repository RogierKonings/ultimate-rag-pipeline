# Rust Embedding Service Design

**Date:** 2025-01-30
**Status:** Approved
**Replaces:** Python embedding service (`services/embedding/`)

## Overview

Rewrite the embedding service in Rust using Candle (via `sentence-transformers-rs`) to eliminate Python dependency and improve deployment characteristics. The new service maintains full OpenAI API compatibility for drop-in replacement.

## Architecture

### Technology Stack

- **ML Framework:** Candle via `sentence-transformers-rs`
- **HTTP Server:** Axum (consistent with other Rust services)
- **Tokenization:** HuggingFace `tokenizers` crate (Rust-native)
- **Model Loading:** HuggingFace Hub integration

### Supported Models

Pre-configured support for:
- `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) - **default**
- `BAAI/bge-small-en-v1.5` (384 dimensions)
- `BAAI/bge-large-en-v1.5` (1024 dimensions)

Custom models supported if they use BERT, MPNet, DistilBERT, or XLMRoberta architectures.

## Crate Structure

```
crates/rag-embedding/
├── Cargo.toml
├── src/
│   ├── lib.rs              # Public API exports
│   ├── config.rs           # Configuration (model, batch size, etc.)
│   ├── error.rs            # Error types
│   ├── model.rs            # Candle model wrapper
│   ├── api/
│   │   ├── mod.rs
│   │   ├── routes.rs       # /v1/embeddings, /v1/models, /health
│   │   ├── types.rs        # OpenAI-compatible request/response schemas
│   │   └── state.rs        # App state (model handle)
│   └── bin/
│       └── main.rs         # Service entrypoint
```

## Dependencies

```toml
[dependencies]
# ML inference
sentence-transformers-rs = "0.1"
candle-core = "0.8"
tokenizers = "0.20"
hf-hub = "0.3"

# HTTP server
axum = "0.7"
tower = "0.4"
tower-http = { version = "0.5", features = ["trace", "cors", "timeout"] }

# Async runtime
tokio = { version = "1.35", features = ["full", "signal"] }

# Serialization
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# Error handling
thiserror = "1.0"

# Logging
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | HuggingFace model ID |
| `EMBEDDING_BATCH_SIZE` | `32` | Maximum texts per request |
| `EMBEDDING_PORT` | `8080` | HTTP server port |
| `EMBEDDING_HOST` | `0.0.0.0` | HTTP server bind address |
| `HF_HOME` | `~/.cache/huggingface` | Model cache directory |
| `RUST_LOG` | `info` | Log level |

## API Specification

### POST /v1/embeddings

OpenAI-compatible embedding endpoint.

**Request:**
```json
{
  "input": ["text1", "text2"] | "single text",
  "model": "optional, ignored",
  "encoding_format": "float"
}
```

**Response:**
```json
{
  "object": "list",
  "data": [
    { "object": "embedding", "index": 0, "embedding": [0.1, 0.2, ...] },
    { "object": "embedding", "index": 1, "embedding": [0.3, 0.4, ...] }
  ],
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "usage": { "prompt_tokens": 10, "total_tokens": 10 }
}
```

**Errors:**
- `400`: Empty input or batch size exceeded
- `503`: Model still loading
- `500`: Inference failure

### GET /v1/models

List available models.

**Response:**
```json
{
  "object": "list",
  "data": [{
    "id": "sentence-transformers/all-MiniLM-L6-v2",
    "object": "model",
    "created": 0,
    "owned_by": "local",
    "metadata": { "dimension": 384, "max_batch_size": 32 }
  }]
}
```

### GET /health

Health check endpoint.

**Response (loading):**
```json
{ "status": "loading", "model": "...", "dimension": null }
```

**Response (ready):**
```json
{ "status": "healthy", "model": "...", "dimension": 384, "max_batch_size": 32 }
```

### GET /

Service information.

**Response:**
```json
{
  "service": "embedding-service",
  "version": "1.0.0",
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "endpoints": {
    "embeddings": "/v1/embeddings",
    "models": "/v1/models",
    "health": "/health"
  }
}
```

## Core Components

### EmbeddingModel (model.rs)

Thread-safe wrapper around `sentence-transformers-rs`:

```rust
pub struct EmbeddingModel {
    model: SentenceTransformer,
    config: ModelConfig,
}

impl EmbeddingModel {
    pub fn load(config: &ModelConfig) -> Result<Self>;
    pub fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    pub fn dimensions(&self) -> usize;
    pub fn model_id(&self) -> &str;
}
```

**Thread safety:**
- `SentenceTransformer` is `Send + Sync`
- Wrapped in `Arc<EmbeddingModel>` for shared state
- CPU inference via `tokio::task::spawn_blocking`

**Normalization:**
- L2 normalization applied automatically (matches Python `normalize_embeddings=True`)

## Service Lifecycle

### Startup

1. Load configuration from environment
2. Initialize tracing subscriber
3. Download/load model from HuggingFace Hub (blocking)
4. Build Axum router with `Arc<AppState>`
5. Bind and serve HTTP

### Shutdown

- SIGTERM/SIGINT handling via `tokio::signal`
- Graceful connection draining
- Model resources freed on drop

### Logging

```
INFO Loading embedding model: sentence-transformers/all-MiniLM-L6-v2
INFO Model loaded in 2.34s. Embedding dimension: 384
INFO Embedding service listening on 0.0.0.0:8080
```

## Migration Plan

### Phase 1: Build Rust Service

1. Create `crates/rag-embedding` crate
2. Implement config, error, model modules
3. Implement API routes
4. Add service binary
5. Write unit and integration tests

### Phase 2: Docker Integration

1. Create `Dockerfile` for Rust embedding service
2. Update `docker-compose.yml` to use new service
3. Verify same port (8080) and environment variables

### Phase 3: Validation

1. Run both services side-by-side
2. Compare embedding outputs (should be near-identical)
3. Benchmark latency and throughput
4. Validate with retrieval service integration

### Phase 4: Cleanup

1. Remove `services/embedding/main.py`
2. Remove `services/embedding/Dockerfile.cpu`
3. Update CLAUDE.md documentation

## Files to Create

- `crates/rag-embedding/Cargo.toml`
- `crates/rag-embedding/src/lib.rs`
- `crates/rag-embedding/src/config.rs`
- `crates/rag-embedding/src/error.rs`
- `crates/rag-embedding/src/model.rs`
- `crates/rag-embedding/src/api/mod.rs`
- `crates/rag-embedding/src/api/routes.rs`
- `crates/rag-embedding/src/api/types.rs`
- `crates/rag-embedding/src/api/state.rs`
- `crates/rag-embedding/src/bin/main.rs`
- `crates/rag-embedding/Dockerfile`

## Files to Delete (after validation)

- `services/embedding/main.py`
- `services/embedding/Dockerfile.cpu`

## Sources

- [Candle - HuggingFace Rust ML Framework](https://github.com/huggingface/candle)
- [sentence-transformers-rs](https://github.com/jwnz/sentence-transformers-rs)
- [Building Sentence Transformers in Rust](https://dev.to/mayu2008/building-sentence-transformers-in-rust-a-practical-guide-with-burn-onnx-runtime-and-candle-281k)
