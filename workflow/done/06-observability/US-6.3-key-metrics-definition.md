# US-6.3: Key Metrics Definition

> **Story ID:** US-6.3  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-6.2 (Prometheus Metrics)

## User Story

**As a** SRE  
**I want** well-defined metrics with semantic meaning  
**So that** I can create meaningful dashboards and alerts

## Context

Consistent metric naming and semantics are crucial for effective observability. This story defines the canonical metrics for the RAG pipeline, following Prometheus naming conventions and establishing clear definitions for each metric's meaning, labels, and use cases.

Metrics should answer:
- **Latency**: How long do operations take?
- **Traffic**: How many requests are we handling?
- **Errors**: What's our error rate?
- **Saturation**: How full are our resources?

This follows the RED (Rate, Errors, Duration) and USE (Utilization, Saturation, Errors) methodologies.

## Technical Requirements

### Directory Structure

```
observability/
├── metrics/
│   ├── definitions/
│   │   ├── __init__.py
│   │   ├── query_metrics.py       # Query/request metrics
│   │   ├── retrieval_metrics.py   # Retrieval metrics
│   │   ├── llm_metrics.py         # LLM metrics
│   │   ├── ingestion_metrics.py   # Ingestion metrics
│   │   ├── cache_metrics.py       # Cache metrics
│   │   └── system_metrics.py      # System/resource metrics
│   ├── sli.py                     # SLI calculations
│   ├── slo.py                     # SLO definitions
│   └── constants.py               # Metric name constants
└── docs/
    └── metrics-catalog.md         # Human-readable catalog
```

### Metric Naming Conventions

```python
"""
Prometheus Metric Naming Conventions for RAG Pipeline.

Format: rag_<subsystem>_<metric_name>_<unit>

Rules:
1. Use snake_case
2. Include unit suffix (_seconds, _bytes, _total, _ratio)
3. Use _total suffix for counters
4. Use base units (seconds not milliseconds, bytes not megabytes)
5. Group related metrics with common prefix

Examples:
- rag_query_duration_seconds (histogram)
- rag_llm_tokens_total (counter)
- rag_cache_hit_ratio (gauge)
"""

# Metric name constants to ensure consistency
class MetricNames:
    """Canonical metric names for the RAG pipeline."""
    
    # Query/Request Metrics
    QUERY_DURATION = "rag_query_duration_seconds"
    QUERY_TOTAL = "rag_query_total"
    QUERY_ACTIVE = "rag_query_active"
    QUERY_SIZE_BYTES = "rag_query_size_bytes"
    
    # Retrieval Metrics
    RETRIEVAL_DURATION = "rag_retrieval_duration_seconds"
    RETRIEVAL_RESULT_COUNT = "rag_retrieval_result_count"
    RETRIEVAL_SCORE = "rag_retrieval_score"
    RETRIEVAL_TOTAL = "rag_retrieval_total"
    
    # Embedding Metrics
    EMBEDDING_DURATION = "rag_embedding_duration_seconds"
    EMBEDDING_TOKENS = "rag_embedding_tokens_total"
    EMBEDDING_BATCH_SIZE = "rag_embedding_batch_size"
    EMBEDDING_REQUESTS = "rag_embedding_requests_total"
    
    # LLM Metrics
    LLM_DURATION = "rag_llm_duration_seconds"
    LLM_TOKENS = "rag_llm_tokens_total"
    LLM_TTFT = "rag_llm_time_to_first_token_seconds"
    LLM_REQUESTS = "rag_llm_requests_total"
    LLM_PROMPT_TOKENS = "rag_llm_prompt_tokens"
    LLM_COMPLETION_TOKENS = "rag_llm_completion_tokens"
    
    # Ingestion Metrics
    DOCUMENTS_INGESTED = "rag_documents_ingested_total"
    DOCUMENT_BYTES = "rag_document_bytes_total"
    CHUNKS_CREATED = "rag_chunks_created_total"
    INGESTION_DURATION = "rag_ingestion_duration_seconds"
    INGESTION_QUEUE_SIZE = "rag_ingestion_queue_size"
    
    # Cache Metrics
    CACHE_HITS = "rag_cache_hits_total"
    CACHE_MISSES = "rag_cache_misses_total"
    CACHE_SIZE_BYTES = "rag_cache_size_bytes"
    CACHE_LATENCY = "rag_cache_latency_seconds"
    CACHE_EVICTIONS = "rag_cache_evictions_total"
    
    # System Metrics
    DB_CONNECTIONS_ACTIVE = "rag_db_connections_active"
    DB_CONNECTIONS_IDLE = "rag_db_connections_idle"
    VECTOR_DB_POINTS = "rag_vector_db_points"
    VECTOR_DB_COLLECTIONS = "rag_vector_db_collections"
```

