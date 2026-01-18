"""Correlation ID propagation for distributed tracing."""

from .celery import (
    cleanup_correlation_for_task,
    extract_correlation_from_task,
    inject_correlation_to_task,
    setup_celery_correlation_signals,
)
from .context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)
from .http_client import CorrelatedHttpClient, create_service_client
from .middleware import CorrelationMiddleware

__all__ = [
    # Celery integration
    "cleanup_correlation_for_task",
    "extract_correlation_from_task",
    "inject_correlation_to_task",
    "setup_celery_correlation_signals",
    # Context management
    "CorrelationContext",
    "clear_correlation_context",
    "get_correlation_context",
    "set_correlation_context",
    # HTTP client
    "CorrelatedHttpClient",
    "create_service_client",
    # Middleware
    "CorrelationMiddleware",
]
