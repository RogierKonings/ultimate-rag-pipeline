# Trace Hierarchy Documentation

## Overview

This document describes the span naming conventions and trace hierarchy
for the RAG pipeline, enabling complete visualization of request lifecycle
in Jaeger and similar tools.

## Span Naming Convention

All spans follow the pattern: `{service}.{component}.{operation}`

### External Services
- `qdrant.query.search` - Vector similarity search
- `qdrant.mutation.upsert` - Vector upsert
- `opensearch.query.search` - Keyword search
- `opensearch.mutation.index` - Document indexing

### Retrieval Service
- `retrieval.search.hybrid` - Root span for hybrid search
- `retrieval.preprocess.query` - Query preprocessing
- `retrieval.embed.query` - Query embedding
- `retrieval.search.semantic` - Semantic search phase
- `retrieval.search.keyword` - Keyword search phase
- `retrieval.fusion.rrf` - RRF fusion
- `retrieval.rerank.crossencoder` - Reranking

### Orchestrator Service
- `orchestrator.query.process` - Root span for query processing
- `orchestrator.workflow.routing` - Strategy routing
- `orchestrator.workflow.retrieval` - Retrieval node
- `orchestrator.workflow.prompt_building` - Prompt construction
- `orchestrator.workflow.generation` - LLM generation
- `orchestrator.workflow.validation` - Response validation

## Complete Trace Hierarchy

```
orchestrator.query.process
├── orchestrator.workflow.routing
├── orchestrator.workflow.retrieval
│   └── HTTP POST /api/v1/retrieve
│       └── retrieval.search.hybrid
│           ├── retrieval.search.semantic
│           │   └── qdrant.query.search
│           ├── retrieval.search.keyword
│           │   └── opensearch.query.search
│           └── retrieval.fusion.rrf
├── orchestrator.workflow.prompt_building
├── orchestrator.workflow.generation
│   └── llm.completion.stream
└── orchestrator.workflow.validation
```

## Viewing Traces in Jaeger

1. Access Jaeger UI at `http://localhost:16686`
2. Select service: `orchestrator`, `retrieval`, or `ingestion`
3. Search for traces by:
   - Operation name (e.g., `orchestrator.query.process`)
   - Tags (e.g., `tenant_id=xxx`)
   - Time range

## Span Attributes

### Common Attributes
- `tenant_id` - Tenant identifier
- `db.system` - Database system (qdrant, opensearch, postgres)
- `db.operation` - Operation type

### Retrieval Attributes
- `retrieval.query_length` - Query text length
- `retrieval.result_count` - Number of results

### Orchestrator Attributes
- `orchestrator.strategy` - Selected routing strategy
- `orchestrator.model` - LLM model used

## Auto-Instrumentation

The following libraries are automatically instrumented:
- `httpx` - HTTP client calls between services
- `asyncpg` - PostgreSQL database queries
- `redis` - Redis cache operations

Auto-instrumentation is initialized at service startup via `setup_auto_instrumentation()`.

## Traced Client Wrappers

Custom traced wrappers are provided for:
- `TracedQdrantClient` - Wraps AsyncQdrantClient with span creation
- `TracedOpenSearchClient` - Wraps AsyncOpenSearch with span creation

These wrappers ensure proper parent-child relationships in traces.

## Implementation

See:
- `services/shared/observability/otel/span_names.py` - Canonical span names
- `services/shared/observability/clients/` - Traced client wrappers
- `services/shared/observability/otel/tracer.py` - Setup functions
