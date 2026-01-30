"""
Logger Factory.

Provides centralized logging setup and logger retrieval.
"""

import atexit
import logging
import logging.handlers
import queue
import sys

from .config import LoggingConfig
from .context import ContextInjectorFilter, LoggerAdapter, StructuredLogger
from .filters import SensitiveDataFilter
from .formatters import JSONFormatter, PrettyJSONFormatter, TextFormatter

# Global state
_logging_initialized: bool = False
_logging_config: LoggingConfig | None = None
_queue_listener: logging.handlers.QueueListener | None = None

# Third-party loggers to quiet
NOISY_LOGGERS = [
    "urllib3",
    "httpx",
    "httpcore",
    "asyncio",
    "aiohttp",
    "uvicorn.access",
    "watchfiles",
    "hpack",
    "sqlalchemy.engine",
    "celery.worker.strategy",
]


def setup_logging(
    config: LoggingConfig | None = None,
    service_name: str | None = None,
) -> LoggingConfig:
    """
    Initialize logging for the application.

    This should be called once at application startup.

    Args:
        config: Logging configuration (uses env if not provided)
        service_name: Service name (used if config not provided)

    Returns:
        The logging configuration used
    """
    global _logging_initialized, _logging_config, _queue_listener

    if _logging_initialized:
        logging.getLogger(__name__).warning("Logging already initialized")
        return _logging_config  # type: ignore

    # Create config from env if not provided
    if config is None:
        config = LoggingConfig.from_env(service_name)

    _logging_config = config

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(config.get_log_level_int())

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatter
    if config.json_format:
        if config.pretty_json:
            formatter = PrettyJSONFormatter(
                service_name=config.service_name,
                service_version=config.service_version,
                environment=config.environment,
                include_trace_context=config.include_trace_context,
            )
        else:
            formatter = JSONFormatter(
                service_name=config.service_name,
                service_version=config.service_version,
                environment=config.environment,
                include_trace_context=config.include_trace_context,
            )
    else:
        formatter = TextFormatter(
            include_trace_context=config.include_trace_context,
        )

    # Create handler(s)
    if config.async_logging:
        # Use queue-based async logging
        log_queue: queue.Queue = queue.Queue(-1)  # Unbounded
        queue_handler = logging.handlers.QueueHandler(log_queue)

        # Create the actual handler for the queue listener
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)

        # Start the queue listener
        _queue_listener = logging.handlers.QueueListener(
            log_queue,
            stream_handler,
            respect_handler_level=True,
        )
        _queue_listener.start()

        # Register shutdown
        atexit.register(_shutdown_logging)

        root_logger.addHandler(queue_handler)
    else:
        # Direct logging
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    # Add filters
    sensitive_filter = SensitiveDataFilter(
        sensitive_fields=config.sensitive_fields,
    )
    root_logger.addFilter(sensitive_filter)

    context_filter = ContextInjectorFilter()
    root_logger.addFilter(context_filter)

    # Quiet noisy third-party loggers
    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    _logging_initialized = True

    # Log startup
    logger = get_logger(__name__)
    logger.info(
        f"Logging initialized for {config.service_name}",
        extra={
            "service_version": config.service_version,
            "environment": config.environment,
            "log_level": config.log_level,
            "json_format": config.json_format,
            "async_logging": config.async_logging,
        },
    )

    return config


def _shutdown_logging() -> None:
    """Shutdown the logging system gracefully."""
    global _queue_listener

    if _queue_listener is not None:
        _queue_listener.stop()
        _queue_listener = None


def get_logger(name: str | None = None) -> LoggerAdapter:
    """
    Get a logger with the given name.

    Returns a LoggerAdapter that automatically includes request context.

    Args:
        name: Logger name (usually __name__)

    Returns:
        LoggerAdapter instance
    """
    global _logging_initialized, _logging_config

    # Auto-initialize if needed
    if not _logging_initialized:
        setup_logging()

    logger = logging.getLogger(name)
    return LoggerAdapter(logger)


def get_structured_logger(name: str | None = None) -> StructuredLogger:
    """
    Get a structured logger with convenience methods.

    Args:
        name: Logger name (usually __name__)

    Returns:
        StructuredLogger instance
    """
    adapter = get_logger(name)
    return StructuredLogger(adapter)


def get_component_logger(
    component: str,
    name: str | None = None,
) -> LoggerAdapter:
    """
    Get a logger for a specific component.

    Includes the component name as static context.

    Args:
        component: Component name (e.g., "retrieval", "orchestrator")
        name: Logger name

    Returns:
        LoggerAdapter with component context
    """
    adapter = get_logger(name)
    return adapter.with_context(component=component)


def configure_third_party_logging(
    logger_name: str,
    level: int = logging.WARNING,
) -> None:
    """
    Configure logging level for a third-party library.

    Args:
        logger_name: Name of the third-party logger
        level: Logging level to set
    """
    logging.getLogger(logger_name).setLevel(level)


def add_file_handler(
    filename: str,
    level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """
    Add a rotating file handler to the root logger.

    Args:
        filename: Path to log file
        level: Minimum level for this handler
        max_bytes: Max file size before rotation
        backup_count: Number of backup files to keep
    """
    global _logging_config

    if _logging_config is None:
        setup_logging()

    # Create file handler
    file_handler = logging.handlers.RotatingFileHandler(
        filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setLevel(level)

    # Create formatter (JSON for files)
    formatter = JSONFormatter(
        service_name=_logging_config.service_name if _logging_config else "unknown",
        service_version=_logging_config.service_version if _logging_config else "0.0.0",
        environment=_logging_config.environment if _logging_config else "development",
    )
    file_handler.setFormatter(formatter)

    # Add to root logger
    logging.getLogger().addHandler(file_handler)


class LoggingContext:
    """
    Context manager for temporary logging configuration.

    Useful for adding extra context to a block of code.
    """

    def __init__(self, **context: any):
        """
        Initialize the context.

        Args:
            **context: Context fields to add
        """
        self.context = context
        self._original_context = None

    def __enter__(self) -> "LoggingContext":
        """Enter the context, setting up logging context."""
        from .context import get_request_context, set_request_context, update_request_context

        self._original_context = get_request_context()
        if self._original_context:
            update_request_context(**self.context)
        else:
            set_request_context(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context, restoring original context."""
        from .context import _request_context

        _request_context.set(self._original_context)
