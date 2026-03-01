"""
Base Metric Definition Classes.

Provides dataclasses and utilities for defining canonical metrics
with full documentation and semantic meaning.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum


class MetricType(StrEnum):
    """Prometheus metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class Label:
    """
    Metric label definition.

    Attributes:
        name: Label name
        description: Human-readable description
        cardinality: Expected cardinality level (low, medium, high)
        example_values: Example values for documentation
    """

    name: str
    description: str
    cardinality: str = "low"  # low (<10), medium (<100), high (>100)
    example_values: list[str] = field(default_factory=list)


@dataclass
class MetricDefinition:
    """
    Canonical metric definition.

    Provides full documentation and semantic meaning for a metric.

    Attributes:
        name: Metric name (follows rag_<subsystem>_<metric>_<unit> convention)
        metric_type: Prometheus metric type
        unit: Unit of measurement
        description: Human-readable description
        labels: List of label definitions
        buckets: Histogram buckets (for histograms only)
        objectives: Summary objectives (for summaries only)
        use_cases: List of use case descriptions
        example_queries: Example PromQL queries
        slo_relevant: Whether this metric is relevant for SLOs
        subsystem: Metric subsystem (query, retrieval, llm, etc.)
    """

    name: str
    metric_type: MetricType
    unit: str
    description: str
    labels: list[Label] = field(default_factory=list)
    buckets: tuple | None = None
    objectives: dict[float, float] | None = None
    use_cases: list[str] = field(default_factory=list)
    example_queries: list[str] = field(default_factory=list)
    slo_relevant: bool = False
    subsystem: str = ""

    def __post_init__(self):
        """Extract subsystem from metric name."""
        if not self.subsystem:
            parts = self.name.split("_")
            if len(parts) >= 2 and parts[0] == "rag":
                self.subsystem = parts[1]

    def validate_name(self) -> bool:
        """
        Validate metric name follows convention.

        Returns:
            True if name is valid
        """
        pattern = r"^rag_[a-z]+_[a-z_]+(_[a-z]+)?$"
        return bool(re.match(pattern, self.name))


# =============================================================================
# Metric Catalog - All canonical metrics
# =============================================================================

METRIC_CATALOG: dict[str, MetricDefinition] = {}


def _register(metric: MetricDefinition) -> MetricDefinition:
    """Register a metric in the catalog."""
    METRIC_CATALOG[metric.name] = metric
    return metric


# -----------------------------------------------------------------------------
# Query Metrics
# -----------------------------------------------------------------------------

