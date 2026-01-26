# Retrieval Service Documentation

The Retrieval Service is the core search component of the RAG pipeline, responsible for finding relevant document chunks using hybrid search (semantic + keyword), fusion algorithms, cross-encoder reranking, and ACL-based access control.

**Implementation:** Rust (Axum HTTP server)

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Hybrid Search Pipeline](#hybrid-search-pipeline)
  - [Query Preprocessing](#query-preprocessing)
  - [Semantic Search](#semantic-search)
  - [Keyword Search](#keyword-search)
  - [Hybrid Fusion](#hybrid-fusion)
  - [Reranking](#reranking)
  - [ACL Filtering](#acl-filtering)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Caching Strategy](#caching-strategy)
- [Observability](#observability)
- [Performance Targets](#performance-targets)
- [Testing](#testing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            Retrieval Service                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                        Query Preprocessing Pipeline                         │ │
│  │                                                                             │ │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │ │
│  │  │Normalize  │─▶│ Classify  │─▶│  Expand   │─▶│   HyDE    │─▶│  Embed   │ │ │
│  │  │ Query     │  │   Type    │  │  (LLM)    │  │(Optional) │  │  Query   │ │ │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘  └──────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                        │                                         │
│                                        ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                        Parallel Search Execution                            │ │
│  │                                                                             │ │
│  │  ┌─────────────────────────────┐    ┌─────────────────────────────┐        │ │
│  │  │      Semantic Search        │    │       Keyword Search         │        │ │
│  │  │         (Qdrant)            │    │       (OpenSearch)           │        │ │
│  │  │                             │    │                              │        │ │
│  │  │  • Vector similarity        │    │  • BM25 ranking              │        │ │
│  │  │  • HNSW index              │    │  • Multi-field search        │        │ │
│  │  │  • Cosine distance         │    │  • Fuzzy matching            │        │ │
│  │  │  • Top-K retrieval         │    │  • Highlighting              │        │ │
│  │  └──────────────┬──────────────┘    └──────────────┬───────────────┘        │ │
│  │                 │                                   │                        │ │
│  │                 └──────────────┬────────────────────┘                        │ │
│  │                                ▼                                             │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐    │ │
│  │  │                      Hybrid Fusion (RRF)                             │    │ │
│  │  │  • Reciprocal Rank Fusion (k=60)                                     │    │ │
│  │  │  • Linear weighted combination (semantic: 0.7, keyword: 0.3)         │    │ │
│  │  │  • Deduplication by document_id                                      │    │ │
│  │  └──────────────────────────────┬──────────────────────────────────────┘    │ │
│  │                                 ▼                                            │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐    │ │
│  │  │                    Cross-Encoder Reranking                           │    │ │
│  │  │  • Model: BAAI/bge-reranker-v2-m3                                    │    │ │
│  │  │  • Batch processing (max 32 docs)                                    │    │ │
│  │  │  • Top-K selection (default: 20 → 10)                                │    │ │
│  │  └──────────────────────────────┬──────────────────────────────────────┘    │ │
│  │                                 ▼                                            │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐    │ │
│  │  │                        ACL Filtering                                 │    │ │
│  │  │  • Tenant isolation (always enforced)                                │    │ │
│  │  │  • Visibility levels (PUBLIC, PRIVATE, GROUP, TENANT)                │    │ │
│  │  │  • User/group-based access control                                   │    │ │
│  │  └──────────────────────────────┬──────────────────────────────────────┘    │ │
│  └─────────────────────────────────┼────────────────────────────────────────────┘ │
│                                    ▼                                             │
│                            Final Results                                         │
│                                                                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐ │
│  │    Metrics    │  │   Logging     │  │    Cache      │  │     Tracing       │ │
│  │  (Prometheus) │  │   (tracing)   │  │   (Redis)     │  │ (OpenTelemetry)   │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
crates/rag-retrieval/
├── src/
│   ├── lib.rs              # Library root with module exports
│   ├── bin/
│   │   └── main.rs         # Axum HTTP server entry point
│   ├── api/
│   │   ├── mod.rs          # API module
│   │   ├── routes.rs       # Route definitions
│   │   ├── handlers.rs     # Request handlers
│   │   ├── state.rs        # Application state (AppState)
│   │   └── types.rs        # Request/response types
│   ├── acl/
│   │   ├── mod.rs          # ACL module
│   │   ├── config.rs       # ACLFilterConfig
│   │   ├── filter.rs       # ACLFilter implementation
│   │   ├── builders.rs     # Qdrant/OpenSearch filter builders
│   │   └── user_context.rs # UserContext from JWT
│   ├── search/
│   │   ├── mod.rs          # Search module
│   │   ├── semantic.rs     # SemanticSearcher (Qdrant)
│   │   └── keyword.rs      # KeywordSearcher (OpenSearch)
│   ├── hybrid/
│   │   ├── mod.rs          # Hybrid search module
│   │   ├── searcher.rs     # HybridSearcher orchestrator
│   │   ├── config.rs       # HybridSearchConfig
│   │   └── fusion.rs       # RRF, Linear, DBSF algorithms
│   ├── embedding/
│   │   ├── mod.rs          # Embedding module
│   │   └── client.rs       # EmbeddingClient
│   ├── reranking/
│   │   ├── mod.rs          # Reranking module
│   │   ├── client.rs       # RerankerClient
│   │   └── service.rs      # RerankerService
│   ├── types/
│   │   ├── mod.rs          # Core types
│   │   ├── search.rs       # SearchResult, SearchOptions
│   │   └── visibility.rs   # Visibility enum
│   └── error.rs            # RetrievalError
├── tests/
│   ├── integration/        # Integration tests
│   └── property/           # Property-based tests
├── Cargo.toml              # Dependencies
└── Dockerfile              # Multi-stage build
```

---

## Hybrid Search Pipeline

### Query Preprocessing

The query preprocessing pipeline normalizes, classifies, and enriches user queries before search.

```rust
use rag_retrieval::query::{QueryPreprocessor, ProcessedQuery};

let preprocessor = QueryPreprocessor::new(
    embedding_client,
    llm_gateway,
    query_cache,
);

// Process a query
let processed: ProcessedQuery = preprocessor.process(
    "How do I reset my password?",
    "tenant-123",
    QueryOptions {
        enable_hyde: false,
        enable_expansion: true,
        ..Default::default()
    },
).await?;

println!("{}", processed.normalized_query);  // "how do i reset my password"
println!("{:?}", processed.query_type);      // QueryType::Question
println!("{:?}", processed.embedding);       // [0.123, 0.456, ...] (384 dims)
```

#### Query Classification

| Query Type | Description | Example |
|------------|-------------|---------|
| `Simple` | Short factual queries | "Python version" |
| `Question` | Natural language questions | "What is Python?" |
| `Semantic` | Concept/meaning focused | "machine learning applications" |
| `Hybrid` | Mixed intent | "Python vs Java for web development" |

---

### Semantic Search

Vector similarity search using Qdrant with HNSW indexing.

```rust
use rag_retrieval::search::{SemanticSearcher, SemanticSearchConfig};

let searcher = SemanticSearcher::new(&SemanticSearchConfig {
    url: "http://localhost:6333".to_string(),
    collection: "documents".to_string(),
    top_k: 50,
    score_threshold: 0.0,
}).await?;

// Search by embedding
let results = searcher.search(
    &embedding,  // 384 dimensions
    "tenant-123",
    Some(filters),
    50,
).await?;

for result in results {
    println!("{}: {:.3}", result.chunk_id, result.score);
}
```

**Score Normalization:**
- Cosine similarity scores are normalized from [-1, 1] to [0, 1]
- Formula: `normalized = (score + 1) / 2`

**Qdrant Configuration:**
- Collection: `documents`
- Vector dimensions: 384 (all-MiniLM-L6-v2)
- Distance metric: Cosine
- HNSW parameters: `m=16`, `ef_construct=100`

---

### Keyword Search

BM25-based keyword search using OpenSearch with multi-field matching.

```rust
use rag_retrieval::search::{KeywordSearcher, KeywordSearchConfig};

let searcher = KeywordSearcher::new(&KeywordSearchConfig {
    url: "http://localhost:9200".to_string(),
    index: "documents".to_string(),
    top_k: 50,
    fields: vec!["content".to_string(), "title".to_string()],
    field_boosts: [("title".to_string(), 2.0)].into(),
})?;

// Search by keywords
let results = searcher.search(
    "password reset SSO",
    "tenant-123",
    Some(filters),
    50,
).await?;

for result in results {
    println!("{}: {:.3}", result.chunk_id, result.score);
    if let Some(highlights) = &result.highlights {
        println!("  Highlights: {:?}", highlights);
    }
}
```

---

### Hybrid Fusion

Combines semantic and keyword search results using configurable fusion algorithms.

```rust
use rag_retrieval::hybrid::{HybridSearcher, HybridSearchConfig, FusionMethod};

let config = HybridSearchConfig {
    fusion_method: FusionMethod::RRF,
    rrf_k: 60,
    semantic_weight: 0.7,
    keyword_weight: 0.3,
    deduplicate: true,
};

let hybrid = HybridSearcher::new(
    Arc::new(semantic_searcher),
    Arc::new(keyword_searcher),
    config,
);

// Execute hybrid search
let results = hybrid.search(
    &embedding,
    "password reset SSO",
    user_context,
    SearchOptions::default(),
).await?;
```

#### Fusion Algorithms

| Algorithm | Description | Best For |
|-----------|-------------|----------|
| **RRF** (Reciprocal Rank Fusion) | `score = sum(weight / (k + rank))` | Default, robust |
| **Linear** | `score = w1 * semantic + w2 * keyword` | When scores are comparable |
| **DBSF** (Distribution-Based Score Fusion) | Z-score normalization | Diverse score distributions |

#### RRF Formula

```rust
fn rrf_score(
    semantic_rank: Option<usize>,
    keyword_rank: Option<usize>,
    k: usize,      // default: 60
    w_s: f32,      // semantic weight (default: 0.7)
    w_k: f32,      // keyword weight (default: 0.3)
) -> f32 {
    let mut score = 0.0;
    if let Some(rank) = semantic_rank {
        score += w_s / (k + rank) as f32;
    }
    if let Some(rank) = keyword_rank {
        score += w_k / (k + rank) as f32;
    }
    score
}
```

---

### Reranking

Cross-encoder reranking using the LLM Gateway's reranker endpoint.

```rust
use rag_retrieval::reranking::{RerankerService, RerankerConfig};

let reranker = RerankerService::new(RerankerConfig {
    gateway_url: "http://localhost:8004".to_string(),
    model: "BAAI/bge-reranker-v2-m3".to_string(),
    max_documents: 20,
    batch_size: 32,
    timeout_secs: 30,
})?;

// Rerank fused results
let reranked = reranker.rerank(
    "How do I reset my SSO password?",
    &documents,
    10,  // top_k
).await?;
```

**Reranking Flow:**
1. Take top N results from fusion (default: 20)
2. Truncate documents to max_length tokens (512)
3. Batch documents (max 32 per batch)
4. Call LLM Gateway `/v1/rerank` endpoint
5. Sort by reranker scores
6. Return top K results (default: 10)

---

### ACL Filtering

Access Control Layer filters results based on user permissions, applied after reranking to preserve quality.

```rust
use rag_retrieval::acl::{ACLFilter, ACLFilterConfig, UserContext};
use rag_retrieval::types::Visibility;

let acl_filter = ACLFilter::new(ACLFilterConfig::default());

// Create user context from JWT
let user_context = UserContext {
    user_id: Uuid::new_v4(),
    tenant_id: Uuid::parse_str("tenant-456")?,
    groups: vec!["engineering".to_string(), "product".to_string()],
    roles: vec!["user".to_string()],
    is_admin: false,
};

// Filter results
let filtered = acl_filter.filter(&results, &user_context);
```

#### Visibility Levels

| Level | Access Rule |
|-------|-------------|
| `Public` | Accessible to all users in tenant |
| `Private` | Only accessible to document owner |
| `Group` | Accessible to users in `allowed_groups` |
| `Tenant` | Accessible to all users in the same tenant |

---

## API Reference

### Main Retrieval Endpoint

```
POST /api/v1/retrieve
```

**Request:**

```json
{
  "query": "How do I reset my SSO password?",
  "mode": "hybrid",
  "top_k": 10,
  "semantic_weight": 0.7,
  "keyword_weight": 0.3,
  "rerank": true,
  "rerank_top_k": 20,
  "filters": {
    "source_type": "kb_article",
    "language": "en"
  },
  "min_score": 0.0,
  "include_metadata": true,
  "include_highlights": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Search query (1-2000 chars) |
| `mode` | enum | `hybrid` | `hybrid`, `semantic`, or `keyword` |
| `top_k` | int | 10 | Final results to return (1-100) |
| `semantic_weight` | float | 0.7 | Weight for semantic search (0.0-1.0) |
| `keyword_weight` | float | 0.3 | Weight for keyword search (0.0-1.0) |
| `rerank` | bool | true | Enable cross-encoder reranking |
| `rerank_top_k` | int | 20 | Candidates for reranking (1-100) |
| `filters` | dict | null | Metadata filters |
| `min_score` | float | 0.0 | Minimum score threshold (0.0-1.0) |
| `include_metadata` | bool | true | Include document metadata |
| `include_highlights` | bool | true | Include keyword highlights |

**Response:**

```json
{
  "results": [
    {
      "chunk_id": "uuid-1",
      "document_id": "doc-uuid-1",
      "content": "To reset your SSO password, navigate to...",
      "score": 0.87,
      "title": "SSO Password Reset Guide",
      "source": "https://kb.example.com/sso-reset",
      "chunk_index": 2,
      "total_chunks": 5,
      "semantic_score": 0.82,
      "keyword_score": 0.91,
      "rerank_score": 0.95,
      "metadata": {
        "author": "IT Department",
        "last_updated": "2024-01-15"
      },
      "highlights": [
        "To <em>reset</em> your <em>SSO</em> <em>password</em>..."
      ]
    }
  ],
  "total_results": 1,
  "query": "How do I reset my SSO password?",
  "mode": "hybrid",
  "metrics": {
    "query_preprocessing_ms": 45,
    "semantic_search_ms": 32,
    "keyword_search_ms": 28,
    "fusion_ms": 3,
    "rerank_ms": 85,
    "total_ms": 198
  },
  "query_id": "query-uuid"
}
```

### Multi-Query Search

```
POST /api/v1/retrieve/multi
```

Execute multiple queries in parallel with result aggregation.

**Request:**

```json
{
  "queries": [
    {"query": "password reset", "weight": 1.0},
    {"query": "SSO configuration", "weight": 0.5}
  ],
  "aggregation": "union",
  "top_k": 10
}
```

### Health Endpoints

```
GET /health        # Full health with component status
GET /health/live   # Kubernetes liveness probe
GET /health/ready  # Kubernetes readiness probe
```

**Full Health Response:**

```json
{
  "status": "healthy",
  "service": "retrieval-service",
  "version": "0.1.0",
  "components": {
    "qdrant": {"status": "healthy", "latency_ms": 5},
    "opensearch": {"status": "healthy", "latency_ms": 8},
    "redis": {"status": "healthy", "latency_ms": 2}
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

## Configuration

### Environment Variables

```bash
# Server
RETRIEVAL_HOST=0.0.0.0
RETRIEVAL_PORT=8002
RUST_LOG=info,rag_retrieval=debug

# Qdrant (Vector Store)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=documents

# OpenSearch (Keyword Search)
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=documents

# Embedding Service
EMBEDDING_SERVICE_URL=http://localhost:8080
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384

# Search Weights
HYBRID_SEMANTIC_WEIGHT=0.7
HYBRID_KEYWORD_WEIGHT=0.3
HYBRID_FUSION_METHOD=rrf

# Reranking
RERANKER_ENABLED=true
RERANKER_GATEWAY_URL=http://localhost:8004
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# ACL
ACL_ENABLED=true
ACL_ADMIN_BYPASS=true
ACL_DEFAULT_VISIBILITY=private
```

---

## Observability

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `retrieval_requests_total` | Counter | mode, status | Total requests |
| `retrieval_duration_seconds` | Histogram | mode, component | Request latency |
| `retrieval_search_duration_seconds` | Histogram | type | Search time (semantic/keyword) |
| `retrieval_rerank_duration_seconds` | Histogram | | Reranking time |

**Metrics Endpoint:**

```
GET /metrics
```

### Structured Logging

JSON-formatted logs with tracing for log aggregation.

```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO",
  "target": "rag_retrieval::api::handlers",
  "message": "retrieval_complete",
  "query_id": "query-uuid",
  "tenant_id": "tenant-456",
  "mode": "hybrid",
  "results_count": 10,
  "total_ms": 198
}
```

---

## Performance Targets

| Operation | Target (p95) | Max (p99) |
|-----------|--------------|-----------|
| Query preprocessing | 150ms | 200ms |
| Semantic search | 50ms | 100ms |
| Keyword search | 50ms | 100ms |
| Hybrid fusion | 5ms | 10ms |
| Reranking (20 docs) | 100ms | 150ms |
| ACL filtering | 5ms | 10ms |
| **Total** | **200ms** | **300ms** |

### Throughput Target

- 100+ queries per second (QPS) sustained
- Horizontal scaling via Kubernetes replicas

---

## Testing

### Run Tests

```bash
cd crates

# Run all tests
cargo test -p rag-retrieval

# Run with verbose output
cargo test -p rag-retrieval -- --nocapture

# Run specific test module
cargo test -p rag-retrieval --test integration

# Run with all features
cargo test -p rag-retrieval --all-features
```

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| api | 20+ | 95%+ |
| search | 30+ | 98% |
| hybrid | 25+ | 97% |
| acl | 20+ | 98% |
| reranking | 15+ | 96% |
| types | 20+ | 95% |
| **Total** | **130+** | **>90%** |

---

## Related Documentation

- [Architecture Overview](../architecture.md)
- [Health Check Specification](../health-check-specification.md)
- [Resilience & Degradation](../resilience-degradation.md)
- [Orchestrator Service](../orchestrator-service/README.md)
