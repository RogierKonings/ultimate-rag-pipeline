# Resilience & Graceful Degradation

> **Status:** Production
> **Last Updated:** January 2026

This document describes the resilience patterns implemented across the RAG pipeline, including circuit breakers, degradation modes, timeout policies, and cross-service degradation propagation.

---

## Table of Contents

- [Overview](#overview)
- [Circuit Breakers](#circuit-breakers)
  - [Circuit Breaker States](#circuit-breaker-states)
  - [Configuration](#circuit-breaker-configuration)
  - [Usage](#circuit-breaker-usage)
- [Degradation Modes](#degradation-modes)
  - [Retrieval Service Degradation](#retrieval-service-degradation)
  - [Mode Selection Logic](#mode-selection-logic)
  - [Health Endpoint Enhancement](#health-endpoint-enhancement)
- [Cross-Service Degradation Propagation](#cross-service-degradation-propagation)
  - [Retrieval Response Schema](#retrieval-response-schema)
  - [Orchestrator Handling](#orchestrator-handling)
  - [Prompt Adjustments](#prompt-adjustments)
- [Timeout & Retry Policies](#timeout--retry-policies)
  - [Timeout Cascade](#timeout-cascade)
  - [Retry Behavior](#retry-behavior)
  - [Validation](#timeout-validation)
- [Prometheus Metrics](#prometheus-metrics)
- [Operational Guide](#operational-guide)

---

## Overview

The RAG pipeline implements a comprehensive resilience strategy to ensure graceful degradation when backend components become unhealthy. The key principles are:

1. **Fail gracefully** - Return partial results instead of errors when possible
2. **Fail fast** - Use circuit breakers to avoid cascading failures
3. **Propagate status** - Inform upstream services and users about degraded state
4. **Recover automatically** - Test recovery and restore normal operation

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Orchestrator Service                               │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Degradation-Aware Workflow                        │   │
│  │  • Parses degradation info from retrieval response                   │   │
│  │  • Adjusts prompts based on context quality                          │   │
│  │  • Includes quality indicators in streaming events                   │   │
│  │  • Returns metadata with retrieval mode used                         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
└────────────────────────────────────┼─────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Retrieval Service                                  │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    RetrievalDegradationManager                        │   │
│  │                                                                       │   │
│  │    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐              │   │
│  │    │   Qdrant    │   │ OpenSearch  │   │  Reranker   │              │   │
│  │    │   Circuit   │   │   Circuit   │   │   Circuit   │              │   │
│  │    │   Breaker   │   │   Breaker   │   │   Breaker   │              │   │
│  │    └─────────────┘   └─────────────┘   └─────────────┘              │   │
│  │           │                 │                 │                      │   │
│  │           └─────────────────┴─────────────────┘                      │   │
│  │                            │                                         │   │
│  │                            ▼                                         │   │
│  │                  ┌─────────────────────┐                             │   │
│  │                  │   Degradation Mode   │                             │   │
│  │                  │   HYBRID_FULL       │                             │   │
│  │                  │   SEMANTIC_ONLY     │                             │   │
│  │                  │   KEYWORD_ONLY      │                             │   │
│  │                  │   HYBRID_NO_RERANK  │                             │   │
│  │                  │   MINIMAL           │                             │   │
│  │                  └─────────────────────┘                             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Circuit Breakers

Circuit breakers prevent cascading failures by stopping calls to unhealthy services after a threshold of failures.

### Circuit Breaker States

| State | Description | Behavior |
|-------|-------------|----------|
| **CLOSED** | Normal operation | Requests pass through, failures tracked |
| **OPEN** | Service failing | Requests rejected immediately or use fallback |
| **HALF_OPEN** | Testing recovery | Limited requests allowed to test if service recovered |

```
     ┌──────────────────────────────────────────────────────┐
     │                                                      │
     │                     CLOSED                           │
     │              (Normal Operation)                      │
     │                                                      │
     └────────────────────┬─────────────────────────────────┘
                          │
                          │ failure_count >= failure_threshold
                          ▼
     ┌──────────────────────────────────────────────────────┐
     │                                                      │
     │                      OPEN                            │
     │              (Requests Rejected)                     │
     │                                                      │
     └────────────────────┬─────────────────────────────────┘
                          │
                          │ recovery_timeout elapsed
                          ▼
     ┌──────────────────────────────────────────────────────┐
     │                                                      │
     │                   HALF_OPEN                          │
     │              (Testing Recovery)                      │
     │                                                      │
     └───────────────┬──────────────────────┬───────────────┘
                     │                      │
         success     │                      │ failure
                     ▼                      ▼
                  CLOSED                   OPEN
```

### Circuit Breaker Configuration

```python
# services/retrieval/resilience/config.py

from pydantic import BaseModel, Field

class CircuitBreakerConfig(BaseModel):
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = Field(
        default=5,
        ge=1,
        description="Number of failures before the circuit opens"
    )
    recovery_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Seconds to wait before attempting recovery"
    )
    half_open_max_calls: int = Field(
        default=3,
        ge=1,
        description="Maximum calls allowed in HALF_OPEN state"
    )

class ResilienceConfig(BaseModel):
    """Top-level configuration for the resilience module."""

    qdrant_circuit: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    opensearch_circuit: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    reranker_circuit: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    enable_metrics: bool = Field(default=True)
```

**Environment Variable Overrides:**

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_CIRCUIT_FAILURE_THRESHOLD` | 5 | Failures before Qdrant circuit opens |
| `QDRANT_CIRCUIT_RECOVERY_TIMEOUT` | 30.0 | Seconds before testing Qdrant recovery |
| `OPENSEARCH_CIRCUIT_FAILURE_THRESHOLD` | 5 | Failures before OpenSearch circuit opens |
| `RERANKER_CIRCUIT_FAILURE_THRESHOLD` | 5 | Failures before reranker circuit opens |

### Circuit Breaker Usage

```python
from retrieval.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError
from retrieval.resilience.config import CircuitBreakerConfig

# Create a circuit breaker
breaker = CircuitBreaker(
    name="qdrant",
    config=CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=30.0,
        half_open_max_calls=3
    )
)

# Use with fallback
async def search_with_fallback():
    result = await breaker.call(
        qdrant_client.search,
        collection="documents",
        query_vector=embedding,
        fallback=lambda *args, **kwargs: []  # Return empty on failure
    )
    return result

# Check circuit state
if breaker.is_healthy:
    print(f"Circuit {breaker.name} is healthy")
else:
    print(f"Circuit {breaker.name} is {breaker.state.value}")

# Get metrics
metrics = breaker.get_metrics()
# {
#     "name": "qdrant",
#     "state": "closed",
#     "failure_count": 0,
#     "total_calls": 150,
#     "total_successes": 148,
#     "total_failures": 2,
#     "total_rejections": 0,
#     "config": {...}
# }

# Manual reset (for operations)
breaker.reset()
```

---

## Degradation Modes

### Retrieval Service Degradation

The retrieval service supports five degradation modes based on component health:

| Mode | Qdrant | OpenSearch | Reranker | Description |
|------|--------|------------|----------|-------------|
| `HYBRID_FULL` | ✓ | ✓ | ✓ | All components healthy (default) |
| `SEMANTIC_ONLY` | ✓ | ✗ | ✓ | OpenSearch down, use Qdrant only |
| `KEYWORD_ONLY` | ✗ | ✓ | ✓ | Qdrant down, use OpenSearch only |
| `HYBRID_NO_RERANK` | ✓ | ✓ | ✗ | Reranker down, skip reranking |
| `MINIMAL` | ✗ | ✗ | * | Both search backends down |

### Mode Selection Logic

```python
# services/retrieval/resilience/degradation.py

def get_current_mode(self) -> DegradationMode:
    """Determine current degradation mode from circuit states."""
    qdrant_ok = self.qdrant_breaker.state != CircuitState.OPEN
    opensearch_ok = self.opensearch_breaker.state != CircuitState.OPEN
    reranker_ok = self.reranker_breaker.state != CircuitState.OPEN

    if qdrant_ok and opensearch_ok and reranker_ok:
        return DegradationMode.HYBRID_FULL

    if not qdrant_ok and not opensearch_ok:
        return DegradationMode.MINIMAL

    if not qdrant_ok:
        return DegradationMode.KEYWORD_ONLY

    if not opensearch_ok:
        return DegradationMode.SEMANTIC_ONLY

    if not reranker_ok:
        return DegradationMode.HYBRID_NO_RERANK

    return DegradationMode.HYBRID_FULL
```

### Health Endpoint Enhancement

The `/health` endpoint includes degradation status:

```bash
curl http://localhost:8002/health
```

**Response (Healthy):**

```json
{
  "status": "healthy",
  "service": "retrieval-service",
  "version": "1.0.0",
  "degradation_level": "hybrid_full",
  "components": {
    "qdrant": {
      "status": "healthy",
      "circuit_state": "closed",
      "latency_ms": 5
    },
    "opensearch": {
      "status": "healthy",
      "circuit_state": "closed",
      "latency_ms": 8
    },
    "reranker": {
      "status": "healthy",
      "circuit_state": "closed",
      "latency_ms": 15
    }
  },
  "capabilities": {
    "semantic_search": true,
    "keyword_search": true,
    "reranking": true,
    "hybrid_search": true
  }
}
```

**Response (Degraded):**

```json
{
  "status": "degraded",
  "service": "retrieval-service",
  "version": "1.0.0",
  "degradation_level": "semantic_only",
  "components": {
    "qdrant": {
      "status": "healthy",
      "circuit_state": "closed",
      "latency_ms": 5
    },
    "opensearch": {
      "status": "unhealthy",
      "circuit_state": "open",
      "latency_ms": null
    },
    "reranker": {
      "status": "healthy",
      "circuit_state": "closed",
      "latency_ms": 15
    }
  },
  "capabilities": {
    "semantic_search": true,
    "keyword_search": false,
    "reranking": true,
    "hybrid_search": false
  }
}
```

---

## Cross-Service Degradation Propagation

Degradation information flows from the retrieval service to the orchestrator, enabling appropriate user-facing adjustments.

### Retrieval Response Schema

Search responses include a `degradation` field:

```json
{
  "results": [...],
  "total_results": 10,
  "degradation": {
    "level": "degraded",
    "mode": "semantic_only",
    "components": [
      {"name": "qdrant", "available": true, "circuit_state": "closed"},
      {"name": "opensearch", "available": false, "circuit_state": "open"},
      {"name": "reranker", "available": true, "circuit_state": "closed"}
    ],
    "message": "Keyword search unavailable, using semantic search only"
  },
  "metrics": {...}
}
```

### Orchestrator Handling

The orchestrator tracks degradation in its workflow state:

```python
# services/orchestrator/workflow/state.py

class RetrievalQuality(TypedDict):
    """Quality information from retrieval."""
    degradation_level: Literal["normal", "degraded", "minimal"]
    mode: str
    components_used: list[str]
    components_skipped: list[str]

class RAGState(TypedDict, total=False):
    # ... existing fields ...

    # Retrieval quality tracking
    retrieval_quality: RetrievalQuality
    context_quality: Literal["full", "partial", "minimal"]
    fallbacks_used: list[str]
```

### Prompt Adjustments

The orchestrator adjusts prompts based on degradation:

| Mode | Disclaimer Added to System Prompt |
|------|-----------------------------------|
| `SEMANTIC_ONLY` | "Note: The search results were obtained using semantic similarity only. Keyword matching was unavailable, so some exact term matches may be missing." |
| `KEYWORD_ONLY` | "Note: The search results were obtained using keyword matching only. Semantic search was unavailable, so conceptually similar content may be missing." |
| `HYBRID_NO_RERANK` | "Note: Search results were not reranked for relevance. Results may not be in optimal order." |
| `MINIMAL` | "IMPORTANT: Search capabilities are significantly degraded. The context provided may be incomplete or less relevant than usual." |

### Streaming Events

Streaming responses include degradation metadata:

```json
{
  "event": "metadata",
  "request_id": "req-uuid",
  "degradation": {
    "level": "degraded",
    "mode": "semantic_only",
    "message": "Using semantic search only"
  },
  "quality_indicator": "partial"
}
```

---

## Timeout & Retry Policies

### Timeout Cascade

All timeouts are centralized in `services/shared/config/timeouts.py`. Inner timeouts must be shorter than outer timeouts.

```
RAG E2E (30s)
├── Retrieval Total (15s)
│   ├── Embedding (5s)
│   ├── Qdrant (3s) ──┐
│   ├── OpenSearch (3s)├── Parallel
│   └── Reranker (8s)
└── LLM (25s)

Ingestion Document (5min)
├── Parsing (60s)
├── Embedding Batch (30s)
├── Qdrant Upsert (10s)
└── OpenSearch Index (10s)
```

**Standard Values:**

| Operation | Timeout | Retries | Environment Variable |
|-----------|---------|---------|---------------------|
| **Retrieval Service** ||||
| Embedding request | 5000ms | 2 | `RETRIEVAL_EMBEDDING_TIMEOUT_MS` |
| Qdrant query | 3000ms | 1 | `RETRIEVAL_QDRANT_TIMEOUT_MS` |
| OpenSearch query | 3000ms | 1 | `RETRIEVAL_OPENSEARCH_TIMEOUT_MS` |
| Reranker batch | 8000ms | 1 | `RETRIEVAL_RERANKER_TIMEOUT_MS` |
| Retrieval total | 15000ms | 0 | `RETRIEVAL_TOTAL_TIMEOUT_MS` |
| **Orchestrator Service** ||||
| Retrieval call | 20000ms | 1 | `ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS` |
| LLM generation | 25000ms | 0 | `ORCHESTRATOR_LLM_TIMEOUT_MS` |
| RAG total | 30000ms | 0 | `ORCHESTRATOR_TOTAL_TIMEOUT_MS` |
| **Ingestion Service** ||||
| Document parsing | 60000ms | 0 | `INGESTION_PARSING_TIMEOUT_MS` |
| Embedding batch | 30000ms | 2 | `INGESTION_EMBEDDING_TIMEOUT_MS` |
| Qdrant upsert | 10000ms | 2 | `INGESTION_QDRANT_UPSERT_TIMEOUT_MS` |
| OpenSearch index | 10000ms | 2 | `INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS` |
| Document total | 300000ms | 3 | `INGESTION_DOCUMENT_TIMEOUT_MS` |

### Retry Behavior

```python
from shared.config.timeouts import RETRIEVAL_QDRANT_TIMEOUT
from shared.resilience.retry import with_retry, retry_on_timeout

# Functional approach
result = await with_retry(
    qdrant_client.search,
    RETRIEVAL_QDRANT_TIMEOUT,
    "qdrant_search",
    collection="documents",
    query_vector=embedding
)

# Decorator approach
@retry_on_timeout(RETRIEVAL_QDRANT_TIMEOUT, "qdrant_search")
async def search_qdrant(collection: str, query_vector: list[float]):
    return await qdrant_client.search(collection, query_vector)
```

**Retry Policy:**

- **Idempotent operations** (search, embedding): Retry with exponential backoff
- **Non-idempotent operations** (LLM generation): No retry
- **Backoff formula:** `min(base_ms * 2^attempt, max_ms)` with ±25% jitter

### Timeout Validation

At service startup, timeout cascade is validated:

```python
from shared.config.validation import validate_on_startup

# Called during FastAPI lifespan startup
validate_on_startup(fail_fast=True)
```

**Validation Rules:**

1. `max(retrieval inner timeouts) < retrieval_total`
2. `orchestrator_retrieval < orchestrator_total`
3. `retrieval_total < orchestrator_retrieval`
4. `max(ingestion inner timeouts) < ingestion_document`

---

## Prometheus Metrics

### Circuit Breaker Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `retrieval_circuit_breaker_state` | Gauge | `component` | Circuit state (0=closed, 1=open, 2=half_open) |
| `retrieval_circuit_breaker_failures_total` | Counter | `component` | Total failures recorded |
| `retrieval_circuit_breaker_rejections_total` | Counter | `component` | Requests rejected due to open circuit |

### Degradation Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `retrieval_degradation_mode` | Gauge | `mode` | Current mode (1 = active) |
| `retrieval_degraded_searches_total` | Counter | `mode` | Searches in degraded mode |

### Example Queries

```promql
# Circuit breaker state by component
retrieval_circuit_breaker_state

# Degraded search rate (last 5 minutes)
sum(rate(retrieval_degraded_searches_total[5m])) by (mode)

# Circuit rejections rate
sum(rate(retrieval_circuit_breaker_rejections_total[5m])) by (component)
```

---

## Operational Guide

### Monitoring Degradation

1. **Grafana Dashboard**: Check the "Retrieval Service" dashboard for:
   - Circuit breaker state visualization
   - Degradation mode over time
   - Component latency percentiles

2. **Alerts**: Configure alerts for:
   - Circuit breaker opening: `retrieval_circuit_breaker_state{} == 1`
   - Extended degradation: `retrieval_degradation_mode{mode!="hybrid_full"} == 1` for > 5 minutes

### Manual Recovery

**Reset a circuit breaker:**

```bash
# Via admin API (if exposed)
curl -X POST http://localhost:8002/admin/circuits/qdrant/reset

# Or restart the service
kubectl rollout restart deployment/retrieval-service -n rag-pipeline
```

**Force component health check:**

```bash
curl http://localhost:8002/health?force_check=true
```

### Tuning Recommendations

| Scenario | Adjustment |
|----------|------------|
| Frequent false opens | Increase `failure_threshold` (e.g., 5 → 10) |
| Slow recovery detection | Decrease `recovery_timeout` (e.g., 30s → 15s) |
| Flapping circuit | Increase `half_open_max_calls` (e.g., 3 → 5) |
| High latency operations | Increase individual timeouts |

### Troubleshooting

**Circuit stuck open:**

1. Check component health: `curl http://localhost:8002/health`
2. Review logs for failure patterns: `kubectl logs deployment/retrieval-service | grep circuit`
3. Verify network connectivity to backend services
4. Consider manual reset if component is healthy

**Unexpected degradation mode:**

1. Verify all circuits are closed
2. Check for intermittent failures triggering circuit opens
3. Review timeout values vs actual latencies

---

## Related Documentation

- [Retrieval Service](retrieval-service/README.md)
- [Orchestrator Service](orchestrator-service/README.md)
- [Health Check Specification](health-check-specification.md)
- [Observability](observability/README.md)
