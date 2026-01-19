# Retrieval Service Documentation

The Retrieval Service is the core search component of the RAG pipeline, responsible for finding relevant document chunks using hybrid search (semantic + keyword), fusion algorithms, cross-encoder reranking, and ACL-based access control.

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
│  │  (Prometheus) │  │  (structlog)  │  │   (Redis)     │  │ (OpenTelemetry)   │ │
│  └───────────────┘  └───────────────┘  └───────────────┘  └───────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
services/retrieval/
├── api/
│   ├── main.py              # FastAPI app with lifespan management
│   ├── routes/
│   │   ├── retrieve.py      # POST /retrieve, multi-query endpoints
│   │   └── health.py        # Health checks for Kubernetes
│   ├── schemas/
│   │   ├── retrieve.py      # Request/response Pydantic models
│   │   └── common.py        # Shared models
│   └── dependencies.py      # Dependency injection setup
├── acl/                     # Access Control Layer
│   ├── models.py            # UserContext, DocumentACL, Visibility enums
│   ├── filter.py            # ACLFilter for Qdrant/OpenSearch
│   ├── context.py           # UserContextExtractor for JWT parsing
│   └── middleware.py        # FastAPI dependencies
├── search/                  # Hybrid search implementation
│   ├── base.py              # BaseSearcher abstract interface
│   ├── semantic.py          # SemanticSearcher (Qdrant)
│   ├── keyword.py           # KeywordSearcher (OpenSearch)
│   ├── fusion.py            # RRF, Linear, DBSF fusion algorithms
│   ├── hybrid.py            # HybridSearcher orchestrator
│   ├── models.py            # SearchResultItem, FusedResult, configs
│   └── exceptions.py        # Custom exceptions
├── query/                   # Query Preprocessing Pipeline
│   ├── preprocessor.py      # QueryPreprocessor main pipeline
│   ├── expander.py          # QueryExpander (synonyms + LLM)
│   ├── hyde.py              # HyDEGenerator, MultiQueryGenerator
│   ├── cache.py             # QueryCache (Redis-backed)
│   └── models.py            # ProcessedQuery, QueryType configs
├── reranking/               # Cross-encoder Reranking
│   ├── reranker.py          # RerankerService calling LLM Gateway
│   ├── models.py            # RerankRequest, RerankResult, configs
│   └── exceptions.py        # Reranking exceptions
├── cache/                   # Result Caching
│   └── retrieval_cache.py   # RetrievalCache (Redis)
├── observability/           # Metrics & Logging
│   ├── retrieval_logger.py  # Structured JSON logging with structlog
│   ├── metrics.py           # Prometheus metrics
│   ├── tracing.py           # OpenTelemetry setup for Jaeger
│   └── middleware.py        # LoggingMiddleware
├── config.py                # RetrievalConfig with pydantic-settings
├── run.py                   # Uvicorn entry point
├── Dockerfile               # Docker image
└── tests/                   # Comprehensive test suite
```

---

## Hybrid Search Pipeline

### Query Preprocessing

The query preprocessing pipeline normalizes, classifies, and enriches user queries before search.

```python
from query.preprocessor import QueryPreprocessor
from query.models import ProcessedQuery

preprocessor = QueryPreprocessor(
    embedding_service=embedding_client,
    llm_gateway=llm_client,
    cache=query_cache
)

# Process a query
processed: ProcessedQuery = await preprocessor.process(
    query="How do I reset my password?",
    tenant_id="tenant-123",
    options={"enable_hyde": False, "enable_expansion": True}
)

print(processed.normalized_query)  # "how do i reset my password"
print(processed.query_type)        # QueryType.QUESTION
print(processed.embedding)         # [0.123, 0.456, ...] (1024 dims)
print(processed.expanded_terms)    # ["password reset", "account recovery"]
```

#### Query Classification

| Query Type | Description | Example |
|------------|-------------|---------|
| `SIMPLE` | Short factual queries | "Python version" |
| `QUESTION` | Natural language questions | "What is Python?" |
| `SEMANTIC` | Concept/meaning focused | "machine learning applications" |
| `HYBRID` | Mixed intent | "Python vs Java for web development" |

#### HyDE (Hypothetical Document Embeddings)

For difficult queries, HyDE generates a hypothetical answer and uses its embedding for search:

```python
from query.hyde import HyDEGenerator

