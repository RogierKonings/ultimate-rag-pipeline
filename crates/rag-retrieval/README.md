# rag-retrieval

A high-performance Rust retrieval service for RAG (Retrieval-Augmented Generation) pipelines.

## Features

- **Hybrid Search**: Combines semantic (vector) and keyword (BM25) search with configurable fusion
- **Fusion Algorithms**: RRF (Reciprocal Rank Fusion), Linear, and Distribution-Based Score Fusion (DBSF)
- **Cross-Encoder Reranking**: Improves result quality via neural reranking
- **ACL Enforcement**: Multi-tenant access control with visibility levels
- **Query Enhancement**: Preprocessing, expansion, and HyDE (Hypothetical Document Embeddings) support
- **Caching**: Redis-backed caching for embeddings and query results
- **Observability**: OpenTelemetry tracing, Prometheus metrics, structured logging

## Quick Start

### Fusion Algorithms

```rust
use rag_retrieval::fusion::{fuse, FusionConfig, FusionMethod};
use rag_retrieval::ScoredItem;

// Create search results from different sources
let semantic_results = vec![
    ScoredItem::new("doc1", 0.9),
    ScoredItem::new("doc2", 0.8),
    ScoredItem::new("doc3", 0.7),
];

let keyword_results = vec![
    ScoredItem::new("doc2", 0.95),
    ScoredItem::new("doc4", 0.85),
    ScoredItem::new("doc1", 0.75),
];

// RRF fusion (default) - rank-based, ignores absolute scores
let config = FusionConfig::default();
let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();

// Linear fusion - weighted score combination
let config = FusionConfig::new(FusionMethod::Linear)
    .with_weights(0.7, 0.3);  // 70% semantic, 30% keyword
let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();

// DBSF fusion - distribution-aware with z-score normalization
let config = FusionConfig::new(FusionMethod::Dbsf);
let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
```

### Hybrid Search Configuration

```rust
use rag_retrieval::hybrid::HybridSearchConfig;
use rag_retrieval::fusion::FusionMethod;

let config = HybridSearchConfig::default()
    .with_top_k(10)                    // Final results to return
    .with_semantic_top_k(50)           // Candidates from vector search
    .with_keyword_top_k(50)            // Candidates from keyword search
    .with_fusion_method(FusionMethod::Rrf)
    .with_weights(0.7, 0.3)            // Semantic vs keyword weight
    .with_min_score(0.3)               // Minimum score threshold
    .with_deduplicate(true);           // Remove duplicate chunks
```

### Access Control

```rust
use rag_retrieval::types::{UserContext, Visibility};
use uuid::Uuid;

let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
    .with_groups(vec!["engineering".into(), "backend".into()])
    .with_roles(vec!["developer".into()])
    .with_admin(false);

// Check access to a group-restricted document
let can_access = user.can_access(
    Visibility::Group,
    &["engineering".into(), "sales".into()]
);
assert!(can_access);  // User is in "engineering" group
```

## Building

```bash
# Build the crate
cargo build -p rag-retrieval

# Run tests
cargo test -p rag-retrieval

# Run with all features
cargo build -p rag-retrieval --all-features

# Run benchmarks
cargo bench -p rag-retrieval
```

## Optional Features

- `openapi` - Enable OpenAPI/utoipa schema generation for API documentation
- `memory-profiling` - Enable memory profiling with dhat for allocation analysis

```bash
# Build with OpenAPI support
cargo build -p rag-retrieval --features openapi

# Run memory profiling benchmark
cargo bench --bench memory_benchmark --features memory-profiling
```

## Performance Targets

| Operation | Target (p95) | Timeout |
|-----------|-------------|---------|
| Query embedding | 20ms | 5000ms |
| Semantic search | 50ms | 3000ms |
| Keyword search | 30ms | 3000ms |
| RRF Fusion | 5ms | N/A |
| Reranking | 150ms | 8000ms |
| Total E2E | 300ms | 15000ms |

## Architecture

```
                    SearchPipeline
+-------------------------------------------------------------+
|  Query -> Preprocess -> Expand -> Embed -> Cache Check      |
|                                              |               |
|              +-------------+-------------+   |               |
|              |   Qdrant    |  OpenSearch |   | (parallel)    |
|              +-------------+-------------+   |               |
|                          |                   v               |
|                    Fusion (RRF/Linear/DBSF)                  |
|                          |                                   |
|                    ACL Filter                                |
|                          |                                   |
|                    Rerank (optional)                         |
|                          |                                   |
|                    Cache Store -> Response                   |
+-------------------------------------------------------------+
```

## Module Overview

- `fusion` - Fusion algorithms (RRF, Linear, DBSF) for combining search results
- `hybrid` - Hybrid search orchestration and pipeline configuration
- `search` - Semantic and keyword search client implementations
- `query` - Query preprocessing, expansion, and HyDE generation
- `reranking` - Cross-encoder reranking service integration
- `acl` - Access control list filtering and visibility enforcement
- `cache` - Query result caching with Redis
- `embedding` - Embedding service client for query vectorization
- `api` - HTTP API types, routes, and server configuration
- `observability` - Metrics, tracing, and structured logging

## Testing

```bash
# Run all tests
cargo test -p rag-retrieval

# Run property-based tests
cargo test -p rag-retrieval --test property_tests

# Run with OpenAPI feature tests
cargo test -p rag-retrieval --features openapi

# Run specific test
cargo test -p rag-retrieval test_rrf_output_sorted
```

## API Endpoints

The service exposes the following HTTP endpoints:

- `POST /api/v1/retrieve` - Execute hybrid search query
- `POST /api/v1/multi-retrieve` - Execute multi-query search
- `GET /health` - Full health check with component status
- `GET /health/live` - Kubernetes liveness probe
- `GET /health/ready` - Kubernetes readiness probe
- `GET /metrics` - Prometheus metrics

## License

MIT