_register(
    MetricDefinition(
        name="rag_query_total",
        metric_type=MetricType.COUNTER,
        unit="requests",
        description="Total number of queries processed by the RAG pipeline",
        labels=[
            Label("service", "Service processing the query", "low", ["orchestrator", "retrieval"]),
            Label("mode", "Search mode used", "low", ["hybrid", "semantic", "keyword"]),
            Label("status", "Query result status", "low", ["success", "error"]),
        ],
        use_cases=[
            "Track query volume over time",
            "Monitor error rates by search mode",
            "Calculate request rate for capacity planning",
        ],
        example_queries=[
            "sum(rate(rag_query_total[5m])) by (service)",
            'sum(rate(rag_query_total{status="error"}[5m])) / sum(rate(rag_query_total[5m]))',
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_query_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        unit="seconds",
        description="End-to-end query processing duration",
        labels=[
            Label("service", "Service processing the query", "low"),
            Label("mode", "Search mode used", "low"),
        ],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0),
        use_cases=[
            "Monitor query latency SLOs",
            "Identify slow queries",
            "Compare latency across search modes",
        ],
        example_queries=[
            "histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le))",
            "histogram_quantile(0.99, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, mode))",
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_query_active",
        metric_type=MetricType.GAUGE,
        unit="requests",
        description="Number of currently active queries being processed",
        labels=[
            Label("service", "Service processing queries", "low"),
        ],
        use_cases=[
            "Monitor concurrent request load",
            "Detect saturation conditions",
            "Trigger autoscaling",
        ],
        example_queries=[
            "sum(rag_query_active) by (service)",
            "max_over_time(rag_query_active[1h])",
        ],
    ),
)

# -----------------------------------------------------------------------------
# Retrieval Metrics
# -----------------------------------------------------------------------------

_register(
    MetricDefinition(
        name="rag_retrieval_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        unit="seconds",
        description="Retrieval operation duration by search type",
        labels=[
            Label("service", "Service performing retrieval", "low"),
            Label("search_type", "Type of search", "low", ["semantic", "keyword", "hybrid"]),
        ],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0),
        use_cases=[
            "Monitor retrieval latency SLOs",
            "Compare search type performance",
            "Identify vector DB bottlenecks",
        ],
        example_queries=[
            "histogram_quantile(0.99, sum(rate(rag_retrieval_duration_seconds_bucket[5m])) by (le, search_type))",
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_retrieval_result_count",
        metric_type=MetricType.HISTOGRAM,
        unit="results",
        description="Number of results returned per retrieval operation",
        labels=[
            Label("service", "Service performing retrieval", "low"),
            Label("search_type", "Type of search", "low"),
        ],
        buckets=(0, 1, 2, 5, 10, 20, 50, 100),
        use_cases=[
            "Monitor result quality",
            "Detect zero-result queries",
            "Tune top-k parameters",
        ],
        example_queries=[
            "histogram_quantile(0.5, sum(rate(rag_retrieval_result_count_bucket[5m])) by (le))",
            'sum(rate(rag_retrieval_result_count_bucket{le="0"}[5m])) / sum(rate(rag_retrieval_result_count_count[5m]))',
        ],
    ),
)

_register(
    MetricDefinition(
        name="rag_retrieval_zero_results_total",
        metric_type=MetricType.COUNTER,
        unit="requests",
        description="Number of retrieval operations returning zero results",
        labels=[
            Label("service", "Service performing retrieval", "low"),
            Label("search_type", "Type of search", "low"),
        ],
        use_cases=[
            "Monitor retrieval quality",
            "Detect indexing issues",
            "Identify query understanding problems",
        ],
        example_queries=[
            "sum(rate(rag_retrieval_zero_results_total[1h])) / sum(rate(rag_query_total[1h]))",
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_rerank_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        unit="seconds",
        description="Reranking operation duration",
        labels=[
            Label("service", "Service performing reranking", "low"),
            Label("model", "Reranker model", "low", ["bge-reranker-v2-m3"]),
        ],
        buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5),
        use_cases=[
            "Monitor reranking latency",
            "Compare reranker models",
            "Tune batch sizes",
        ],
        example_queries=[
            "histogram_quantile(0.95, sum(rate(rag_rerank_duration_seconds_bucket[5m])) by (le, model))",
        ],
    ),
)

# -----------------------------------------------------------------------------
# LLM Metrics
# -----------------------------------------------------------------------------

_register(
    MetricDefinition(
        name="rag_llm_requests_total",
        metric_type=MetricType.COUNTER,
        unit="requests",
        description="Total LLM inference requests",
        labels=[
            Label("service", "Service making LLM request", "low"),
            Label("model", "LLM model", "low", ["llama-3.1-8b", "llama-3.1-70b"]),
            Label("provider", "LLM provider", "low", ["vllm", "ollama"]),
            Label("status", "Request status", "low", ["success", "error", "timeout"]),
        ],
        use_cases=[
            "Track LLM usage",
            "Monitor error rates by model",
            "Calculate costs",
        ],
        example_queries=[
            "sum(rate(rag_llm_requests_total[5m])) by (model)",
            'sum(rate(rag_llm_requests_total{status="error"}[5m])) / sum(rate(rag_llm_requests_total[5m]))',
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_llm_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        unit="seconds",
        description="LLM inference duration",
        labels=[
            Label("service", "Service making LLM request", "low"),
            Label("model", "LLM model", "low"),
        ],
        buckets=(0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0, 60.0),
        use_cases=[
            "Monitor LLM latency SLOs",
            "Compare model performance",
            "Detect degradation",
        ],
        example_queries=[
            "histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le, model))",
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_llm_ttft_seconds",
        metric_type=MetricType.HISTOGRAM,
        unit="seconds",
        description="Time to first token for streaming LLM responses",
        labels=[
            Label("service", "Service making LLM request", "low"),
            Label("model", "LLM model", "low"),
        ],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
        use_cases=[
            "Monitor streaming latency",
            "Track user-perceived responsiveness",
            "Compare streaming performance",
        ],
        example_queries=[
            "histogram_quantile(0.95, sum(rate(rag_llm_ttft_seconds_bucket[5m])) by (le))",
        ],
        slo_relevant=True,
    ),
)

_register(
    MetricDefinition(
        name="rag_llm_tokens_total",
        metric_type=MetricType.COUNTER,
        unit="tokens",
        description="Total LLM tokens processed",
        labels=[
            Label("service", "Service making LLM request", "low"),
            Label("model", "LLM model", "low"),
            Label("type", "Token type", "low", ["input", "output"]),
        ],
        use_cases=[
            "Calculate LLM costs",
            "Monitor token throughput",
            "Track context usage",
        ],
        example_queries=[
            "sum(rate(rag_llm_tokens_total[1h])) by (model, type)",
            "sum(increase(rag_llm_tokens_total[24h])) by (type)",
        ],
    ),
)

# -----------------------------------------------------------------------------
# Ingestion Metrics
# -----------------------------------------------------------------------------

_register(
    MetricDefinition(
        name="rag_ingest_documents_total",
        metric_type=MetricType.COUNTER,
        unit="documents",
        description="Total documents ingested",
        labels=[
            Label("service", "Service performing ingestion", "low"),
            Label("source_type", "Document source type", "low", ["file", "web", "api", "database"]),
            Label("status", "Ingestion status", "low", ["success", "error", "skipped"]),
        ],
        use_cases=[
            "Track ingestion volume",
            "Monitor error rates by source",
            "Calculate throughput",
        ],
        example_queries=[
            "sum(rate(rag_ingest_documents_total[1h])) by (source_type)",
            'sum(increase(rag_ingest_documents_total{status="success"}[24h]))',
        ],
    ),
)

_register(
    MetricDefinition(
        name="rag_ingest_chunks_total",
        metric_type=MetricType.COUNTER,
        unit="chunks",
        description="Total chunks created during ingestion",
        labels=[
            Label("service", "Service performing ingestion", "low"),
            Label("strategy", "Chunking strategy", "low", ["recursive", "semantic", "fixed"]),
        ],
        use_cases=[
            "Track chunk volume",
            "Compare chunking strategies",
            "Monitor index growth",
        ],
        example_queries=[
            "sum(rate(rag_ingest_chunks_total[1h])) by (strategy)",
        ],
    ),
)

_register(
    MetricDefinition(
        name="rag_ingest_queue_size",
        metric_type=MetricType.GAUGE,
        unit="items",
        description="Current ingestion queue depth",
        labels=[
            Label("service", "Service processing queue", "low"),
            Label("queue", "Queue name", "low", ["default", "priority"]),
        ],
        use_cases=[
            "Monitor queue backlog",
            "Trigger autoscaling",
            "Detect bottlenecks",
        ],
        example_queries=[
            "sum(rag_ingest_queue_size) by (queue)",
            "max_over_time(rag_ingest_queue_size[1h])",
        ],
        slo_relevant=True,
    ),
)

# -----------------------------------------------------------------------------
# Cache Metrics
# -----------------------------------------------------------------------------

_register(
    MetricDefinition(
        name="rag_cache_hits_total",
        metric_type=MetricType.COUNTER,
        unit="requests",
        description="Total cache hits",
        labels=[
            Label("service", "Service using cache", "low"),
            Label("cache_type", "Type of cache", "low", ["embedding", "query", "response"]),
        ],
        use_cases=[
            "Calculate cache hit rate",
            "Monitor cache effectiveness",
            "Tune cache parameters",
        ],
        example_queries=[
            "sum(rate(rag_cache_hits_total[5m])) / (sum(rate(rag_cache_hits_total[5m])) + sum(rate(rag_cache_misses_total[5m])))",
        ],
    ),
)

_register(
    MetricDefinition(
        name="rag_cache_misses_total",
        metric_type=MetricType.COUNTER,
        unit="requests",
        description="Total cache misses",
        labels=[
            Label("service", "Service using cache", "low"),
            Label("cache_type", "Type of cache", "low"),
        ],
        use_cases=[
            "Calculate cache hit rate",
            "Identify cold cache scenarios",
            "Tune cache TTL",
        ],
        example_queries=[
            "sum(rate(rag_cache_misses_total[5m])) by (cache_type)",
        ],
    ),
)


# =============================================================================
# Utility Functions
# =============================================================================


def get_metric_definition(name: str) -> MetricDefinition | None:
    """
    Get a metric definition by name.

    Args:
        name: Metric name

    Returns:
        MetricDefinition or None if not found
    """
    return METRIC_CATALOG.get(name)


def get_slo_relevant_metrics() -> list[MetricDefinition]:
    """
    Get all metrics relevant for SLOs.

    Returns:
        List of SLO-relevant metric definitions
    """
    return [m for m in METRIC_CATALOG.values() if m.slo_relevant]


def validate_metric_name(name: str) -> bool:
    """
    Validate a metric name follows the RAG convention.

    Convention: rag_<subsystem>_<metric>_<unit>

    Args:
        name: Metric name to validate

    Returns:
        True if valid
    """
    pattern = r"^rag_[a-z]+_[a-z_]+$"
    return bool(re.match(pattern, name))


def generate_metrics_documentation() -> str:
    """
    Generate markdown documentation for all metrics.

    Returns:
        Markdown formatted documentation
    """
    lines = [
        "# RAG Metrics Catalog",
        "",
        "This document describes all canonical metrics for the RAG pipeline.",
        "",
        "## Naming Convention",
        "",
        "All metrics follow the pattern: `rag_<subsystem>_<metric>_<unit>`",
        "",
        "## Metrics by Subsystem",
        "",
    ]

    # Group by subsystem
    by_subsystem: dict[str, list[MetricDefinition]] = {}
    for metric in METRIC_CATALOG.values():
        subsystem = metric.subsystem or "other"
        if subsystem not in by_subsystem:
            by_subsystem[subsystem] = []
        by_subsystem[subsystem].append(metric)

    for subsystem in sorted(by_subsystem.keys()):
        lines.append(f"### {subsystem.title()}")
        lines.append("")

        for metric in by_subsystem[subsystem]:
            lines.append(f"#### `{metric.name}`")
            lines.append("")
            lines.append(f"**Type:** {metric.metric_type.value}")
            lines.append(f"**Unit:** {metric.unit}")
            lines.append(f"**SLO Relevant:** {'Yes' if metric.slo_relevant else 'No'}")
            lines.append("")
            lines.append(metric.description)
            lines.append("")

            if metric.labels:
                lines.append("**Labels:**")
                lines.append("")
                for label in metric.labels:
                    examples = (
                        f" (e.g., {', '.join(label.example_values)})"
                        if label.example_values
                        else ""
                    )
                    lines.append(f"- `{label.name}`: {label.description}{examples}")
                lines.append("")

            if metric.buckets:
                lines.append(f"**Buckets:** `{metric.buckets}`")
                lines.append("")

            if metric.use_cases:
                lines.append("**Use Cases:**")
                lines.append("")
                for use_case in metric.use_cases:
                    lines.append(f"- {use_case}")
                lines.append("")

            if metric.example_queries:
                lines.append("**Example Queries:**")
                lines.append("")
                lines.append("```promql")
                for query in metric.example_queries:
                    lines.append(query)
                lines.append("```")
                lines.append("")

    return "\n".join(lines)