hyde = HyDEGenerator(llm_gateway=llm_client)

# Generate hypothetical document
hypothetical_doc = await hyde.generate(
    query="What are the benefits of microservices?",
    num_hypotheticals=1
)
# "Microservices architecture offers several benefits including..."

# The embedding of this hypothetical is often closer to relevant documents
```

#### Query Expansion

```python
from query.expander import QueryExpander

expander = QueryExpander(llm_gateway=llm_client)

# Expand query with synonyms and related terms
expanded = await expander.expand(
    query="ML model training",
    max_expansions=3
)
# ["machine learning model training", "neural network training", "model fitting"]
```

---

### Semantic Search

Vector similarity search using Qdrant with HNSW indexing.

```python
from search.semantic import SemanticSearcher
from search.models import SemanticSearchConfig

searcher = SemanticSearcher(
    qdrant_client=qdrant,
    collection_name="documents",
    config=SemanticSearchConfig(
        top_k=50,
        score_threshold=0.0,
        ef_search=128  # HNSW parameter
    )
)

# Search by embedding
results = await searcher.search(
    embedding=[0.123, 0.456, ...],  # 1024 dimensions
    tenant_id="tenant-123",
    filters={"source_type": "kb_article"},
    top_k=50
)

for result in results:
    print(f"{result.chunk_id}: {result.score:.3f}")
    # chunk-uuid-1: 0.892
    # chunk-uuid-2: 0.847
```

**Score Normalization:**
- Cosine similarity scores are normalized from [-1, 1] to [0, 1]
- Formula: `normalized = (score + 1) / 2`

**Qdrant Configuration:**
- Collection: `documents`
- Vector dimensions: 1024 (BGE-large)
- Distance metric: Cosine
- HNSW parameters: `m=16`, `ef_construct=100`

---

### Keyword Search

BM25-based keyword search using OpenSearch with multi-field matching.

```python
from search.keyword import KeywordSearcher
from search.models import KeywordSearchConfig

searcher = KeywordSearcher(
    opensearch_client=opensearch,
    index_name="documents",
    config=KeywordSearchConfig(
        top_k=50,
        fields=["content", "title"],
        field_boosts={"title": 2.0, "content": 1.0},
        fuzziness="AUTO",
        highlight=True,
        highlight_fragment_size=150
    )
)

# Search by keywords
results = await searcher.search(
    query="password reset SSO",
    tenant_id="tenant-123",
    filters={"language": "en"},
    top_k=50
)

for result in results:
    print(f"{result.chunk_id}: {result.score:.3f}")
    print(f"  Highlights: {result.highlights}")
    # chunk-uuid-1: 0.756
    #   Highlights: ["To <em>reset</em> your <em>SSO</em> <em>password</em>..."]
```

**OpenSearch Query Structure:**
```json
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "password reset SSO",
            "fields": ["content", "title^2.0"],
            "type": "best_fields",
            "fuzziness": "AUTO"
          }
        }
      ],
      "filter": [
        {"term": {"tenant_id": "tenant-123"}},
        {"term": {"language": "en"}}
      ]
    }
  },
  "highlight": {
    "fields": {"content": {"fragment_size": 150}}
  }
}
```

---

### Hybrid Fusion

Combines semantic and keyword search results using configurable fusion algorithms.

```python
from search.fusion import HybridFusion, FusionAlgorithm
from search.models import FusionConfig

fusion = HybridFusion(
    config=FusionConfig(
        algorithm=FusionAlgorithm.RRF,
        rrf_k=60,
        semantic_weight=0.7,
        keyword_weight=0.3,
        deduplicate=True
    )
)

# Fuse results from both search methods
fused_results = fusion.fuse(
    semantic_results=semantic_results,
    keyword_results=keyword_results,
    top_k=50
)

for result in fused_results:
    print(f"{result.chunk_id}: {result.fused_score:.3f}")
    print(f"  Semantic: {result.semantic_score:.3f} (rank {result.semantic_rank})")
    print(f"  Keyword: {result.keyword_score:.3f} (rank {result.keyword_rank})")