### Metric Definitions Catalog

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


class MetricType(str, Enum):
    """Prometheus metric types."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class MetricUnit(str, Enum):
    """Standard metric units."""
    SECONDS = "seconds"
    BYTES = "bytes"
    TOTAL = "total"  # For counters
    RATIO = "ratio"
    COUNT = "count"  # For histograms of counts


@dataclass
class MetricDefinition:
    """
    Definition of a single metric.
    
    Provides full documentation including:
    - Name and type
    - Labels and their meanings
    - Description and use cases
    - Example queries
    """
    name: str
    type: MetricType
    unit: MetricUnit
    description: str
    labels: List[str]
    label_descriptions: Dict[str, str] = field(default_factory=dict)
    use_cases: List[str] = field(default_factory=list)
    example_queries: List[str] = field(default_factory=list)
    buckets: Optional[tuple] = None  # For histograms
    slo_relevant: bool = False
    

# ============================================
# QUERY/REQUEST METRICS
# ============================================

QUERY_DURATION = MetricDefinition(
    name="rag_query_duration_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="End-to-end query duration from request receipt to response sent",
    labels=["service", "endpoint", "method", "status", "tenant_id"],
    label_descriptions={
        "service": "Service name (orchestrator, retrieval, etc.)",
        "endpoint": "API endpoint path pattern",
        "method": "HTTP method (GET, POST)",
        "status": "Response status (success, error, client_error)",
        "tenant_id": "Tenant identifier for multi-tenant tracking",
    },
    use_cases=[
        "Calculate p50/p95/p99 latency",
        "Track latency by tenant",
        "Identify slow endpoints",
        "SLO compliance tracking",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le))',
        'sum(rate(rag_query_duration_seconds_sum[5m])) / sum(rate(rag_query_duration_seconds_count[5m]))',
    ],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    slo_relevant=True,
)

QUERY_TOTAL = MetricDefinition(
    name="rag_query_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total number of queries processed",
    labels=["service", "endpoint", "method", "status", "tenant_id"],
    label_descriptions={
        "service": "Service name",
        "endpoint": "API endpoint path pattern",
        "method": "HTTP method",
        "status": "Response status (success, error, client_error)",
        "tenant_id": "Tenant identifier",
    },
    use_cases=[
        "Calculate request rate",
        "Track error rate",
        "Traffic analysis by tenant",
        "Capacity planning",
    ],
    example_queries=[
        'sum(rate(rag_query_total[5m])) by (service)',
        'sum(rate(rag_query_total{status="error"}[5m])) / sum(rate(rag_query_total[5m]))',
    ],
    slo_relevant=True,
)

QUERY_ACTIVE = MetricDefinition(
    name="rag_query_active",
    type=MetricType.GAUGE,
    unit=MetricUnit.COUNT,
    description="Number of currently active queries being processed",
    labels=["service"],
    label_descriptions={
        "service": "Service name",
    },
    use_cases=[
        "Detect saturation",
        "Concurrency monitoring",
        "Load balancing decisions",
    ],
    example_queries=[
        'max(rag_query_active) by (service)',
    ],
)


# ============================================
# RETRIEVAL METRICS
# ============================================

RETRIEVAL_DURATION = MetricDefinition(
    name="rag_retrieval_duration_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Duration of document retrieval operations",
    labels=["strategy", "index", "tenant_id"],
    label_descriptions={
        "strategy": "Retrieval strategy (vector, keyword, hybrid)",
        "index": "Index/collection name being searched",
        "tenant_id": "Tenant identifier",
    },
    use_cases=[
        "Compare retrieval strategy performance",
        "Identify slow collections",
        "Optimize search configuration",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_retrieval_duration_seconds_bucket[5m])) by (le, strategy))',
    ],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0),
    slo_relevant=True,
)

RETRIEVAL_RESULT_COUNT = MetricDefinition(
    name="rag_retrieval_result_count",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.COUNT,
    description="Number of documents returned per retrieval query",
    labels=["strategy", "index"],
    label_descriptions={
        "strategy": "Retrieval strategy used",
        "index": "Index/collection searched",
    },
    use_cases=[
        "Analyze retrieval effectiveness",
        "Detect empty result queries",
        "Tune top_k settings",
    ],
    example_queries=[
        'histogram_quantile(0.50, sum(rate(rag_retrieval_result_count_bucket[1h])) by (le, strategy))',
        'sum(rate(rag_retrieval_result_count_bucket{le="0"}[1h])) / sum(rate(rag_retrieval_result_count_count[1h]))',
    ],
    buckets=(0, 1, 2, 3, 5, 10, 15, 20, 50, 100),
)

RETRIEVAL_SCORE = MetricDefinition(
    name="rag_retrieval_score",
    type=MetricType.SUMMARY,
    unit=MetricUnit.RATIO,
    description="Similarity score distribution of retrieved documents",
    labels=["strategy", "position"],
    label_descriptions={
        "strategy": "Retrieval strategy used",
        "position": "Result position (top1, top3, top5, top10)",
    },
    use_cases=[
        "Monitor retrieval quality",
        "Detect score degradation",
        "Compare strategy effectiveness",
    ],
    example_queries=[
        'avg(rag_retrieval_score{position="top1"}) by (strategy)',
    ],
)


# ============================================
# EMBEDDING METRICS
# ============================================

EMBEDDING_DURATION = MetricDefinition(
    name="rag_embedding_duration_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Duration of embedding generation",
    labels=["model", "batch_size_bucket", "operation"],
    label_descriptions={
        "model": "Embedding model name (e.g., text-embedding-3-small)",
        "batch_size_bucket": "Batch size bucket (1, 8, 16, 32, 64+)",
        "operation": "Operation type (query, document)",
    },
    use_cases=[
        "Compare model performance",
        "Optimize batch sizes",
        "Latency analysis",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_embedding_duration_seconds_bucket[5m])) by (le, model))',
    ],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

EMBEDDING_TOKENS = MetricDefinition(
    name="rag_embedding_tokens_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total tokens processed for embeddings",
    labels=["model", "operation"],
    label_descriptions={
        "model": "Embedding model name",
        "operation": "Operation type (query, document)",
    },
    use_cases=[
        "Track embedding costs",
        "Analyze token throughput",
        "Capacity planning",
    ],
    example_queries=[
        'sum(rate(rag_embedding_tokens_total[1h])) by (model)',
    ],
)


# ============================================
# LLM METRICS
# ============================================

LLM_DURATION = MetricDefinition(
    name="rag_llm_duration_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Total LLM inference duration (time to complete)",
    labels=["model", "provider", "operation"],
    label_descriptions={
        "model": "LLM model name (e.g., gpt-4, llama-3-70b)",
        "provider": "LLM provider (openai, anthropic, vllm)",
        "operation": "Operation type (completion, chat)",
    },
    use_cases=[
        "Compare model latency",
        "Track provider performance",
        "SLO compliance",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le, model))',
    ],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    slo_relevant=True,
)

LLM_TTFT = MetricDefinition(
    name="rag_llm_time_to_first_token_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Time from request to first token (streaming)",
    labels=["model", "provider"],
    label_descriptions={
        "model": "LLM model name",
        "provider": "LLM provider",
    },
    use_cases=[
        "Measure perceived latency",
        "Streaming performance",
        "User experience tracking",
    ],
    example_queries=[
        'histogram_quantile(0.50, sum(rate(rag_llm_time_to_first_token_seconds_bucket[5m])) by (le, model))',
    ],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    slo_relevant=True,
)

LLM_TOKENS = MetricDefinition(
    name="rag_llm_tokens_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total LLM tokens used",
    labels=["model", "provider", "token_type", "tenant_id"],
    label_descriptions={
        "model": "LLM model name",
        "provider": "LLM provider",
        "token_type": "Token type (input, output)",
        "tenant_id": "Tenant identifier",
    },
    use_cases=[
        "Cost tracking",
        "Usage analytics per tenant",
        "Quota enforcement",
    ],
    example_queries=[
        'sum(increase(rag_llm_tokens_total[24h])) by (model, token_type)',
        'sum(rate(rag_llm_tokens_total[5m])) by (tenant_id)',
    ],
)

LLM_PROMPT_TOKENS = MetricDefinition(
    name="rag_llm_prompt_tokens",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.COUNT,
    description="Distribution of prompt token counts per request",
    labels=["model"],
    label_descriptions={
        "model": "LLM model name",
    },
    use_cases=[
        "Analyze prompt sizes",
        "Detect context window issues",
        "Optimize prompt engineering",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_llm_prompt_tokens_bucket[1h])) by (le, model))',
    ],
    buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000),
)

LLM_REQUESTS = MetricDefinition(
    name="rag_llm_requests_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total LLM requests made",
    labels=["model", "provider", "status"],
    label_descriptions={
        "model": "LLM model name",
        "provider": "LLM provider",
        "status": "Response status (success, error, rate_limited)",
    },
    use_cases=[
        "Track request rate",
        "Monitor error rate by provider",
        "Rate limit detection",
    ],
    example_queries=[
        'sum(rate(rag_llm_requests_total{status="error"}[5m])) / sum(rate(rag_llm_requests_total[5m]))',
    ],
    slo_relevant=True,
)


# ============================================
# INGESTION METRICS
# ============================================

DOCUMENTS_INGESTED = MetricDefinition(
    name="rag_documents_ingested_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total documents ingested into the system",
    labels=["source_type", "status", "tenant_id"],
    label_descriptions={
        "source_type": "Document source type (pdf, html, docx, etc.)",
        "status": "Ingestion status (success, error, skipped)",
        "tenant_id": "Tenant identifier",
    },
    use_cases=[
        "Track ingestion volume",
        "Monitor failure rates by type",
        "Tenant usage tracking",
    ],
    example_queries=[
        'sum(increase(rag_documents_ingested_total[24h])) by (source_type)',
        'sum(rate(rag_documents_ingested_total{status="error"}[1h])) by (source_type)',
    ],
)

DOCUMENT_BYTES = MetricDefinition(
    name="rag_document_bytes_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.BYTES,
    description="Total bytes processed during ingestion",
    labels=["source_type", "tenant_id"],
    label_descriptions={
        "source_type": "Document source type",
        "tenant_id": "Tenant identifier",
    },
    use_cases=[
        "Track data throughput",
        "Storage cost estimation",
        "Capacity planning",
    ],
    example_queries=[
        'sum(rate(rag_document_bytes_total[1h])) by (source_type)',
    ],
)

CHUNKS_CREATED = MetricDefinition(
    name="rag_chunks_created_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total chunks created from documents",
    labels=["chunking_strategy", "source_type"],
    label_descriptions={
        "chunking_strategy": "Chunking strategy used (semantic, fixed, sentence)",
        "source_type": "Original document type",
    },
    use_cases=[
        "Analyze chunking effectiveness",
        "Storage planning",
        "Compare strategies",
    ],
    example_queries=[
        'sum(increase(rag_chunks_created_total[24h])) by (chunking_strategy)',
    ],
)

INGESTION_DURATION = MetricDefinition(
    name="rag_ingestion_duration_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Total duration to ingest a document",
    labels=["source_type", "stage"],
    label_descriptions={
        "source_type": "Document source type",
        "stage": "Processing stage (extraction, chunking, embedding, indexing)",
    },
    use_cases=[
        "Identify slow stages",
        "Compare document types",
        "Optimize pipeline",
    ],
    example_queries=[
        'histogram_quantile(0.95, sum(rate(rag_ingestion_duration_seconds_bucket[1h])) by (le, stage))',
    ],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

INGESTION_QUEUE_SIZE = MetricDefinition(
    name="rag_ingestion_queue_size",
    type=MetricType.GAUGE,
    unit=MetricUnit.COUNT,
    description="Current number of documents waiting in ingestion queue",
    labels=["queue", "priority"],
    label_descriptions={
        "queue": "Queue name",
        "priority": "Document priority (high, normal, low)",
    },
    use_cases=[
        "Monitor queue depth",
        "Detect backlog",
        "Scale workers",
    ],
    example_queries=[
        'sum(rag_ingestion_queue_size) by (queue)',
    ],
)


# ============================================
# CACHE METRICS
# ============================================

CACHE_HITS = MetricDefinition(
    name="rag_cache_hits_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total cache hits",
    labels=["cache_type", "key_prefix"],
    label_descriptions={
        "cache_type": "Type of cache (embedding, query, result)",
        "key_prefix": "Cache key prefix for categorization",
    },
    use_cases=[
        "Calculate hit ratio",
        "Analyze cache effectiveness",
        "Cost savings estimation",
    ],
    example_queries=[
        'sum(rate(rag_cache_hits_total[5m])) by (cache_type)',
    ],
)

CACHE_MISSES = MetricDefinition(
    name="rag_cache_misses_total",
    type=MetricType.COUNTER,
    unit=MetricUnit.TOTAL,
    description="Total cache misses",
    labels=["cache_type", "key_prefix"],
    label_descriptions={
        "cache_type": "Type of cache",
        "key_prefix": "Cache key prefix",
    },
    use_cases=[
        "Calculate hit ratio",
        "Identify cold spots",
        "Cache sizing",
    ],
    example_queries=[
        'sum(rate(rag_cache_misses_total[5m])) / (sum(rate(rag_cache_hits_total[5m])) + sum(rate(rag_cache_misses_total[5m])))',
    ],
)

CACHE_LATENCY = MetricDefinition(
    name="rag_cache_latency_seconds",
    type=MetricType.HISTOGRAM,
    unit=MetricUnit.SECONDS,
    description="Cache operation latency",
    labels=["cache_type", "operation"],
    label_descriptions={
        "cache_type": "Type of cache",
        "operation": "Cache operation (get, set, delete)",
    },
    use_cases=[
        "Monitor cache performance",
        "Detect Redis issues",
        "Compare cache backends",
    ],
    example_queries=[
        'histogram_quantile(0.99, sum(rate(rag_cache_latency_seconds_bucket[5m])) by (le, cache_type))',
    ],
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1),
)


# ============================================
# REGISTRY OF ALL METRICS
# ============================================

METRIC_CATALOG = {
    # Query metrics
    "query_duration": QUERY_DURATION,
    "query_total": QUERY_TOTAL,
    "query_active": QUERY_ACTIVE,
    
    # Retrieval metrics
    "retrieval_duration": RETRIEVAL_DURATION,
    "retrieval_result_count": RETRIEVAL_RESULT_COUNT,
    "retrieval_score": RETRIEVAL_SCORE,
    
    # Embedding metrics
    "embedding_duration": EMBEDDING_DURATION,
    "embedding_tokens": EMBEDDING_TOKENS,
    
    # LLM metrics
    "llm_duration": LLM_DURATION,
    "llm_ttft": LLM_TTFT,
    "llm_tokens": LLM_TOKENS,
    "llm_prompt_tokens": LLM_PROMPT_TOKENS,
    "llm_requests": LLM_REQUESTS,
    
    # Ingestion metrics
    "documents_ingested": DOCUMENTS_INGESTED,
    "document_bytes": DOCUMENT_BYTES,
    "chunks_created": CHUNKS_CREATED,
    "ingestion_duration": INGESTION_DURATION,
    "ingestion_queue_size": INGESTION_QUEUE_SIZE,
    
    # Cache metrics
    "cache_hits": CACHE_HITS,
    "cache_misses": CACHE_MISSES,
    "cache_latency": CACHE_LATENCY,
}


def get_slo_relevant_metrics() -> List[MetricDefinition]:
    """Get all metrics that are relevant for SLO tracking."""
    return [m for m in METRIC_CATALOG.values() if m.slo_relevant]


def generate_metrics_documentation() -> str:
    """Generate markdown documentation for all metrics."""
    lines = ["# RAG Pipeline Metrics Catalog\n"]
    
    # Group by category
    categories = {
        "Query/Request": ["query_duration", "query_total", "query_active"],
        "Retrieval": ["retrieval_duration", "retrieval_result_count", "retrieval_score"],
        "Embedding": ["embedding_duration", "embedding_tokens"],
        "LLM": ["llm_duration", "llm_ttft", "llm_tokens", "llm_prompt_tokens", "llm_requests"],
        "Ingestion": ["documents_ingested", "document_bytes", "chunks_created", "ingestion_duration", "ingestion_queue_size"],
        "Cache": ["cache_hits", "cache_misses", "cache_latency"],
    }
    
    for category, metric_keys in categories.items():
        lines.append(f"\n## {category} Metrics\n")
        
        for key in metric_keys:
            metric = METRIC_CATALOG[key]
            lines.append(f"### `{metric.name}`\n")
            lines.append(f"**Type:** {metric.type.value}\n")
            lines.append(f"**Unit:** {metric.unit.value}\n")
            lines.append(f"\n{metric.description}\n")
            
            lines.append("\n**Labels:**\n")
            for label in metric.labels:
                desc = metric.label_descriptions.get(label, "")
                lines.append(f"- `{label}`: {desc}\n")
            
            if metric.use_cases:
                lines.append("\n**Use Cases:**\n")
                for use_case in metric.use_cases:
                    lines.append(f"- {use_case}\n")
            
            if metric.example_queries:
                lines.append("\n**Example Queries:**\n```promql\n")
                for query in metric.example_queries:
                    lines.append(f"{query}\n")
                lines.append("```\n")
    
    return "".join(lines)
```

### SLI/SLO Definitions

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class SLOType(str, Enum):
    """Types of SLO targets."""
    LATENCY = "latency"
    AVAILABILITY = "availability"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"


@dataclass
class SLI:
    """
    Service Level Indicator definition.
    
    An SLI is a quantitative measure of some aspect of the
    service that can be measured and compared against an SLO.
    """
    name: str
    description: str
    metric_query: str
    unit: str
    good_events_query: Optional[str] = None
    total_events_query: Optional[str] = None


@dataclass
class SLO:
    """
    Service Level Objective definition.
    
    An SLO is a target value or range of values for an SLI.
    """
    name: str
    sli: SLI
    target: float
    window: str  # e.g., "30d"
    slo_type: SLOType
    description: str
    error_budget_calculation: str
    burn_rate_alerts: List[dict]


# SLI Definitions
QUERY_LATENCY_SLI = SLI(
    name="query_latency",
    description="Proportion of queries completed within 2 seconds",
    metric_query="""
        sum(rate(rag_query_duration_seconds_bucket{le="2"}[{{window}}]))
        / sum(rate(rag_query_duration_seconds_count[{{window}}]))
    """,
    unit="ratio",
    good_events_query='sum(rate(rag_query_duration_seconds_bucket{le="2"}[{{window}}]))',
    total_events_query='sum(rate(rag_query_duration_seconds_count[{{window}}]))',
)

AVAILABILITY_SLI = SLI(
    name="availability",
    description="Proportion of successful requests",
    metric_query="""
        1 - (
            sum(rate(rag_query_total{status="error"}[{{window}}]))
            / sum(rate(rag_query_total[{{window}}]))
        )
    """,
    unit="ratio",
    good_events_query='sum(rate(rag_query_total{status=~"success|client_error"}[{{window}}]))',
    total_events_query='sum(rate(rag_query_total[{{window}}]))',
)

LLM_TTFT_SLI = SLI(
    name="llm_ttft",
    description="Proportion of LLM requests with TTFT under 1 second",
    metric_query="""
        sum(rate(rag_llm_time_to_first_token_seconds_bucket{le="1"}[{{window}}]))
        / sum(rate(rag_llm_time_to_first_token_seconds_count[{{window}}]))
    """,
    unit="ratio",
)

RETRIEVAL_LATENCY_SLI = SLI(
    name="retrieval_latency",
    description="Proportion of retrievals completed within 500ms",
    metric_query="""
        sum(rate(rag_retrieval_duration_seconds_bucket{le="0.5"}[{{window}}]))
        / sum(rate(rag_retrieval_duration_seconds_count[{{window}}]))
    """,
    unit="ratio",
)


# SLO Definitions
QUERY_LATENCY_SLO = SLO(
    name="Query Latency SLO",
    sli=QUERY_LATENCY_SLI,
    target=0.99,  # 99% of queries under 2s
    window="30d",
    slo_type=SLOType.LATENCY,
    description="99% of queries must complete within 2 seconds over a 30-day window",
    error_budget_calculation="""
        Error budget = (1 - target) = 1%
        Over 30 days: 30 * 24 * 60 = 43,200 minutes
        Budget = 432 minutes of allowed violations
    """,
    burn_rate_alerts=[
        {"severity": "page", "burn_rate": 14.4, "window": "1h", "long_window": "5m"},
        {"severity": "page", "burn_rate": 6, "window": "6h", "long_window": "30m"},
        {"severity": "ticket", "burn_rate": 1, "window": "3d", "long_window": "6h"},
    ],
)

AVAILABILITY_SLO = SLO(
    name="Availability SLO",
    sli=AVAILABILITY_SLI,
    target=0.999,  # 99.9% availability
    window="30d",
    slo_type=SLOType.AVAILABILITY,
    description="99.9% of requests must succeed over a 30-day window",
    error_budget_calculation="""
        Error budget = (1 - 0.999) = 0.1%
        Over 30 days: 43,200 minutes
        Budget = 43.2 minutes of errors
    """,
    burn_rate_alerts=[
        {"severity": "page", "burn_rate": 14.4, "window": "1h", "long_window": "5m"},
        {"severity": "page", "burn_rate": 6, "window": "6h", "long_window": "30m"},
        {"severity": "ticket", "burn_rate": 1, "window": "3d", "long_window": "6h"},
    ],
)

LLM_TTFT_SLO = SLO(
    name="LLM Time to First Token SLO",
    sli=LLM_TTFT_SLI,
    target=0.95,  # 95% of requests under 1s TTFT
    window="7d",
    slo_type=SLOType.LATENCY,
    description="95% of LLM requests must return first token within 1 second",
    error_budget_calculation="""
        Error budget = 5%
        Over 7 days: 10,080 minutes
        Budget = 504 minutes of slow responses
    """,
    burn_rate_alerts=[
        {"severity": "ticket", "burn_rate": 2, "window": "6h", "long_window": "1h"},
    ],
)


# All SLOs
ALL_SLOS = [
    QUERY_LATENCY_SLO,
    AVAILABILITY_SLO,
    LLM_TTFT_SLO,
]


def generate_slo_recording_rules() -> str:
    """Generate Prometheus recording rules for SLO tracking."""
    rules = []
    
    for slo in ALL_SLOS:
        sli = slo.sli
        name = sli.name.replace("_", ":")
        
        # Current SLI value
        rules.append({
            "record": f"rag:sli:{name}:30d",
            "expr": sli.metric_query.replace("{{window}}", "30d"),
        })
        
        # Error budget remaining
        rules.append({
            "record": f"rag:error_budget:{name}:30d",
            "expr": f"""
                1 - (
                    (1 - rag:sli:{name}:30d)
                    / (1 - {slo.target})
                )
            """,
        })
    
    return rules


def generate_slo_burn_rate_alerts() -> List[dict]:
    """Generate alerting rules based on SLO burn rates."""
    alerts = []
    
    for slo in ALL_SLOS:
        sli = slo.sli
        
        for alert_config in slo.burn_rate_alerts:
            alert_name = f"SLO{sli.name.title().replace('_', '')}BurnRate"
            
            alerts.append({
                "alert": alert_name,
                "expr": f"""
                    (
                        1 - (
                            {sli.good_events_query.replace('{{window}}', alert_config['long_window'])}
                            / {sli.total_events_query.replace('{{window}}', alert_config['long_window'])}
                        )
                    ) > ({1 - slo.target} * {alert_config['burn_rate']})
                    and
                    (
                        1 - (
                            {sli.good_events_query.replace('{{window}}', alert_config['window'])}
                            / {sli.total_events_query.replace('{{window}}', alert_config['window'])}
                        )
                    ) > ({1 - slo.target} * {alert_config['burn_rate']})
                """,
                "for": "5m",
                "labels": {
                    "severity": alert_config["severity"],
                    "slo": slo.name,
                },
                "annotations": {
                    "summary": f"{slo.name} burn rate too high",
                    "description": f"Error budget for {slo.name} is being consumed too fast",
                },
            })
    
    return alerts
```

### Metrics Catalog Documentation

```markdown
# RAG Pipeline Metrics Catalog

## Overview

This document defines the canonical metrics for the RAG pipeline. All metrics follow Prometheus naming conventions and use the `rag_` prefix.

## Naming Conventions

- **Format:** `rag_<subsystem>_<metric>_<unit>`
- **Units:** Always use base units (seconds, bytes, not milliseconds, megabytes)
- **Suffixes:** 
  - `_total` for counters
  - `_seconds` for durations
  - `_bytes` for sizes
  - `_ratio` for ratios (0-1)

## Labels

### Standard Labels
| Label | Description | Values |
|-------|-------------|--------|
| `service` | Service emitting the metric | orchestrator, retrieval, ingestion, llm |
| `status` | Operation status | success, error, client_error |
| `tenant_id` | Tenant identifier | UUID string |

### Cardinality Guidelines
- Avoid high-cardinality labels (user IDs, document IDs)
- Use bucketed values for numeric labels (batch_size_bucket, not exact batch_size)
- Limit label values to < 100 per label

## Metric Categories

### Query Metrics (rag_query_*)
Metrics for end-user query processing.

### Retrieval Metrics (rag_retrieval_*)
Metrics for document retrieval operations.

### Embedding Metrics (rag_embedding_*)
Metrics for vector embedding generation.

### LLM Metrics (rag_llm_*)
Metrics for LLM inference operations.

### Ingestion Metrics (rag_ingestion_*, rag_document_*, rag_chunks_*)
Metrics for document ingestion pipeline.

### Cache Metrics (rag_cache_*)
Metrics for caching layers.

## SLO Metrics

### Key SLOs
| SLO | Target | Window | SLI Metric |
|-----|--------|--------|------------|
| Query Latency | 99% < 2s | 30d | rag_query_duration_seconds |
| Availability | 99.9% | 30d | rag_query_total |
| LLM TTFT | 95% < 1s | 7d | rag_llm_time_to_first_token_seconds |

### Error Budget Calculation
```
Error Budget Remaining = 1 - (actual_error_rate / allowed_error_rate)
```
```

## Unit Tests

```python
import pytest
from typing import Dict, Any


def test_metric_names_follow_convention():
    """Test all metric names follow naming convention."""
    for key, metric in METRIC_CATALOG.items():
        assert metric.name.startswith("rag_"), f"{metric.name} must start with 'rag_'"
        
        # Check unit suffix
        if metric.unit == MetricUnit.SECONDS:
            assert metric.name.endswith("_seconds"), f"{metric.name} should end with _seconds"
        elif metric.unit == MetricUnit.BYTES:
            assert metric.name.endswith("_bytes"), f"{metric.name} should end with _bytes"
        elif metric.unit == MetricUnit.TOTAL:
            assert metric.name.endswith("_total"), f"{metric.name} should end with _total"


def test_metric_has_labels():
    """Test all metrics have required labels."""
    for key, metric in METRIC_CATALOG.items():
        assert len(metric.labels) > 0, f"{metric.name} must have at least one label"


def test_histogram_has_buckets():
    """Test all histograms have buckets defined."""
    for key, metric in METRIC_CATALOG.items():
        if metric.type == MetricType.HISTOGRAM:
            assert metric.buckets is not None, f"Histogram {metric.name} must have buckets"
            assert len(metric.buckets) > 3, f"Histogram {metric.name} should have meaningful buckets"


def test_slo_metrics_marked():
    """Test SLO-relevant metrics are marked."""
    slo_metrics = get_slo_relevant_metrics()
    
    assert len(slo_metrics) > 0
    assert all(m.slo_relevant for m in slo_metrics)


def test_label_descriptions_complete():
    """Test all labels have descriptions."""
    for key, metric in METRIC_CATALOG.items():
        for label in metric.labels:
            assert label in metric.label_descriptions, \
                f"Label '{label}' in {metric.name} needs description"


def test_example_queries_valid():
    """Test example queries are syntactically reasonable."""
    for key, metric in METRIC_CATALOG.items():
        for query in metric.example_queries:
            # Basic check for metric name presence
            assert metric.name in query or metric.name.replace("_", ":") in query, \
                f"Query should reference {metric.name}"


def test_slo_definitions():
    """Test SLO definitions are valid."""
    for slo in ALL_SLOS:
        assert slo.target > 0 and slo.target < 1
        assert slo.window.endswith("d")  # Days
        assert len(slo.burn_rate_alerts) > 0


def test_generate_documentation():
    """Test documentation generation."""
    doc = generate_metrics_documentation()
    
    assert "# RAG Pipeline Metrics Catalog" in doc
    assert "rag_query_duration_seconds" in doc
    assert "rag_llm_tokens_total" in doc


def test_generate_slo_recording_rules():
    """Test SLO recording rule generation."""
    rules = generate_slo_recording_rules()
    
    assert len(rules) > 0
    assert all("record" in r for r in rules)
    assert all("expr" in r for r in rules)


def test_generate_burn_rate_alerts():
    """Test burn rate alert generation."""
    alerts = generate_slo_burn_rate_alerts()
    
    assert len(alerts) > 0
    assert all("alert" in a for a in alerts)
    assert all("severity" in a.get("labels", {}) for a in alerts)
```

## Dependencies

```
prometheus-client>=0.19.0
```

## Definition of Done

- [ ] MetricNames constants defined for all metrics
- [ ] MetricDefinition dataclass with full documentation
- [ ] All query/request metrics defined with labels
- [ ] All retrieval metrics defined with labels
- [ ] All embedding metrics defined with labels
- [ ] All LLM metrics defined with labels
- [ ] All ingestion metrics defined with labels
- [ ] All cache metrics defined with labels
- [ ] SLI definitions for key service indicators
- [ ] SLO definitions with targets and windows
- [ ] Error budget calculation documented
- [ ] Burn rate alert generation implemented
- [ ] Metrics catalog documentation generated
- [ ] Naming conventions validated in tests
- [ ] Label descriptions complete
- [ ] Example PromQL queries provided
- [ ] >90% test coverage
- [ ] Markdown documentation complete
