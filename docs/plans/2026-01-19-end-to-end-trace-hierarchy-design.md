# End-to-End Trace Hierarchy Design

> **User Story:** US-10.3.2
> **Date:** 2026-01-19
> **Status:** Approved

## Overview

Establish consistent span naming and parent-child relationships across all services, enabling complete visualization of request lifecycle in Jaeger.

## Design Decisions

1. **Wrapper pattern for traced clients** - Composition with delegation for Qdrant and OpenSearch clients (not inheritance)
2. **Extend existing conventions** - Keep `RAGOperation` enum for internal operations, add new `SpanNames` class for client/external calls using `{service}.{component}.{operation}` format
3. **Centralized auto-instrumentation** - Single `setup_auto_instrumentation()` function that all services call at startup
4. **Detailed tracing at each logical step** - Explicit spans for each workflow node and search stage

## File Structure

```
services/shared/observability/
├── otel/
│   ├── __init__.py
│   ├── tracer.py          # Add setup_auto_instrumentation()
│   ├── span_names.py      # NEW - SpanNames class
│   ├── attributes.py      # Existing RAGOperation (unchanged)
│   └── ...
├── clients/
│   ├── __init__.py        # NEW
│   ├── traced_qdrant.py   # NEW - TracedQdrantClient
│   └── traced_opensearch.py # NEW - TracedOpenSearchClient
└── ...
```

## Component Designs

### 1. SpanNames Class

**File:** `services/shared/observability/otel/span_names.py`

```python
class SpanNames:
    """Canonical span names for client/external operations."""

    # Qdrant operations
    QDRANT_QUERY = "qdrant.query.search"
    QDRANT_UPSERT = "qdrant.mutation.upsert"

    # OpenSearch operations
    OPENSEARCH_QUERY = "opensearch.query.search"
    OPENSEARCH_INDEX = "opensearch.mutation.index"

    # PostgreSQL (auto-instrumented, but for reference)
    POSTGRES_QUERY = "postgres.query.select"

    # Redis (auto-instrumented, but for reference)
    REDIS_GET = "redis.query.get"
    REDIS_SET = "redis.mutation.set"

    # Retrieval service spans
    RETRIEVAL_SEARCH = "retrieval.search.hybrid"
    RETRIEVAL_PREPROCESS = "retrieval.preprocess.query"
    RETRIEVAL_EMBED_QUERY = "retrieval.embed.query"
    RETRIEVAL_SEMANTIC = "retrieval.search.semantic"
    RETRIEVAL_KEYWORD = "retrieval.search.keyword"
    RETRIEVAL_FUSION = "retrieval.fusion.rrf"
    RETRIEVAL_RERANK = "retrieval.rerank.crossencoder"

    # Orchestrator service spans
    ORCHESTRATOR_QUERY = "orchestrator.query.process"
    ORCHESTRATOR_ROUTING = "orchestrator.workflow.routing"
    ORCHESTRATOR_RETRIEVAL = "orchestrator.workflow.retrieval"
    ORCHESTRATOR_PROMPT = "orchestrator.workflow.prompt_building"
    ORCHESTRATOR_GENERATION = "orchestrator.workflow.generation"
    ORCHESTRATOR_VALIDATION = "orchestrator.workflow.validation"
```

### 2. Centralized Auto-Instrumentation

**File:** `services/shared/observability/otel/tracer.py` (update)

```python
def setup_auto_instrumentation():
    """Activate all OTEL auto-instrumentors. Idempotent."""
    HTTPXClientInstrumentation().instrument()
    AsyncPGInstrumentation().instrument()
    RedisInstrumentation().instrument()
```

### 3. TracedQdrantClient

**File:** `services/shared/observability/clients/traced_qdrant.py`

Composition-based wrapper that adds tracing to Qdrant operations:

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from qdrant_client import AsyncQdrantClient
from shared.observability.otel.span_names import SpanNames

tracer = trace.get_tracer(__name__)

class TracedQdrantClient:
    """Qdrant client wrapper with OpenTelemetry tracing."""

    def __init__(self, client: AsyncQdrantClient, collection_name: str):
        self._client = client
        self.collection_name = collection_name

    async def query_points(
        self,
        query: list[float],
        collection_name: str | None = None,
        query_filter=None,
        limit: int = 10,
        **kwargs,
    ):
        coll = collection_name or self.collection_name
        with tracer.start_as_current_span(
            SpanNames.QDRANT_QUERY,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "qdrant",
                "db.operation": "query_points",
                "db.collection": coll,
                "db.qdrant.limit": limit,
            },
        ) as span:
            try:
                result = await self._client.query_points(
                    collection_name=coll,
                    query=query,
                    query_filter=query_filter,
                    limit=limit,
                    **kwargs,
                )
                if hasattr(result, "points"):
                    span.set_attribute("db.response_size", len(result.points))
                return result
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise

    async def upsert(self, points: list, collection_name: str | None = None, **kwargs):
        coll = collection_name or self.collection_name
        with tracer.start_as_current_span(
            SpanNames.QDRANT_UPSERT,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "qdrant",
                "db.operation": "upsert",
                "db.collection": coll,
                "db.qdrant.points_count": len(points) if points else 0,
            },
        ) as span:
            try:
                return await self._client.upsert(
                    collection_name=coll, points=points, **kwargs
                )
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise
```

### 4. TracedOpenSearchClient

**File:** `services/shared/observability/clients/traced_opensearch.py`

```python
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opensearchpy import AsyncOpenSearch
from shared.observability.otel.span_names import SpanNames

