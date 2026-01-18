"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)

__all__ = [
    "CorrelationContext",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
]
