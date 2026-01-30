# LLM Gateway

> **Version:** 1.0.0
> **Status:** Production
> **Last Updated:** January 2026
> **Language:** Rust

## Overview

The LLM Gateway is a unified API gateway providing OpenAI-compatible endpoints for embeddings, reranking, and LLM inference. Built in Rust with Axum, it serves as a central access point with JWT/API key authentication, token bucket rate limiting, and Prometheus metrics.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LLM Gateway                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                      Axum HTTP Application                          │    │
│  │                                                                     │    │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐   │    │
│  │  │ Authentication   │→ │  Rate Limiting   │→ │  Route Handler │   │    │
│  │  │   Middleware     │  │   Middleware     │  │                │   │    │
│  │  └──────────────────┘  └──────────────────┘  └────────────────┘   │    │
│  │                                                                     │    │
│  │  Routes:                                                            │    │
│  │  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────┐  │    │
│  │  │ POST /v1/embeddings│  │ POST /v1/chat/    │  │ POST /v1/rerank│  │    │
│  │  │                   │  │     completions   │  │                │  │    │
│  │  └───────────────────┘  └───────────────────┘  └───────────────┘  │    │
│  │  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────┐  │    │
│  │  │ GET /v1/models    │  │ GET /health       │  │ GET /metrics  │  │    │
│  │  └───────────────────┘  └───────────────────┘  └───────────────┘  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                           Services                                    │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │   │
│  │  │    Embeddings   │  │    Reranker     │  │    vLLM Proxy      │  │   │
│  │  │   (fastembed)   │  │  (Cross-Encoder)│  │  (HTTP Streaming)  │  │   │
│  │  │   ONNX-based    │  │   ONNX-based    │  │                    │  │   │
│  │  └─────────────────┘  └─────────────────┘  └────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Service Details

| Property | Value |
|----------|-------|
| **Service Name** | `llm-gateway` |
| **Container Name** | `rag-llm-gateway` |
| **Port** | 8004 |
| **Default Embedding Model** | `all-MiniLM-L6-v2` |
| **Default Reranker Model** | `BAAI/bge-reranker-v2-m3` |
| **Implementation** | `crates/rag-llm-gateway/` |

## API Reference

### Generate Embeddings

**Endpoint:** `POST /v1/embeddings`

Generate embeddings for input text(s). OpenAI-compatible API.

**Request:**

```json
{
    "input": "text to embed",
    "model": "all-MiniLM-L6-v2",
    "encoding_format": "float"
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

### Chat Completion

**Endpoint:** `POST /v1/chat/completions`

Proxy chat completion requests to vLLM backend. Supports streaming via Server-Sent Events (SSE).

**Request:**

```json
{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is machine learning?"}
    ],
    "temperature": 0.7,
    "max_tokens": 512,
    "stream": false
}
```

**Response (non-streaming):**

```json
{
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1706745600,
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Machine learning is..."
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 25,
        "completion_tokens": 150,
        "total_tokens": 175
    }
}
```

**Streaming Response:**

When `stream: true`, the response is Server-Sent Events:

```text
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":"Machine"},"index":0}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":" learning"},"index":0}]}

data: [DONE]
```

### Rerank Documents

**Endpoint:** `POST /v1/rerank` or `POST /v1/rerankings`

Rerank documents by relevance to a query using a cross-encoder model.

**Request:**

```json
{
    "query": "What is machine learning?",
    "documents": [
        "Machine learning is a subset of AI...",
        "The weather today is sunny...",
        "Deep learning uses neural networks..."
    ],
    "model": "BAAI/bge-reranker-v2-m3",
    "top_n": 2,
    "return_documents": true
}
```

**Response:**

```json
{
    "model": "BAAI/bge-reranker-v2-m3",
    "results": [
        {
            "index": 0,
            "relevance_score": 0.95,
            "document": "Machine learning is a subset of AI..."
        },
        {
            "index": 2,
            "relevance_score": 0.88,
            "document": "Deep learning uses neural networks..."
        }
    ],
    "usage": {
        "total_tokens": 45
    }
}
```

### List Models

**Endpoint:** `GET /v1/models`

Returns available models.

**Response:**

```json
{
    "object": "list",
    "data": [
        {
            "id": "all-MiniLM-L6-v2",
            "object": "model",
            "owned_by": "local",
            "type": "embedding"
        },
        {
            "id": "BAAI/bge-reranker-v2-m3",
            "object": "model",
            "owned_by": "local",
            "type": "reranker"
        },
        {
            "id": "Qwen/Qwen2.5-7B-Instruct",
            "object": "model",
            "owned_by": "vllm",
            "type": "chat"
        }
    ]
}
```

### Health Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Service info |
| `GET /health` | Full health status |
| `GET /health/live` | Kubernetes liveness probe |
| `GET /health/ready` | Kubernetes readiness probe |
| `GET /metrics` | Prometheus metrics |

## Configuration

### Environment Variables

#### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8004` | Server port |
| `REQUEST_TIMEOUT_SECS` | `60` | Request timeout |
| `RUST_LOG` | `info` | Log level filter |