```

#### Fusion Algorithms

| Algorithm | Description | Best For |
|-----------|-------------|----------|
| **RRF** (Reciprocal Rank Fusion) | `score = sum(weight / (k + rank))` | Default, robust |
| **Linear** | `score = w1 * semantic + w2 * keyword` | When scores are comparable |
| **Convex** | Linear with weights summing to 1.0 | Normalized output |
| **DBSF** (Distribution-Based Score Fusion) | Z-score normalization | Diverse score distributions |

#### RRF Formula

```python
def rrf_score(semantic_rank, keyword_rank, k=60, w_s=0.7, w_k=0.3):
    """
    Reciprocal Rank Fusion score calculation.

    Args:
        semantic_rank: 1-based rank in semantic results (None if not present)
        keyword_rank: 1-based rank in keyword results (None if not present)
        k: RRF constant (default: 60)
        w_s: Semantic weight (default: 0.7)
        w_k: Keyword weight (default: 0.3)

    Returns:
        Combined RRF score
    """
    score = 0.0
    if semantic_rank is not None:
        score += w_s / (k + semantic_rank)
    if keyword_rank is not None:
        score += w_k / (k + keyword_rank)
    return score
```

---

### Reranking

Cross-encoder reranking using the LLM Gateway's reranker endpoint.

```python
from reranking.reranker import RerankerService
from reranking.models import RerankConfig

reranker = RerankerService(
    llm_gateway_url="http://localhost:8004",
    config=RerankConfig(
        model="BAAI/bge-reranker-v2-m3",
        max_documents=20,
        batch_size=32,
        max_length=512,
        timeout=30.0,
        retries=3
    )
)

# Rerank fused results
reranked = await reranker.rerank(
    query="How do I reset my SSO password?",
    documents=[
        {"id": "chunk-1", "content": "To reset your SSO password..."},
        {"id": "chunk-2", "content": "SSO configuration guide..."},
        # ... more documents
    ],
    top_k=10
)

for result in reranked:
    print(f"{result.id}: {result.rerank_score:.3f}")
    # chunk-1: 0.952
    # chunk-2: 0.234
```

**Reranking Flow:**
1. Take top N results from fusion (default: 20)
2. Truncate documents to max_length tokens (512)
3. Batch documents (max 32 per batch)
4. Call LLM Gateway `/v1/rerank` endpoint
5. Sort by reranker scores
6. Return top K results (default: 10)

**Retry Logic:**
- 3 retry attempts with exponential backoff (1s, 2s, 4s)
- Timeout per request: 30 seconds
- Fallback: Return fusion scores if reranker fails

---

### ACL Filtering

Access Control Layer filters results based on user permissions, applied after reranking to preserve quality.

```python
from acl.filter import ACLFilter
from acl.models import UserContext, Visibility

acl_filter = ACLFilter()

# Create user context from JWT
user_context = UserContext(
    user_id="user-123",
    tenant_id="tenant-456",
    groups=["engineering", "product"],
    roles=["user"],
    is_admin=False
)

# Filter results
filtered_results = acl_filter.filter(
    results=reranked_results,
    user_context=user_context
)
```

#### Visibility Levels

| Level | Access Rule |
|-------|-------------|
| `PUBLIC` | Accessible to all users in tenant |
| `PRIVATE` | Only accessible to document owner |
| `GROUP` | Accessible to users in `allowed_groups` |
| `TENANT` | Accessible to all users in the same tenant |

#### Filter Logic

```python
def is_accessible(document, user_context):
    # 1. Tenant isolation (always enforced)
    if document.tenant_id != user_context.tenant_id:
        return False

    # 2. Admin bypass (if configured)
    if user_context.is_admin:
        return True

    # 3. Visibility-based access
    if document.visibility == Visibility.PUBLIC:
        return True
    elif document.visibility == Visibility.PRIVATE:
        return document.owner_id == user_context.user_id
    elif document.visibility == Visibility.GROUP:
        return bool(set(document.allowed_groups) & set(user_context.groups))
    elif document.visibility == Visibility.TENANT:
        return True  # Already passed tenant check

    return False
