"""
Metric Definitions Module.

Provides canonical metric definitions with:
- Full documentation for each metric
- Label descriptions and cardinality guidelines
- Example PromQL queries
- SLO relevance flags
- Histogram bucket configurations

This module serves as the single source of truth for RAG metrics semantics.
"""

from .base import (
    METRIC_CATALOG,
    Label,
    MetricDefinition,
    MetricType,
    generate_metrics_documentation,
    get_metric_definition,
    get_slo_relevant_metrics,
    validate_metric_name,
)
from .sli import SLI, SLI_CATALOG
from .slo import SLO, SLO_CATALOG, generate_slo_burn_rate_alerts, generate_slo_recording_rules

__all__ = [
    # Metric definitions
    "MetricDefinition",
    "MetricType",
    "Label",
    "METRIC_CATALOG",
    "get_metric_definition",
    "get_slo_relevant_metrics",
    "validate_metric_name",
    "generate_metrics_documentation",
    # SLI/SLO
    "SLI",
    "SLI_CATALOG",
    "SLO",
    "SLO_CATALOG",
    "generate_slo_recording_rules",
    "generate_slo_burn_rate_alerts",
]
