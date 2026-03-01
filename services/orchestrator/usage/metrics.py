"""Prometheus metrics for token usage tracking.

This module provides Prometheus counters for tracking LLM token consumption,
embedding generation, and quota enforcement.

Reference: US-10.5.4 - Token Usage Accounting
"""

from prometheus_client import Counter

# =============================================================================
# Token Usage Metrics
# =============================================================================

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["tenant_id", "model", "type"],  # values: prompt | completion
)

embeddings_generated_total = Counter(
    "embeddings_generated_total",
    "Total embeddings generated",
    ["tenant_id"],
)

# =============================================================================
# Quota Enforcement Metrics
# =============================================================================

quota_checks_total = Counter(
    "quota_checks_total",
    "Total quota checks performed",
    ["tenant_id", "result"],  # result: allowed | denied
)

quota_usage_percent = Counter(
    "quota_usage_percent",
    "Current quota usage percentage (recorded at check time)",
    ["tenant_id"],
)