#### Embedding Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_ENABLED` | `true` | Enable embedding service |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_MAX_BATCH_SIZE` | `32` | Max batch size |

#### Reranker Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RERANKER_ENABLED` | `true` | Enable reranker service |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Reranker model |
| `RERANKER_MAX_BATCH_SIZE` | `32` | Max batch size |
| `RERANKER_MAX_SEQ_LENGTH` | `512` | Max sequence length |
| `RERANKER_NORMALIZE_SCORES` | `false` | Normalize scores to 0-1 |

#### vLLM Proxy Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_ENABLED` | `true` | Enable vLLM proxy |
| `VLLM_URL` | `http://localhost:8000` | vLLM server URL |
| `VLLM_DEFAULT_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Default model |
| `VLLM_TIMEOUT_SECS` | `60` | Request timeout |

#### Authentication Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `false` | Enable authentication |
| `JWT_SECRET` | - | JWT secret (HS256) |
| `JWT_PUBLIC_KEY` | - | JWT public key (RS256) |
| `JWT_ALGORITHM` | `RS256` | JWT algorithm |
| `JWT_ISSUER` | - | Expected JWT issuer |
| `JWT_AUDIENCE` | - | Expected JWT audience |
| `JWKS_URL` | - | JWKS endpoint URL |
| `API_KEYS` | - | API keys (format: `KEY:tenant:user:roles`) |

#### Rate Limiting Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `RATE_LIMIT_RPM` | `60` | Requests per minute |
| `RATE_LIMIT_TPM` | `100000` | Tokens per minute |
| `RATE_LIMIT_BURST` | `1.5` | Burst multiplier |

## Project Structure

```text
crates/rag-llm-gateway/
├── Cargo.toml
├── src/
│   ├── bin/
│   │   └── main.rs              # Service entry point
│   ├── lib.rs                   # Library exports
│   ├── config.rs                # Configuration management
│   ├── error.rs                 # Error types
│   ├── api/
│   │   ├── mod.rs               # API module exports
│   │   ├── state.rs             # Application state
│   │   └── routes/
│   │       ├── mod.rs           # Route registration
│   │       ├── chat.rs          # Chat completion endpoint
│   │       ├── embeddings.rs    # Embeddings endpoint
│   │       ├── rerank.rs        # Rerank endpoint
│   │       ├── models.rs        # Models endpoint
│   │       └── health.rs        # Health endpoints
│   ├── auth/
│   │   ├── mod.rs               # Auth module exports
│   │   ├── jwt.rs               # JWT validation
│   │   ├── middleware.rs        # Auth middleware
│   │   └── context.rs           # Auth context
│   ├── rate_limit/
│   │   ├── mod.rs               # Rate limit exports
│   │   ├── bucket.rs            # Token bucket implementation
│   │   └── middleware.rs        # Rate limit middleware
│   ├── reranker/
│   │   ├── mod.rs               # Reranker exports
│   │   ├── model.rs             # ONNX model wrapper
│   │   └── types.rs             # Request/response types
│   ├── clients/
│   │   ├── mod.rs               # Client exports
│   │   ├── vllm.rs              # vLLM HTTP client
│   │   └── types.rs             # Client types
│   └── metrics/
│       └── mod.rs               # Prometheus metrics
```

## Authentication

### JWT Authentication

The gateway supports JWT tokens with RS256 or HS256 algorithms:

```bash
curl -X POST "http://localhost:8004/v1/embeddings" \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"input": "test"}'
```

### API Key Authentication

API keys can be configured via environment variable:

```bash
# Format: KEY:tenant_id:user_id:role1,role2
export API_KEYS="sk-abc123:tenant1:user1:admin,user;sk-def456:tenant2:user2:user"
```

Usage:

```bash
curl -X POST "http://localhost:8004/v1/embeddings" \
  -H "Authorization: Bearer sk-abc123" \
  -H "Content-Type: application/json" \
  -d '{"input": "test"}'
