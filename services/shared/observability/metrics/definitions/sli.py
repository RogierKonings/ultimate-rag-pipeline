"""
Service Level Indicator (SLI) Definitions.

Provides SLI dataclasses with PromQL query templates for
measuring service quality.
"""

from dataclasses import dataclass


@dataclass
class SLI:
    """
    Service Level Indicator definition.

    An SLI measures a specific aspect of service quality using
    PromQL queries against collected metrics.

    Attributes:
        name: Human-readable SLI name
        description: What this SLI measures
        query_good: PromQL query for good events (numerator)
        query_total: PromQL query for total events (denominator)
        query_ratio: PromQL query for the SLI ratio (0-1)
        unit: Unit of measurement
        category: SLI category (latency, availability, quality, etc.)
    """

    name: str
    description: str
    query_good: str
    query_total: str
    query_ratio: str = ""
    unit: str = "ratio"
    category: str = "availability"

    def __post_init__(self):
        """Generate ratio query if not provided."""
        if not self.query_ratio:
            self.query_ratio = f"({self.query_good}) / ({self.query_total})"

    def get_error_ratio_query(self) -> str:
        """Get query for error ratio (1 - SLI)."""
        return f"1 - ({self.query_ratio})"


# =============================================================================
# SLI Catalog
# =============================================================================

SLI_CATALOG: dict[str, SLI] = {}


def _register_sli(sli: SLI) -> SLI:
    """Register an SLI in the catalog."""
    SLI_CATALOG[sli.name] = sli
    return sli


# -----------------------------------------------------------------------------
# Availability SLIs
# -----------------------------------------------------------------------------

_register_sli(
    SLI(
        name="query_availability",
        description="Percentage of successful query requests",
        query_good='sum(rate(rag_query_total{status="success"}[{{window}}]))',
        query_total="sum(rate(rag_query_total[{{window}}]))",
        category="availability",
    ),
)

_register_sli(
    SLI(
        name="llm_availability",
        description="Percentage of successful LLM requests",
        query_good='sum(rate(rag_llm_requests_total{status="success"}[{{window}}]))',
        query_total="sum(rate(rag_llm_requests_total[{{window}}]))",
        category="availability",
    ),
)

_register_sli(
    SLI(
        name="retrieval_availability",
        description="Percentage of successful retrieval operations",
        query_good="sum(rate(rag_retrieval_duration_seconds_count[{{window}}]))",
        query_total="sum(rate(rag_query_total[{{window}}]))",
        category="availability",
    ),
)

# -----------------------------------------------------------------------------
# Latency SLIs
# -----------------------------------------------------------------------------

_register_sli(
    SLI(
        name="query_latency_p99",
        description="99th percentile query latency",
        query_good='sum(rate(rag_query_duration_seconds_bucket{le="2"}[{{window}}]))',
        query_total="sum(rate(rag_query_duration_seconds_count[{{window}}]))",
        query_ratio="histogram_quantile(0.99, sum(rate(rag_query_duration_seconds_bucket[{{window}}])) by (le))",
        unit="seconds",
        category="latency",
    ),
)

_register_sli(
    SLI(
        name="query_latency_p95",
        description="95th percentile query latency",
        query_good='sum(rate(rag_query_duration_seconds_bucket{le="2"}[{{window}}]))',
        query_total="sum(rate(rag_query_duration_seconds_count[{{window}}]))",
        query_ratio="histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket[{{window}}])) by (le))",
        unit="seconds",
        category="latency",
    ),
)

_register_sli(
    SLI(
        name="retrieval_latency_p99",
        description="99th percentile retrieval latency",
        query_good='sum(rate(rag_retrieval_duration_seconds_bucket{le="0.5"}[{{window}}]))',
        query_total="sum(rate(rag_retrieval_duration_seconds_count[{{window}}]))",
        query_ratio="histogram_quantile(0.99, sum(rate(rag_retrieval_duration_seconds_bucket[{{window}}])) by (le))",
        unit="seconds",
        category="latency",
    ),
)

_register_sli(
    SLI(
        name="llm_latency_p95",
        description="95th percentile LLM inference latency",
        query_good='sum(rate(rag_llm_duration_seconds_bucket{le="5"}[{{window}}]))',
        query_total="sum(rate(rag_llm_duration_seconds_count[{{window}}]))",
        query_ratio="histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[{{window}}])) by (le))",
        unit="seconds",
        category="latency",
    ),
)

_register_sli(
    SLI(
        name="llm_ttft_p95",
        description="95th percentile time to first token",
        query_good='sum(rate(rag_llm_ttft_seconds_bucket{le="1"}[{{window}}]))',
        query_total="sum(rate(rag_llm_ttft_seconds_count[{{window}}]))",
        query_ratio="histogram_quantile(0.95, sum(rate(rag_llm_ttft_seconds_bucket[{{window}}])) by (le))",
        unit="seconds",
        category="latency",
    ),
)

# -----------------------------------------------------------------------------
# Quality SLIs
# -----------------------------------------------------------------------------

_register_sli(
    SLI(
        name="retrieval_zero_results_rate",
        description="Percentage of queries returning zero results",
        query_good="sum(rate(rag_query_total[{{window}}])) - sum(rate(rag_retrieval_zero_results_total[{{window}}]))",
        query_total="sum(rate(rag_query_total[{{window}}]))",
        category="quality",
    ),
)

_register_sli(
    SLI(
        name="cache_hit_rate",
        description="Cache hit rate across all cache types",
        query_good="sum(rate(rag_cache_hits_total[{{window}}]))",
        query_total="sum(rate(rag_cache_hits_total[{{window}}])) + sum(rate(rag_cache_misses_total[{{window}}]))",
        category="quality",
    ),
)

# -----------------------------------------------------------------------------
# Throughput SLIs
# -----------------------------------------------------------------------------

_register_sli(
    SLI(
        name="ingestion_throughput",
        description="Document ingestion rate",
        query_good='sum(rate(rag_ingest_documents_total{status="success"}[{{window}}]))',
        query_total="sum(rate(rag_ingest_documents_total[{{window}}]))",
        unit="documents/second",
        category="throughput",
    ),
)


def get_sli(name: str) -> SLI | None:
    """
    Get an SLI by name.

    Args:
        name: SLI name

    Returns:
        SLI or None if not found
    """
    return SLI_CATALOG.get(name)


def get_slis_by_category(category: str) -> list[SLI]:
    """
    Get all SLIs in a category.

    Args:
        category: Category name

    Returns:
        List of SLIs in the category
    """
    return [sli for sli in SLI_CATALOG.values() if sli.category == category]


def render_sli_query(sli: SLI, window: str = "5m") -> str:
    """
    Render an SLI query with a specific time window.

    Args:
        sli: SLI to render
        window: Time window (e.g., "5m", "1h", "30d")

    Returns:
        Rendered PromQL query
    """
    return sli.query_ratio.replace("{{window}}", window)