tracer = trace.get_tracer(__name__)

class TracedOpenSearchClient:
    """OpenSearch client wrapper with OpenTelemetry tracing."""

    def __init__(self, client: AsyncOpenSearch, index_name: str):
        self._client = client
        self.index_name = index_name

    async def search(self, body: dict, index: str | None = None, **kwargs):
        idx = index or self.index_name
        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_QUERY,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "opensearch",
                "db.operation": "search",
                "db.elasticsearch.index": idx,
            },
        ) as span:
            try:
                result = await self._client.search(index=idx, body=body, **kwargs)
                hits = result.get("hits", {})
                total = hits.get("total", {})
                count = total.get("value", 0) if isinstance(total, dict) else total
                span.set_attribute("db.response_size", count)
                return result
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise

    async def index(self, body: dict, index: str | None = None, **kwargs):
        idx = index or self.index_name
        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_INDEX,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "opensearch",
                "db.operation": "index",
                "db.elasticsearch.index": idx,
            },
        ) as span:
            try:
                return await self._client.index(index=idx, body=body, **kwargs)
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise

    async def bulk(self, body: list, index: str | None = None, **kwargs):
        idx = index or self.index_name
        with tracer.start_as_current_span(
            SpanNames.OPENSEARCH_INDEX,
            kind=SpanKind.CLIENT,
            attributes={
                "db.system": "opensearch",
                "db.operation": "bulk",
                "db.elasticsearch.index": idx,
                "db.opensearch.bulk_size": len(body) if body else 0,
            },
        ) as span:
            try:
                return await self._client.bulk(body=body, index=idx, **kwargs)
            except Exception as e:
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                raise
```

### 5. Trace Hierarchy

**Retrieval Service:**
```
retrieval.search.hybrid (root)
├── retrieval.preprocess.query
├── retrieval.embed.query
├── retrieval.search.semantic
│   └── qdrant.query.search (from TracedQdrantClient)
├── retrieval.search.keyword
│   └── opensearch.query.search (from TracedOpenSearchClient)
├── retrieval.fusion.rrf
└── retrieval.rerank.crossencoder
```

**Orchestrator Service:**
```
orchestrator.query.process (root)
├── orchestrator.workflow.routing
├── orchestrator.workflow.retrieval
│   └── retrieval.search.hybrid (HTTP call to retrieval service)
├── orchestrator.workflow.prompt_building
├── orchestrator.workflow.generation
│   └── llm.completion.stream (from LLM client)
└── orchestrator.workflow.validation
```

**Complete E2E Trace:**
```
orchestrator.query.process (root)
├── orchestrator.workflow.routing
├── orchestrator.workflow.retrieval
│   └── HTTP POST /api/v1/retrieve (httpx auto-instrumented)
│       └── retrieval.search.hybrid
│           ├── retrieval.preprocess.query
│           ├── retrieval.embed.query
│           ├── retrieval.search.semantic
│           │   └── qdrant.query.search
│           ├── retrieval.search.keyword
│           │   └── opensearch.query.search
│           ├── retrieval.fusion.rrf
│           └── retrieval.rerank.crossencoder
├── orchestrator.workflow.prompt_building
├── orchestrator.workflow.generation
│   └── llm.completion.stream
└── orchestrator.workflow.validation
```

## Implementation Plan

1. Create SpanNames class
2. Update tracer.py with setup_auto_instrumentation()
3. Create traced clients directory with TracedQdrantClient and TracedOpenSearchClient
4. Update requirements.txt files with missing OTEL instrumentors
5. Update service initialization to call setup_auto_instrumentation()
6. Integrate TracedQdrantClient in retrieval and ingestion services
7. Integrate TracedOpenSearchClient in retrieval and ingestion services
8. Add retrieval service tracing around search pipeline stages
9. Add orchestrator service tracing around workflow nodes
10. Write unit tests for traced clients
11. Write integration test for trace hierarchy verification

## Dependencies

- `opentelemetry-instrumentation-httpx>=0.43b0`
- `opentelemetry-instrumentation-asyncpg>=0.43b0`
- `opentelemetry-instrumentation-redis>=0.43b0`