```

#### Qdrant Filter Builder

```python
# ACL filter for Qdrant queries
qdrant_filter = acl_filter.build_qdrant_filter(user_context)
# {
#     "must": [
#         {"key": "tenant_id", "match": {"value": "tenant-456"}},
#         {
#             "should": [
#                 {"key": "visibility", "match": {"value": "public"}},
#                 {"key": "visibility", "match": {"value": "tenant"}},
#                 {
#                     "must": [
#                         {"key": "visibility", "match": {"value": "group"}},
#                         {"key": "allowed_groups", "match": {"any": ["engineering", "product"]}}
#                     ]
#                 }
#             ]
#         }
#     ]
# }
```

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
      ],
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-15T00:00:00Z"
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
    "total_ms": 198,
    "semantic_results_count": 50,
    "keyword_results_count": 50,
    "fused_results_count": 47,
    "reranked_results_count": 20,
    "final_results_count": 10
  },
  "query_id": "query-uuid",
  "processed_at": "2024-01-15T10:30:00Z",
  "debug": {
    "query_type": "question",
    "expanded_terms": ["password reset", "sso"],
    "hyde_used": false,
    "cache_hit": false
  }
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

### Relevance Explanation

```
GET /api/v1/retrieve/explain/{chunk_id}?query={query}
```

Explains why a chunk was ranked for a specific query.

**Response:**

```json
{
  "chunk_id": "uuid-1",
  "query": "password reset",
  "explanation": {
    "semantic_contribution": 0.65,
    "keyword_contribution": 0.35,
    "matched_terms": ["password", "reset"],
    "semantic_similarity": 0.82,
    "bm25_score": 12.45
  }
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
  "version": "1.0.0",
  "components": {
    "qdrant": {"status": "healthy", "latency_ms": 5},
    "opensearch": {"status": "healthy", "latency_ms": 8},
    "redis": {"status": "healthy", "latency_ms": 2},
    "llm_gateway": {"status": "healthy", "latency_ms": 15}
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

## Configuration

### Environment Variables

```bash
# Service
RETRIEVAL_SERVICE_NAME=retrieval-service
RETRIEVAL_SERVICE_PORT=8002
RETRIEVAL_DEBUG=false

# Qdrant (Vector Store)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=documents
QDRANT_API_KEY=

# OpenSearch (Keyword Search)
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=documents
OPENSEARCH_USERNAME=admin
OPENSEARCH_PASSWORD=admin

# LLM Gateway (Embeddings & Reranking)
LLM_GATEWAY_URL=http://localhost:8004
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# Search Weights
RETRIEVAL_SEMANTIC_WEIGHT=0.7
RETRIEVAL_KEYWORD_WEIGHT=0.3
RETRIEVAL_RRF_K=60

# Reranking
RETRIEVAL_RERANK_ENABLED=true
RETRIEVAL_RERANK_TOP_K=20
RETRIEVAL_RERANK_TIMEOUT=30

# Redis (Cache)
REDIS_URL=redis://localhost:6379
RETRIEVAL_CACHE_ENABLED=true
RETRIEVAL_CACHE_TTL=3600

# JWT Authentication
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256

# Timeouts
RETRIEVAL_SEARCH_TIMEOUT=30
RETRIEVAL_EMBEDDING_TIMEOUT=10

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Metrics
PROMETHEUS_PORT=9090
```

### Pydantic Settings

```python
from config import RetrievalConfig

config = RetrievalConfig()

# Access settings
print(config.qdrant_url)         # http://localhost:6333
print(config.semantic_weight)    # 0.7
print(config.rerank_enabled)     # True
print(config.cache_ttl)          # 3600
```

---

## Caching Strategy

### Query Cache

Caches processed queries (including embeddings) to avoid repeated LLM/embedding calls.

```python
from query.cache import QueryCache

cache = QueryCache(redis_url="redis://localhost:6379", ttl=3600)

# Cache key format: query:{config_hash}:{query_hash}
# Example: query:abc123:def456

# Get or compute
cached = await cache.get(query="password reset", config=config)
if cached is None:
    processed = await preprocessor.process(query)
    await cache.set(query, config, processed)
```

### Retrieval Cache

Caches full retrieval results for repeated identical queries.

```python
from cache.retrieval_cache import RetrievalCache

cache = RetrievalCache(redis_url="redis://localhost:6379", ttl=3600)

# Cache key includes: query, mode, filters, top_k, tenant_id
cache_key = cache.build_key(
    query="password reset",
    mode="hybrid",
    filters={"language": "en"},
    top_k=10,
    tenant_id="tenant-123"
)

# Get cached results
cached = await cache.get(cache_key)
if cached:
    return cached

# Compute and cache
results = await retrieval_pipeline.search(...)
await cache.set(cache_key, results)
```

**Cache Invalidation:**
- TTL-based expiration (default: 1 hour)
- Manual invalidation by document_id
- Bulk invalidation by tenant_id

---

## Observability

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `retrieval_requests_total` | Counter | mode, status | Total requests |
| `retrieval_results_total` | Counter | mode | Total results returned |
| `retrieval_duration_seconds` | Histogram | mode, component | Request latency |
| `retrieval_preprocessing_duration_seconds` | Histogram | | Query preprocessing time |
| `retrieval_search_duration_seconds` | Histogram | type | Search time (semantic/keyword) |
| `retrieval_rerank_duration_seconds` | Histogram | | Reranking time |
| `retrieval_cache_hits_total` | Counter | type | Cache hits |
| `retrieval_cache_misses_total` | Counter | type | Cache misses |
| `retrieval_active_requests` | Gauge | | Currently processing |
| `retrieval_component_health` | Gauge | component | Component status (0/1) |

**Metrics Endpoint:**

```
GET /metrics
```

### Structured Logging

JSON-formatted logs with structlog for log aggregation.

```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "info",
  "event": "retrieval_complete",
  "query_id": "query-uuid",
  "user_id_hash": "sha256:abc123...",
  "tenant_id": "tenant-456",
  "query_length": 32,
  "mode": "hybrid",
  "results_count": 10,
  "total_ms": 198,
  "semantic_ms": 32,
  "keyword_ms": 28,
  "rerank_ms": 85,
  "cache_hit": false
}
```

**Privacy:**
- User IDs are hashed (SHA-256) in logs
- Query content is not logged by default
- PII detection for query logging (optional)

### OpenTelemetry Tracing

Distributed tracing with Jaeger integration.

```python
from observability.tracing import setup_tracing, traced

# Setup at service startup
setup_tracing(
    service_name="retrieval-service",
    otlp_endpoint="http://localhost:4317"
)

# Automatic instrumentation for FastAPI and HTTPX

# Custom spans with decorator
@traced("custom_operation")
async def my_function():
    pass
```

**Span Hierarchy:**
```
retrieval_request
├── query_preprocessing
│   ├── normalize
│   ├── classify
│   ├── expand
│   └── embed
├── parallel_search
│   ├── semantic_search
│   └── keyword_search
├── fusion
├── reranking
└── acl_filter
```

**Span Attributes:**
- `query_id`, `tenant_id`, `user_id`
- `result_count`, `latency_ms`
- `mode`, `rerank_enabled`
- `cache_hit`, `error`

---

## Performance Targets

| Operation | Target (p95) | Max (p99) |
|-----------|--------------|-----------|
| Query preprocessing | 150ms | 200ms |
| Query preprocessing (with HyDE) | 700ms | 1000ms |
| Semantic search | 50ms | 100ms |
| Keyword search | 50ms | 100ms |
| Hybrid fusion | 5ms | 10ms |
| Reranking (20 docs) | 100ms | 150ms |
| ACL filtering | 5ms | 10ms |
| **Total (without HyDE)** | **200ms** | **300ms** |
| **Total (with HyDE)** | **700ms** | **1000ms** |

### Throughput Target

- 100+ queries per second (QPS) sustained
- Horizontal scaling via Kubernetes replicas

### Scaling Recommendations

| Load | Replicas | Qdrant | OpenSearch |
|------|----------|--------|------------|
| < 10 QPS | 1 | 1 node | 1 node |
| 10-50 QPS | 2-3 | 1 node | 3 nodes |
| 50-100 QPS | 3-5 | 3 nodes | 3 nodes |
| > 100 QPS | 5+ | 3+ nodes | 5+ nodes |

---

## Testing

### Run Tests

```bash
cd services/retrieval

# Activate virtual environment
source ../../.venv/bin/activate

# Run all tests
python -m pytest -v

# Run specific module tests
python -m pytest tests/search/ -v
python -m pytest tests/query/ -v
python -m pytest tests/reranking/ -v
python -m pytest tests/acl/ -v

# Run with coverage
python -m pytest --cov=. --cov-report=html

# Run integration tests
python -m pytest tests/test_wave*.py -v
```

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| api | 30+ | 95%+ |
| search | 40+ | 98% |
| query | 35+ | 97% |
| reranking | 20+ | 96% |
| acl | 25+ | 98% |
| cache | 15+ | 95% |
| observability | 25+ | 97% |
| **Total** | **190+** | **>90%** |

### Test Categories

- **Unit Tests**: Mock external dependencies (Qdrant, OpenSearch, Redis)
- **Integration Tests**: Use docker-compose services
- **Contract Tests**: Validate API schemas
- **Performance Tests**: Latency benchmarks

---

## Troubleshooting

### Common Issues

**Qdrant connection failed:**
```bash
# Check Qdrant health
curl http://localhost:6333/health

# Verify collection exists
curl http://localhost:6333/collections/documents
```

**OpenSearch connection failed:**
```bash
# Check OpenSearch health
curl http://localhost:9200/_cluster/health

# Verify index exists
curl http://localhost:9200/documents
```

**Reranker timeout:**
```bash
# Increase timeout
export RETRIEVAL_RERANK_TIMEOUT=60

# Check LLM Gateway health
curl http://localhost:8004/health
```

**High latency:**
```bash
# Check component latencies in metrics
curl http://localhost:8002/metrics | grep duration

# Enable debug logging
export LOG_LEVEL=DEBUG
```

**Cache not working:**
```bash
# Check Redis connectivity
redis-cli ping

# Verify cache is enabled
curl http://localhost:8002/health | jq '.components.redis'
```

---

## Resilience & Degradation

The retrieval service implements circuit breakers and graceful degradation to handle backend failures without complete service outage.

### Circuit Breakers

Each backend component has a dedicated circuit breaker:

| Component | Breaker | Default Threshold | Recovery Timeout |
|-----------|---------|-------------------|------------------|
| Qdrant | `qdrant_breaker` | 5 failures | 30 seconds |
| OpenSearch | `opensearch_breaker` | 5 failures | 30 seconds |
| Reranker | `reranker_breaker` | 5 failures | 30 seconds |

### Degradation Modes

Based on circuit breaker states, the service automatically selects a degradation mode:

| Mode | Description | Search Behavior |
|------|-------------|-----------------|
| `HYBRID_FULL` | All healthy | Full hybrid search with reranking |
| `SEMANTIC_ONLY` | OpenSearch down | Vector search only (no keyword) |
| `KEYWORD_ONLY` | Qdrant down | Keyword search only (no vectors) |
| `HYBRID_NO_RERANK` | Reranker down | Hybrid search without reranking |
| `MINIMAL` | Both search backends down | Return empty results |

### Response Metadata

Search responses include degradation information:

```json
{
  "results": [...],
  "degradation": {
    "level": "degraded",
    "mode": "semantic_only",
    "components": [
      {"name": "qdrant", "available": true, "circuit_state": "closed"},
      {"name": "opensearch", "available": false, "circuit_state": "open"}
    ],
    "message": "Keyword search unavailable, using semantic search only"
  }
}
```

### Directory Structure (Resilience)

```
services/retrieval/
├── resilience/
│   ├── circuit_breaker.py     # CircuitBreaker class with state management
│   ├── degradation.py         # RetrievalDegradationManager
│   └── config.py              # CircuitBreakerConfig, ResilienceConfig
```

For full details, see [Resilience & Degradation](../resilience-degradation.md).

---

## Related Documentation

- [Architecture Overview](../architecture.md)
- [Health Check Specification](../health-check-specification.md)
- [Resilience & Degradation](../resilience-degradation.md)
- [LLM Serving Layer](../llm-serving/README.md)
- [Orchestrator Service](../orchestrator-service/README.md)
