# Correlation ID Propagation

> **Status:** Production Ready
> **Implemented:** US-10.3.1
> **Last Updated:** January 2026

## Overview

The RAG pipeline implements strict correlation ID propagation across all services, enabling complete request tracing from ingestion through retrieval to generation. Every request is assigned a unique identifier that flows through HTTP calls, Celery tasks, and logging contexts.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Correlation Context](#correlation-context)
3. [HTTP Header Standards](#http-header-standards)
4. [Middleware Integration](#middleware-integration)
5. [HTTP Client Integration](#http-client-integration)
6. [Celery Task Integration](#celery-task-integration)
7. [Log Joinability](#log-joinability)
8. [Configuration](#configuration)
9. [Usage Examples](#usage-examples)
10. [Troubleshooting](#troubleshooting)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Client Request                                   │
│                    X-Request-ID: <uuid>                                  │
│                    X-Tenant-ID: <tenant>                                 │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Correlation Middleware                                │
│  • Extract/generate request_id                                          │
│  • Bind to structlog context                                            │
│  • Bind to OTEL span attributes                                         │
│  • Store in ContextVar                                                  │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│   Retrieval     │        │   Orchestrator  │        │   Ingestion     │
│   Service       │        │   Service       │        │   Service       │
│                 │        │                 │        │                 │
│ Headers passed  │◄──────►│ CorrelatedHttp  │        │ Celery tasks    │
│ via middleware  │        │ Client          │        │ with context    │
└─────────────────┘        └─────────────────┘        └─────────────────┘
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Structured Logs (Loki)                                │
│  All logs include: request_id, trace_id, tenant_id, service             │
│  Logs are joinable across services by request_id                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Correlation Context

The `CorrelationContext` dataclass holds all correlation information for a request:

```python
from shared.observability.correlation import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
)

# Get current context
ctx = get_correlation_context()
if ctx:
    print(f"Request ID: {ctx.request_id}")
    print(f"Trace ID: {ctx.trace_id}")
    print(f"Tenant ID: {ctx.tenant_id}")
```

### Context Fields

| Field | Description | Source |
|-------|-------------|--------|
| `request_id` | Unique identifier for the user request | Generated or from `X-Request-ID` header |
| `trace_id` | OpenTelemetry trace ID | From `X-Trace-ID` header or equals `request_id` |
| `tenant_id` | Tenant context for multi-tenancy | From `X-Tenant-ID` header |
| `user_id_hash` | Hashed user ID for privacy | From `X-User-ID-Hash` header |
| `span_id` | Current OTEL span ID | From active span |

### Context Storage

The correlation context uses Python's `contextvars` for async-safe storage:

```python
from contextvars import ContextVar

_correlation_context: ContextVar[CorrelationContext | None] = ContextVar(
    "correlation_context", default=None
)
```

This ensures context is properly isolated across concurrent requests.

---

## HTTP Header Standards

### Standard Headers

| Header | Purpose | Format | Example |
|--------|---------|--------|---------|
| `X-Request-ID` | Unique request identifier | UUID v4 | `550e8400-e29b-41d4-a716-446655440000` |
| `X-Trace-ID` | OTEL trace ID | UUID v4 or 32-char hex | `550e8400-e29b-41d4-a716-446655440000` |
| `X-Tenant-ID` | Tenant identifier | String | `acme-corp` |
| `X-User-ID-Hash` | Hashed user ID | 16-char hex | `a1b2c3d4e5f6a7b8` |

### Header Behavior

1. **Incoming requests**: Headers are extracted and stored in context
2. **Missing headers**: `request_id` and `trace_id` are auto-generated as UUIDs
3. **Outgoing requests**: Context is serialized to headers automatically
4. **Response headers**: `X-Request-ID` and `X-Trace-ID` included in responses

---

## Middleware Integration

### FastAPI Middleware

Add the `CorrelationMiddleware` to your FastAPI application:

```python
from fastapi import FastAPI
from shared.observability.correlation import CorrelationMiddleware

app = FastAPI()
app.add_middleware(CorrelationMiddleware)
```

### Middleware Behavior

The middleware performs the following on each request:

1. **Extract headers** into `CorrelationContext`
2. **Generate IDs** if missing (UUIDs for `request_id`/`trace_id`)
3. **Set context variable** for async access throughout request
4. **Bind to structlog** for automatic log inclusion
5. **Set OTEL span attributes** for trace correlation
6. **Log request start/completion** with timing
7. **Add headers to response** for client correlation
8. **Clean up context** after request completes

### Example Log Output

```json
{
  "timestamp": "2026-01-19T10:30:00.123Z",
  "level": "INFO",
  "event": "request_started",
  "service": "orchestrator",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "acme-corp",
  "method": "POST",
  "path": "/api/v1/query"
}
```

---

## HTTP Client Integration

### CorrelatedHttpClient

Use `CorrelatedHttpClient` for inter-service communication to automatically propagate correlation headers:

```python
from shared.observability.correlation import (
    CorrelatedHttpClient,
    create_service_client,
)

# Create a client for the retrieval service
retrieval_client = create_service_client(
    service_name="retrieval",
    base_url="http://retrieval-service:8002"
)

# Make requests - headers automatically included
response = await retrieval_client.post(
    "/api/v1/retrieve",
    json={"query": "How do I reset my password?", "top_k": 10}
)

# Headers X-Request-ID, X-Trace-ID, X-Tenant-ID are automatically added
```

### Client Methods

```python
class CorrelatedHttpClient:
    async def get(self, path: str, params: dict | None = None, **kwargs) -> Response
    async def post(self, path: str, json: Any = None, data: Any = None, **kwargs) -> Response
    async def put(self, path: str, json: Any = None, **kwargs) -> Response
    async def delete(self, path: str, **kwargs) -> Response
```

All methods automatically inject correlation headers from the current context.

---

## Celery Task Integration

### Setup

Enable Celery correlation by setting up signal handlers at worker startup:

```python
from shared.observability.correlation import setup_celery_correlation_signals

# In your Celery app configuration
setup_celery_correlation_signals()
```

### Automatic Propagation

When tasks are enqueued, correlation context is automatically serialized to task headers:

```python
# In an HTTP request handler
@app.post("/api/v1/ingest")
async def ingest_document(doc: Document):
    # Context is automatically propagated to the Celery task
    process_document.delay(doc.id)
    return {"status": "queued"}
```

### Task Context Restoration

Tasks automatically restore correlation context at execution:

```python
@celery_app.task
def process_document(document_id: str):
    # Correlation context is automatically available
    ctx = get_correlation_context()
    logger.info(
        "Processing document",
        document_id=document_id,
        # request_id, trace_id, tenant_id automatically included
    )
```

### Signal Handlers

| Signal | Purpose |
|--------|---------|
| `before_task_publish` | Inject correlation context into task headers |
| `task_prerun` | Restore correlation context and bind to structlog |
| `task_postrun` | Clean up correlation context |

---

## Log Joinability

All logs across services can be joined by `request_id`:

### Query Example (Loki/LogQL)

```logql
{service=~"orchestrator|retrieval|ingestion"} |= "550e8400-e29b-41d4-a716-446655440000"
```

### Grafana Correlation

In Grafana, logs include clickable links to associated traces:

1. View a log line with `trace_id`
2. Click the trace ID to jump to Jaeger/Tempo
3. See the complete distributed trace

### Log Format Consistency

All services emit logs with consistent fields:

```json
{
  "timestamp": "2026-01-19T10:30:00.123Z",
  "level": "INFO",
  "event": "retrieval_completed",
  "service": "retrieval",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "acme-corp",
  "result_count": 10,
  "duration_ms": 145
}
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CORRELATION_HEADER_REQUEST_ID` | Header name for request ID | `X-Request-ID` |
| `CORRELATION_HEADER_TRACE_ID` | Header name for trace ID | `X-Trace-ID` |
| `CORRELATION_HEADER_TENANT_ID` | Header name for tenant ID | `X-Tenant-ID` |
| `CORRELATION_HEADER_USER_ID_HASH` | Header name for user ID hash | `X-User-ID-Hash` |

### Service Configuration

Each service should initialize correlation in its startup:

```python
# In service main.py or app factory
from fastapi import FastAPI
from shared.observability.correlation import CorrelationMiddleware
from shared.observability.otel import setup_tracing
from shared.observability.logging import setup_logging

def create_app() -> FastAPI:
    app = FastAPI(title="My Service")

    # Setup tracing first
    setup_tracing(service_name="my-service")

    # Setup logging with correlation support
    setup_logging(service_name="my-service", json_format=True)

    # Add correlation middleware (before other middleware)
    app.add_middleware(CorrelationMiddleware)

    return app
```

---

## Usage Examples

### Complete Request Flow

```python
# 1. Client makes request with optional correlation headers
# curl -H "X-Request-ID: abc-123" -H "X-Tenant-ID: acme" http://orchestrator/query

# 2. Orchestrator receives request, middleware sets up context
@app.post("/api/v1/query")
async def query(request: QueryRequest):
    # Context automatically available
    ctx = get_correlation_context()
    logger.info("Processing query", query=request.query)

    # 3. Call retrieval service - headers propagated automatically
    results = await retrieval_client.post("/retrieve", json={"query": request.query})

    # 4. Call LLM - headers propagated
    response = await llm_client.post("/generate", json={"context": results})

    return response

# 5. All services log with same request_id
# 6. Response includes X-Request-ID header
```

### Manual Context Access

```python
from shared.observability.correlation import (
    get_correlation_context,
    set_correlation_context,
    CorrelationContext,
)

# Get current context
ctx = get_correlation_context()

# Create new context (useful for background jobs)
new_ctx = CorrelationContext.generate(
    tenant_id="background-tenant",
    user_id="system"
)
set_correlation_context(new_ctx)

# Convert to headers for external calls
headers = ctx.to_headers()
# {'X-Request-ID': '...', 'X-Trace-ID': '...', 'X-Tenant-ID': '...'}
```

### Privacy-Preserving User ID

```python
# User IDs are hashed for privacy in logs
ctx = CorrelationContext.generate(
    tenant_id="acme-corp",
    user_id="user@example.com"  # Original ID
)

# Stored as SHA-256 hash truncated to 16 chars
print(ctx.user_id_hash)  # e.g., "a1b2c3d4e5f6a7b8"
```

---

## Troubleshooting

### Missing Correlation in Logs

**Symptom:** Logs don't include `request_id`

**Causes:**
1. Middleware not added to FastAPI app
2. Logging not configured with structlog
3. Context not bound before logging

**Fix:**
```python
# Ensure middleware is added
app.add_middleware(CorrelationMiddleware)

# Ensure structlog is configured
import structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,  # Required!
        # ... other processors
    ]
)
```

### Correlation Lost in Celery Tasks

**Symptom:** Tasks don't have correlation context

**Causes:**
1. Signal handlers not set up
2. Task enqueued outside of request context

**Fix:**
```python
# At worker startup
from shared.observability.correlation import setup_celery_correlation_signals
setup_celery_correlation_signals()

# For tasks enqueued outside requests, create context manually
ctx = CorrelationContext.generate(tenant_id="system")
set_correlation_context(ctx)
my_task.delay()
```

### Headers Not Propagated

**Symptom:** Downstream services don't receive correlation headers

**Causes:**
1. Using raw `httpx` instead of `CorrelatedHttpClient`
2. Context not set when making request

**Fix:**
```python
# Use CorrelatedHttpClient
from shared.observability.correlation import create_service_client

client = create_service_client("retrieval", "http://retrieval:8002")
response = await client.post("/api/v1/retrieve", json=data)
```

---

## Implementation Reference

| Component | Location |
|-----------|----------|
| Context dataclass | `services/shared/observability/correlation/context.py` |
| FastAPI middleware | `services/shared/observability/correlation/middleware.py` |
| HTTP client | `services/shared/observability/correlation/http_client.py` |
| Celery integration | `services/shared/observability/correlation/celery.py` |
| Tests | `services/shared/observability/correlation/tests/` |

---

## Related Documentation

- [Trace Hierarchy](./trace-hierarchy.md) - Span naming and parent-child relationships
- [Structured Logging](#structured-logging) - Log format and configuration
- [OpenTelemetry Integration](#opentelemetry-integration) - Distributed tracing setup
