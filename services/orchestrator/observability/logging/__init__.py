"""
Structured Logging Module.

Provides JSON structured logging with trace correlation:
- JSONFormatter for structured output
- Trace context injection from OpenTelemetry
- Sensitive data filtering
- Request logging middleware

Usage:
    from shared.observability.logging import setup_logging, get_logger

    # At startup
    setup_logging(service_name="my-service")

    # Get logger
    logger = get_logger(__name__)
    logger.info("Processing request", extra={"user_id": "123"})
"""

from .config import LoggingConfig
from .context import (
    LoggerAdapter,
    clear_request_context,
    get_request_context,
    set_request_context,
)
from .filters import SensitiveDataFilter
from .formatters import JSONFormatter, PrettyJSONFormatter
from .logger import get_logger, setup_logging

__all__ = [
    # Configuration
    "LoggingConfig",
    # Logger factory
    "setup_logging",
    "get_logger",
    # Formatters
    "JSONFormatter",
    "PrettyJSONFormatter",
    # Filters
    "SensitiveDataFilter",
    # Context
    "set_request_context",
    "clear_request_context",
    "get_request_context",
    "LoggerAdapter",
]