```

### Unauthenticated Endpoints

The following endpoints skip authentication:

- `/health`, `/health/live`, `/health/ready`
- `/metrics`
- `/`

## Rate Limiting

The gateway implements token bucket rate limiting per tenant:

- **RPM (Requests Per Minute):** Controls request frequency
- **TPM (Tokens Per Minute):** Controls token throughput
- **Burst:** Allows temporary bursts above the limit

Rate limit headers in response:

```text
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 55
X-RateLimit-Reset: 1706745660
```

## Prometheus Metrics

Available at `GET /metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_gateway_requests_total` | Counter | Total requests by service/endpoint/status |
| `rag_gateway_request_latency_seconds` | Histogram | Request latency distribution |
| `rag_gateway_active_requests` | Gauge | Currently active requests |
| `rag_gateway_tokens_total` | Counter | Tokens processed by type |
| `rag_gateway_embeddings_total` | Counter | Total embeddings generated |
| `rag_gateway_rate_limit_hits_total` | Counter | Rate limit hits by tenant |
| `rag_gateway_auth_failures_total` | Counter | Authentication failures |
| `rag_gateway_model_loaded` | Gauge | Model load status |

## Docker Compose Configuration

```yaml
llm-gateway:
  build:
    context: .
    dockerfile: crates/rag-llm-gateway/Dockerfile
  container_name: rag-llm-gateway
  ports:
    - "8004:8004"
  environment:
    - HOST=0.0.0.0
    - PORT=8004
    - EMBEDDING_ENABLED=true
    - EMBEDDING_MODEL=all-MiniLM-L6-v2
    - RERANKER_ENABLED=true
    - VLLM_URL=http://vllm:8000
    - AUTH_ENABLED=false
    - RATE_LIMIT_ENABLED=true
    - RUST_LOG=info
  volumes:
    - model_cache:/root/.cache/huggingface
  networks:
    - rag-network
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8004/health"]
    interval: 30s
    timeout: 10s
    retries: 3
  depends_on:
    - vllm
  profiles:
    - app
```

## Development

### Running Tests

```bash
# Run all tests
cd crates && cargo test -p rag-llm-gateway

# Run with verbose output
cd crates && cargo test -p rag-llm-gateway -- --nocapture
```

### Local Development

```bash
# Build the service
cd crates && cargo build -p rag-llm-gateway

# Run locally (requires vLLM for chat completions)
cd crates && cargo run -p rag-llm-gateway

# Run with specific config
EMBEDDING_MODEL=all-MiniLM-L6-v2 VLLM_URL=http://localhost:8000 \
  cargo run -p rag-llm-gateway
```

### Code Quality

```bash
# Lint with clippy
cd crates && cargo clippy -p rag-llm-gateway -- -D warnings

# Format code
cd crates && cargo fmt -p rag-llm-gateway
```

## Integration with Other Services

### Orchestrator Service

The Orchestrator uses the LLM Gateway for:

- Query embeddings (semantic search)
- Document reranking
- LLM inference for response generation

```python
# In services/orchestrator/config.py
llm_gateway_url: str = "http://llm-gateway:8004"
```

### Retrieval Service

The Retrieval Service can optionally use the LLM Gateway for reranking results:

```rust
// In crates/rag-retrieval/src/config.rs
pub reranker_url: String,  // "http://llm-gateway:8004/v1/rerank"
```

## Troubleshooting

### Common Issues

#### 1. vLLM Connection Failed

**Error:** `vLLM service not available`

**Cause:** vLLM server not running or unreachable.

**Solution:**

```bash
# Check vLLM is running
curl http://localhost:8000/health

# Verify VLLM_URL environment variable
echo $VLLM_URL
```

#### 2. Authentication Failed

**Error:** `401 Unauthorized`

**Causes:**

- Invalid or expired JWT token
- Missing Authorization header
- API key not configured

**Solution:**

```bash
# Check if auth is enabled
curl http://localhost:8004/health

# Test with valid token
curl -H "Authorization: Bearer <token>" http://localhost:8004/v1/models
```

#### 3. Rate Limited

**Error:** `429 Too Many Requests`

**Solution:**

- Wait for rate limit window to reset
- Reduce request frequency
- Request higher limits for your tenant

### Logs

View service logs:

```bash
docker logs rag-llm-gateway -f
```

Example startup logs:

```text
2026-01-30T10:00:00.000Z  INFO llm_gateway: Starting LLM Gateway v1.0.0
2026-01-30T10:00:00.001Z  INFO llm_gateway: Configuration loaded
2026-01-30T10:00:00.002Z  INFO llm_gateway: Loading embedding model: all-MiniLM-L6-v2...
2026-01-30T10:00:01.500Z  INFO llm_gateway: Embedding model loaded: sentence-transformers/all-MiniLM-L6-v2
2026-01-30T10:00:01.501Z  INFO llm_gateway: vLLM proxy enabled, URL: http://vllm:8000
2026-01-30T10:00:01.502Z  INFO llm_gateway: Listening on http://0.0.0.0:8004
```

## Related Documentation

- [Architecture Overview](../architecture.md)
- [Embedding Service](../embedding-service/README.md)
- [Retrieval Service](../retrieval-service/README.md)
- [Orchestrator Service](../orchestrator/README.md)
