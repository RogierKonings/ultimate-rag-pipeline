"""Verification metrics for RAG answer validation observability.

This module provides Prometheus metrics for tracking verification node
outcomes, enabling quality monitoring and feedback correlation.

Reference: US-10.4.2 - Verification Metrics & Logging
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from workflow.verification.models import VerificationResult

# =============================================================================
# Verification Score Metrics
# =============================================================================

rag_verification_score = Histogram(
    "rag_verification_score",
    "Distribution of verification scores",
    ["tenant_id"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

rag_verification_label = Counter(
    "rag_verification_label_total",
    "Verification results by label",
    ["label", "tenant_id"],  # supported, partial, unsupported, skipped
)

# =============================================================================
# Verification Latency Metrics
# =============================================================================

rag_verification_latency = Histogram(
    "rag_verification_latency_seconds",
    "Verification node latency",
    ["tenant_id"],
    buckets=[0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 2.0, 5.0],
)

# =============================================================================
# Claims Metrics
# =============================================================================

rag_verification_claims = Counter(
    "rag_verification_claims_total",
    "Claims by verification status",
    ["status", "tenant_id"],  # supported, partial, unsupported
)


def record_verification_metrics(
    result: VerificationResult,
    tenant_id: str | None = None,
) -> None:
    """
    Record verification metrics to Prometheus.

    Args:
        result: The verification result containing score, label, and claim counts.
        tenant_id: The tenant identifier for multi-tenant filtering.
    """
    tid = tenant_id or "anonymous"

    # Record verification score (only for non-skipped verifications)
    if not result.skipped:
        rag_verification_score.labels(tenant_id=tid).observe(result.score)

    # Record verification label
    rag_verification_label.labels(
        label=result.label,
        tenant_id=tid,
    ).inc()

    # Record verification latency
    rag_verification_latency.labels(tenant_id=tid).observe(
        result.verification_time_ms / 1000.0
    )

    # Record claim counts (only for non-skipped verifications)
    if not result.skipped:
        rag_verification_claims.labels(status="supported", tenant_id=tid).inc(
            result.claims_supported
        )
        rag_verification_claims.labels(status="partial", tenant_id=tid).inc(
            result.claims_partial
        )
        rag_verification_claims.labels(status="unsupported", tenant_id=tid).inc(
            result.claims_unsupported
        )
