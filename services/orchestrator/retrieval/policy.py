"""Policy helpers for retrieval parameter selection."""

from __future__ import annotations

from typing import Any

# Strategies that are typically analytical and benefit from reranking.
COMPLEX_RERANK_STRATEGIES = {
    "complex",
    "multi_hop",
    "comparison",
    "aggregation",
}

# Intents that imply deeper reasoning and better quality from reranking.
ANALYTICAL_RERANK_INTENTS = {
    "ANALYTICAL",
}


def _coerce_optional_bool(value: Any) -> bool | None:
    """Parse optional bool-like values from user options."""
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False

    return None


def coerce_positive_int(value: Any, default: int) -> int:
    """Parse a positive integer, falling back to *default* on invalid values."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_retrieval_option(
    options: dict[str, Any] | None,
    *,
    key: str,
    default: Any = None,
    legacy_key: str | None = None,
) -> Any:
    """Resolve a retrieval option from nested or legacy top-level request options.

    Preferred format:
        options={"retrieval": {"top_k": 20, "mode": "hybrid", "rerank": True}}

    Legacy format (still supported):
        options={"top_k": 20, "retrieval_mode": "hybrid", "rerank": True}
    """
    if not isinstance(options, dict):
        return default

    nested = options.get("retrieval")
    if isinstance(nested, dict) and key in nested:
        return nested[key]

    if legacy_key and legacy_key in options:
        return options[legacy_key]

    if key in options:
        return options[key]

    return default


def should_enable_rerank(
    *,
    strategy: str | None,
    intent: str | None = None,
    complexity_score: float | None = None,
    rerank_override: Any = None,
) -> bool:
    """Return whether reranking should be enabled for this retrieval request.

    Decision order:
    1. Explicit request override (`rerank`) if provided.
    2. Known complex strategies.
    3. Analytical intent.
    4. High complexity score fallback.
    """
    explicit = _coerce_optional_bool(rerank_override)
    if explicit is not None:
        return explicit

    strategy_lower = (strategy or "").strip().lower()
    if strategy_lower in COMPLEX_RERANK_STRATEGIES:
        return True

    intent_upper = (intent or "").strip().upper()
    if intent_upper in ANALYTICAL_RERANK_INTENTS:
        return True

    try:
        if complexity_score is not None and float(complexity_score) >= 0.75:
            return True
    except (TypeError, ValueError):
        pass

    return False


__all__ = [
    "coerce_positive_int",
    "get_retrieval_option",
    "should_enable_rerank",
]
