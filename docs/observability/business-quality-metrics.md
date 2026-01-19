# Business & Quality Metrics

> **Status:** Production Ready
> **Implemented:** US-10.3.3
> **Last Updated:** January 2026

## Overview

Business-level metrics for RAG quality, user feedback correlation, and query success rates enable product-level visibility and improvement. These metrics complement technical metrics (latency, errors) with business KPIs for product decisions.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Query Metrics](#query-metrics)
3. [Feedback Metrics](#feedback-metrics)
4. [Quality Indicators](#quality-indicators)
5. [Degradation Metrics](#degradation-metrics)
6. [Metrics Collector](#metrics-collector)
7. [Feedback API](#feedback-api)
8. [Grafana Dashboard](#grafana-dashboard)
9. [Configuration](#configuration)
10. [Implementation Reference](#implementation-reference)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         RAG Query Flow                                   │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    RAG Metrics Collector                                 │
│  • Query metrics (success, latency, strategy)                           │
│  • Component timing breakdown                                            │
│  • Context relevance scores                                              │
│  • Citation counts                                                       │
│  • Degradation tracking                                                  │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│   Prometheus    │        │   PostgreSQL    │        │   Grafana       │
│   Time Series   │        │   Feedback DB   │        │   Dashboards    │
└─────────────────┘        └─────────────────┘        └─────────────────┘
```

---

## Query Metrics

### Core Query Counters

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_queries_total` | Counter | strategy, rag_used, degraded, tenant_id, status | Total RAG queries processed |
| `rag_query_success_rate` | Gauge | tenant_id | Rolling success rate (calculated) |

### Latency Metrics

| Metric | Type | Labels | Buckets | Description |
|--------|------|--------|---------|-------------|
| `rag_e2e_latency_seconds` | Histogram | strategy, tenant_tier, degraded | 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0 | End-to-end RAG query latency |
| `rag_component_latency_seconds` | Histogram | component | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0 | Per-component latency breakdown |

### Component Labels

The `component` label tracks timing for each stage:

| Component | Description |
|-----------|-------------|
| `routing` | Query routing decision |
| `retrieval` | Document retrieval |
| `prompt` | Prompt building |
| `generation` | LLM generation |
| `validation` | Response validation |

### Usage Example

```python
from shared.observability.metrics.business import (
    rag_queries_total,
    rag_e2e_latency,
    rag_component_latency,
)

# Record query completion
rag_queries_total.labels(
    strategy="hybrid",
    rag_used="true",
    degraded="false",
    tenant_id="acme-corp",
    status="success",
).inc()

# Record E2E latency
rag_e2e_latency.labels(
    strategy="hybrid",
    tenant_tier="enterprise",
    degraded="false",
).observe(1.5)  # 1.5 seconds

# Record component timing
rag_component_latency.labels(component="retrieval").observe(0.3)
rag_component_latency.labels(component="generation").observe(1.0)
```

---

## Feedback Metrics

### Feedback Counters

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_feedback_total` | Counter | rating, tenant_id | User feedback on RAG responses |
| `rag_feedback_score` | Gauge | tenant_id | Rolling feedback score (positive/total) |

### Rating Values

| Rating | Description |
|--------|-------------|
| `positive` | User indicated response was helpful |
| `negative` | User indicated response was not helpful |
| `neutral` | User provided feedback without clear rating |

### Feedback Categories

Optional categories can be associated with feedback:

- `accurate` - Response was factually correct
- `relevant` - Response addressed the question
- `well-cited` - Response had good source citations
- `irrelevant` - Response didn't address the question
- `outdated` - Response contained stale information
- `incomplete` - Response was missing information

---

## Quality Indicators

### Context Relevance

| Metric | Type | Labels | Buckets | Description |
|--------|------|--------|---------|-------------|
| `rag_context_relevance_score` | Histogram | tenant_id | 0.1 to 1.0 (0.1 steps) | Relevance score from reranker |

Higher scores indicate retrieved context is more relevant to the query.

### Citation Metrics

| Metric | Type | Labels | Buckets | Description |
|--------|------|--------|---------|-------------|
| `rag_citations_per_response` | Histogram | tenant_id | 0-10 | Number of citations in response |

Tracks how well-sourced responses are.

### Retrieval Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `retrieval_result_count` | Histogram | search_type | Documents retrieved per query |
| `retrieval_empty_results_total` | Counter | tenant_id, query_type | Queries with zero results |

---

## Degradation Metrics

### Fallback Tracking

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_fallback_usage_total` | Counter | fallback_type, tenant_id | Times a fallback was used |
| `rag_degraded_queries_total` | Counter | degradation_mode, tenant_id | Queries served in degraded mode |

### Fallback Types

| Type | Description |
|------|-------------|
| `cache_hit` | Served from response cache |
| `no_retrieval` | Direct LLM without retrieval |
| `degraded_retrieval` | Partial retrieval (semantic-only or keyword-only) |
| `stale_cache` | Served from expired cache |

### Degradation Modes

| Mode | Description |
|------|-------------|
| `semantic_only` | Vector search only (OpenSearch unavailable) |
| `keyword_only` | Keyword search only (Qdrant unavailable) |
| `no_rerank` | Skipped reranking |
| `reduced_context` | Fewer documents in context |

---

## Metrics Collector

### QueryMetrics Dataclass

```python
from dataclasses import dataclass

@dataclass
class QueryMetrics:
    """Metrics collected during a RAG query."""
    request_id: str
    tenant_id: str
    tenant_tier: str
    strategy: str
    rag_used: bool
    degraded: bool
    degradation_mode: str | None
    fallbacks_used: list[str]
    e2e_latency_ms: float
    component_timings: dict[str, float]
    context_relevance_score: float | None
    citation_count: int
    status: str  # success, error
```

### RAGMetricsCollector

```python
from shared.observability.metrics.business import RAGMetricsCollector, QueryMetrics

collector = RAGMetricsCollector()

# After query completion
metrics = QueryMetrics(
    request_id="req-123",
    tenant_id="acme-corp",
    tenant_tier="enterprise",
    strategy="hybrid",
    rag_used=True,
    degraded=False,
    degradation_mode=None,
    fallbacks_used=[],
    e2e_latency_ms=1500,
    component_timings={
        "routing": 10,
        "retrieval": 300,
        "prompt": 20,
        "generation": 1100,
        "validation": 70,
    },
    context_relevance_score=0.85,
    citation_count=3,
    status="success",
)

collector.record_query(metrics)
```

### Integration with Orchestrator

```python
# In orchestrator workflow
import time
from shared.observability.metrics.business import RAGMetricsCollector, QueryMetrics

collector = RAGMetricsCollector()

async def process_query(state: RAGState) -> RAGState:
    start_time = time.time()
    component_timings = {}

    # Track each component
    routing_start = time.time()
    state = await routing_node(state)
    component_timings["routing"] = (time.time() - routing_start) * 1000

    retrieval_start = time.time()
    state = await retrieval_node(state)
    component_timings["retrieval"] = (time.time() - retrieval_start) * 1000

    # ... other components ...

    # Record metrics
    collector.record_query(QueryMetrics(
        request_id=state["request_id"],
        tenant_id=state["tenant_id"],
        tenant_tier=state.get("tenant_tier", "standard"),
        strategy=state["strategy"],
        rag_used=state.get("rag_used", True),
        degraded=state.get("degraded", False),
        degradation_mode=state.get("degradation_mode"),
        fallbacks_used=state.get("fallbacks_used", []),
        e2e_latency_ms=(time.time() - start_time) * 1000,
        component_timings=component_timings,
        context_relevance_score=state.get("context_quality"),
        citation_count=len(state.get("citations", [])),
        status="success" if not state.get("error") else "error",
    ))

    return state
```

---

## Feedback API

### Endpoint

```
POST /api/v1/feedback
```

### Request Schema

```python
class FeedbackRequest(BaseModel):
    request_id: str  # Correlation to original query
    rating: Literal["positive", "negative", "neutral"]
    comment: str | None = None
    categories: list[str] | None = None  # e.g., ["accurate", "well-cited"]
```

### Response Schema

```python
class FeedbackResponse(BaseModel):
    status: str  # "received"
    request_id: str
```

### Example Request

```bash
curl -X POST http://localhost:8003/api/v1/feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "rating": "positive",
    "comment": "Very helpful response!",
    "categories": ["accurate", "well-cited"]
  }'
```

### Database Model

```python
class QueryFeedback(Base):
    __tablename__ = "query_feedback"

    id: str                    # UUID primary key
    request_id: str            # Correlation to query
    tenant_id: str             # Tenant context
    rating: str                # positive/negative/neutral
    comment: str | None        # Optional comment
    categories: list | None    # JSON array of categories
    created_at: datetime       # Timestamp
```

### Rolling Score Calculation

The `rag_feedback_score` gauge is calculated from the last 100 feedback entries:

```python
async def _update_feedback_score(tenant_id: str, session: AsyncSession):
    result = await session.execute(
        select(QueryFeedback.rating)
        .where(QueryFeedback.tenant_id == tenant_id)
        .order_by(QueryFeedback.created_at.desc())
        .limit(100)
    )
    ratings = result.scalars().all()

    if ratings:
        positive = sum(1 for r in ratings if r == "positive")
        score = positive / len(ratings)
        rag_feedback_score.labels(tenant_id=tenant_id).set(score)
```

---

## Grafana Dashboard

### RAG Quality Overview Dashboard

#### Panels

| Panel | Type | Query |
|-------|------|-------|
| Query Volume | Stat | `sum(rate(rag_queries_total[5m]))` |
| Success Rate | Gauge | `sum(rate(rag_queries_total{status='success'}[1h])) / sum(rate(rag_queries_total[1h])) * 100` |
| E2E Latency (p95) | Time series | `histogram_quantile(0.95, sum(rate(rag_e2e_latency_seconds_bucket[5m])) by (le, strategy))` |
| Component Latency | Time series | `histogram_quantile(0.95, sum(rate(rag_component_latency_seconds_bucket[5m])) by (le, component))` |
| Feedback Score | Time series | `rag_feedback_score` |
| Degradation Events | Time series | `sum(rate(rag_degraded_queries_total[5m])) by (degradation_mode)` |
| Fallback Usage | Pie chart | `sum(rag_fallback_usage_total) by (fallback_type)` |
| Context Relevance | Heatmap | `sum(rate(rag_context_relevance_score_bucket[5m])) by (le)` |

#### Thresholds

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Success Rate | > 95% | 90-95% | < 90% |
| Feedback Score | > 0.8 | 0.5-0.8 | < 0.5 |
| E2E Latency p95 | < 2s | 2-5s | > 5s |

### Dashboard JSON Location

```
services/shared/observability/grafana/provisioning/dashboards/rag-quality.json
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `METRICS_ENABLED` | Enable business metrics collection | `true` |
| `FEEDBACK_ENABLED` | Enable feedback API | `true` |
| `FEEDBACK_ROLLING_WINDOW` | Entries for rolling score | `100` |

### Metric Labels

To avoid high cardinality, consider:

1. **Tenant ID**: Only include for multi-tenant deployments
2. **User ID**: Never include raw user IDs, use hashed values
3. **Query Text**: Never include in metrics (use logs instead)

---

## Implementation Reference

| Component | Location |
|-----------|----------|
| Metric definitions | `services/orchestrator/observability/business_metrics.py` |
| Metrics collector | `services/orchestrator/workflow/metrics_collector.py` |
| Feedback API | `services/orchestrator/api/feedback.py` |
| Feedback model | `services/shared/database/models/feedback.py` |
| Grafana dashboard | `services/shared/observability/grafana/provisioning/dashboards/rag-quality.json` |
| Tests | `services/orchestrator/tests/observability/test_business_metrics.py` |

---

## Related Documentation

- [SLO Definitions & Alerts](./slo-definitions-alerts.md) - SLOs built on these metrics
- [Observability Overview](./README.md) - Complete observability stack
- [Correlation ID Propagation](./correlation-id-propagation.md) - Request correlation for feedback
