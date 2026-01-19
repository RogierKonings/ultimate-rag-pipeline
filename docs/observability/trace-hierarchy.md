# End-to-End Trace Hierarchy

> **Status:** Production Ready
> **Implemented:** US-10.3.2
> **Last Updated:** January 2026

## Overview

This document describes the span naming conventions, trace hierarchy, and correlation context for the RAG pipeline, enabling complete visualization of request lifecycle in Jaeger and similar tools.

---

## Table of Contents

1. [Span Naming Convention](#span-naming-convention)
2. [Complete Trace Hierarchy](#complete-trace-hierarchy)
3. [Correlation with Request IDs](#correlation-with-request-ids)
4. [Span Attributes](#span-attributes)
5. [Auto-Instrumentation](#auto-instrumentation)
6. [Traced Client Wrappers](#traced-client-wrappers)
7. [Viewing Traces](#viewing-traces)
8. [Implementation Reference](#implementation-reference)

---

## Span Naming Convention

All spans follow the pattern: `{service}.{component}.{operation}`

### Services

| Service | Description |
|---------|-------------|
| `orchestrator` | RAG workflow orchestration |
| `retrieval` | Hybrid search operations |
| `ingestion` | Document processing |
| `qdrant` | Vector database operations |
| `opensearch` | Keyword search operations |
| `postgres` | Metadata database queries |
| `redis` | Cache operations |
| `llm` | LLM inference |
| `embedding` | Embedding generation |

### Orchestrator Service Spans

| Span Name | Description |
|-----------|-------------|
| `orchestrator.query.process` | Root span for query processing |
| `orchestrator.workflow.routing` | Strategy routing decision |
| `orchestrator.workflow.retrieval` | Retrieval node execution |
| `orchestrator.workflow.prompt_building` | Prompt construction |
| `orchestrator.workflow.generation` | LLM generation |
| `orchestrator.workflow.verification` | Answer verification |
| `orchestrator.workflow.validation` | Response validation |
| `orchestrator.workflow.input_validation` | Input guardrails |
| `orchestrator.workflow.output_validation` | Output guardrails |
| `orchestrator.cache.check` | Cache lookup |
| `orchestrator.cache.store` | Cache storage |

### Retrieval Service Spans

| Span Name | Description |
|-----------|-------------|
| `retrieval.search.hybrid` | Root span for hybrid search |
| `retrieval.preprocess.query` | Query preprocessing |
| `retrieval.embed.query` | Query embedding |
| `retrieval.search.semantic` | Semantic (vector) search |
| `retrieval.search.keyword` | Keyword (BM25) search |
| `retrieval.fusion.rrf` | Reciprocal Rank Fusion |
| `retrieval.rerank.crossencoder` | Cross-encoder reranking |
| `retrieval.filter.acl` | ACL filtering |

### Ingestion Service Spans

| Span Name | Description |
|-----------|-------------|
| `ingestion.document.process` | Root span for document processing |
| `ingestion.parse.document` | Document parsing |
| `ingestion.chunk.split` | Chunking |
| `ingestion.embed.batch` | Batch embedding |
| `ingestion.index.qdrant` | Qdrant indexing |
| `ingestion.index.opensearch` | OpenSearch indexing |

### External Service Spans

| Span Name | Description |
|-----------|-------------|
| `qdrant.query.search` | Vector similarity search |
| `qdrant.mutation.upsert` | Vector upsert |
| `qdrant.mutation.delete` | Vector deletion |
| `opensearch.query.search` | Keyword search |
| `opensearch.mutation.index` | Document indexing |
| `opensearch.mutation.bulk` | Bulk indexing |
| `llm.completion.generate` | Synchronous LLM inference |
| `llm.completion.stream` | Streaming LLM inference |
| `embedding.encode.batch` | Batch embedding generation |

---

## Complete Trace Hierarchy

### RAG Query Flow

```
orchestrator.query.process (root)
├── orchestrator.cache.check
├── orchestrator.workflow.input_validation
├── orchestrator.workflow.routing
├── orchestrator.workflow.retrieval
│   └── HTTP POST /api/v1/retrieve
│       └── retrieval.search.hybrid
│           ├── retrieval.preprocess.query
│           ├── retrieval.embed.query
│           │   └── embedding.encode.batch
│           ├── retrieval.search.semantic
│           │   └── qdrant.query.search
│           ├── retrieval.search.keyword
│           │   └── opensearch.query.search
│           ├── retrieval.fusion.rrf
│           ├── retrieval.rerank.crossencoder
│           │   └── llm.completion.generate (reranker)
│           └── retrieval.filter.acl
├── orchestrator.workflow.prompt_building
├── orchestrator.workflow.generation
│   └── llm.completion.stream
├── orchestrator.workflow.verification
├── orchestrator.workflow.output_validation
└── orchestrator.cache.store
```

### Document Ingestion Flow

```
ingestion.document.process (root)
├── ingestion.parse.document
├── ingestion.chunk.split
├── ingestion.embed.batch
│   └── embedding.encode.batch
├── ingestion.index.qdrant
│   └── qdrant.mutation.upsert
└── ingestion.index.opensearch
    └── opensearch.mutation.bulk
```

---

## Correlation with Request IDs

Traces are correlated with request IDs via span attributes. Every span in a request includes:

| Attribute | Description |
|-----------|-------------|
| `request_id` | Unique identifier for the user request |
| `trace_id` | OpenTelemetry trace ID |
| `tenant_id` | Tenant context |

### W3C Trace Context Propagation

Trace context is propagated across service boundaries using W3C headers:

```
traceparent: 00-<trace_id>-<span_id>-<flags>
tracestate: <vendor-specific data>
```

Combined with correlation headers:

```
X-Request-ID: <request_id>
X-Trace-ID: <trace_id>
X-Tenant-ID: <tenant_id>
```

### Log-Trace Correlation

All logs include `trace_id` enabling clickable links in Grafana:

```json
{
  "timestamp": "2026-01-19T10:30:00.123Z",
  "level": "INFO",
  "message": "Retrieval completed",
  "trace_id": "abc123def456",
  "span_id": "789xyz",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "result_count": 10
}
```

---

## Span Attributes

### Common Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `request_id` | string | Unique request identifier |
| `tenant_id` | string | Tenant context |
| `service.name` | string | Service name |
| `service.version` | string | Service version |

### Database Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `db.system` | string | Database system (qdrant, opensearch, postgres) |
| `db.operation` | string | Operation type (query, upsert, search) |
| `db.collection` | string | Collection/index name |
| `db.response_size` | int | Number of results |

### Retrieval Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `retrieval.query_length` | int | Query text length |
| `retrieval.result_count` | int | Number of results |
| `retrieval.strategy` | string | Search strategy (hybrid, semantic, keyword) |
| `fusion.method` | string | Fusion method (rrf) |
| `fusion.k` | int | RRF constant |
| `rerank.model` | string | Reranker model name |
| `rerank.input_size` | int | Candidates before reranking |
| `rerank.output_size` | int | Results after reranking |

### Orchestrator Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `orchestrator.query_length` | int | Query text length |
| `orchestrator.strategy` | string | Routing strategy (simple, complex, no_retrieval) |
| `orchestrator.session_id` | string | Conversation session ID |

### LLM Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `llm.model` | string | Model name |
| `llm.provider` | string | Provider (vllm, ollama) |
| `llm.input_tokens` | int | Input token count |
| `llm.output_tokens` | int | Output token count |
| `llm.total_tokens` | int | Total tokens |
| `llm.ttft_ms` | float | Time to first token (streaming) |

### Embedding Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `embedding.model` | string | Embedding model name |
| `embedding.batch_size` | int | Number of texts in batch |
| `embedding.dimensions` | int | Vector dimensions |

---

## Auto-Instrumentation

The following libraries are automatically instrumented at service startup:

| Library | Instrumentation |
|---------|-----------------|
| `httpx` | HTTP client calls between services |
| `asyncpg` | PostgreSQL database queries |
| `redis` | Redis cache operations |

### Setup

```python
from shared.observability.otel import setup_tracing

# Initialize tracing with auto-instrumentation
setup_tracing(
    service_name="retrieval-service",
    service_version="1.0.0",
    environment="production"
)
```

---

## Traced Client Wrappers

Custom traced wrappers ensure proper parent-child relationships for external services.

### TracedQdrantClient

```python
from shared.observability.clients import TracedQdrantClient

# Wrap Qdrant client
qdrant = TracedQdrantClient(
    client=async_qdrant_client,
    collection_name="documents"
)

# Spans automatically created for operations
results = await qdrant.query_points(
    query=embedding_vector,
    query_filter=filters,
    limit=10
)
```

**Created spans:**
- `qdrant.query.search` for query operations
- `qdrant.mutation.upsert` for upsert operations
- `qdrant.mutation.delete` for delete operations

### TracedOpenSearchClient

```python
from shared.observability.clients import TracedOpenSearchClient

# Wrap OpenSearch client
opensearch = TracedOpenSearchClient(
    client=async_opensearch_client,
    index_name="documents"
)

# Spans automatically created
results = await opensearch.search(body=query_body)
```

**Created spans:**
- `opensearch.query.search` for search operations
- `opensearch.mutation.index` for index operations
- `opensearch.mutation.bulk` for bulk operations

---

## Viewing Traces

### Jaeger UI

1. Access Jaeger at `http://localhost:16686`
2. Select service from dropdown
3. Search by:
   - **Operation**: e.g., `orchestrator.query.process`
   - **Tags**: e.g., `tenant_id=acme-corp`, `request_id=550e8400-...`
   - **Time range**: Filter by duration

### Finding Traces by Request ID

1. In Jaeger, use tag search: `request_id=<your-request-id>`
2. Or search logs in Grafana/Loki, click trace link

### Trace Analysis Tips

1. **Identify bottlenecks**: Look for longest spans in the hierarchy
2. **Check parallelism**: Semantic and keyword search should overlap
3. **Verify caching**: Cache hits should show short durations
4. **Monitor reranking**: Reranking adds latency but improves quality

### Example Queries

```
# Find slow queries (> 2s)
service=orchestrator duration>2s

# Find errors
service=retrieval error=true

# Find specific tenant
tenant_id=acme-corp

# Find by request ID
request_id=550e8400-e29b-41d4-a716-446655440000
```

---

## Implementation Reference

| Component | Location |
|-----------|----------|
| Span names | `services/shared/observability/otel/span_names.py` |
| Tracer setup | `services/shared/observability/otel/tracer.py` |
| Traced Qdrant | `services/shared/observability/clients/traced_qdrant.py` |
| Traced OpenSearch | `services/shared/observability/clients/traced_opensearch.py` |
| Correlation context | `services/shared/observability/correlation/` |
| Tests | `services/shared/observability/tests/test_trace_hierarchy.py` |

---

## Related Documentation

- [Correlation ID Propagation](./correlation-id-propagation.md) - Request ID propagation across services
- [Observability Overview](./README.md) - Complete observability stack documentation
