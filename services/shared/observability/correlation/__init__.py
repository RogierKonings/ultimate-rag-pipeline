"""Correlation ID propagation for distributed tracing."""

from .context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from .http_client import CorrelatedHttpClient, create_service_client
from .middleware import CorrelationMiddleware

__all__ = [
    "CorrelationContext",
    "CorrelationMiddleware",
    "CorrelatedHttpClient",
    "create_service_client",
    "get_correlation_context",
    "set_correlation_context",
    "clear_correlation_context",
]
