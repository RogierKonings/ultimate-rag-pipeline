"""
Logging Context Management.

Provides context variables for request-scoped logging with automatic injection.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestContext:
    """
    Request context for logging.

    Contains request-scoped information that should be included in logs.
    """

    request_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    method: str | None = None
    path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary for logging."""
        result = {}
        if self.request_id:
            result["request_id"] = self.request_id
        if self.tenant_id:
            result["tenant_id"] = self.tenant_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        if self.method:
            result["method"] = self.method
        if self.path:
            result["path"] = self.path
        result.update(self.extra)
        return result


# Context variable for request context
_request_context: ContextVar[RequestContext | None] = ContextVar(
    "request_context", default=None,
)


def set_request_context(
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    **extra: Any,
) -> RequestContext:
    """
    Set the request context for the current async context.

    Args:
        request_id: Unique request identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        trace_id: OpenTelemetry trace ID
        span_id: OpenTelemetry span ID
        method: HTTP method
        path: Request path
        **extra: Additional context fields

    Returns:
        The created RequestContext
    """
    context = RequestContext(
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        span_id=span_id,
        method=method,
        path=path,
        extra=extra,
    )
    _request_context.set(context)
    return context


def get_request_context() -> RequestContext | None:
    """Get the current request context."""
    return _request_context.get()


def clear_request_context() -> None:
    """Clear the request context."""
    _request_context.set(None)


def update_request_context(**updates: Any) -> RequestContext | None:
    """
    Update the current request context with additional fields.

    Args:
        **updates: Fields to update/add

    Returns:
        Updated context or None if no context exists
    """
    context = _request_context.get()
    if context is None:
        return None

    for key, value in updates.items():
        if hasattr(context, key):
            setattr(context, key, value)
        else:
            context.extra[key] = value

    return context


class ContextInjectorFilter(logging.Filter):
    """
    Log filter that injects request context into log records.

    Automatically adds context fields to every log record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Inject context into the record and return True."""
        context = get_request_context()

        if context:
            # Add context fields to the record
            for key, value in context.to_dict().items():
                if not hasattr(record, key):
                    setattr(record, key, value)

        return True


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically includes request context.

    Provides a consistent way to log with context across the application.
    """

    def __init__(
        self,
        logger: logging.Logger,
        extra: dict[str, Any] | None = None,
    ):
        """
        Initialize the adapter.

        Args:
            logger: Underlying logger
            extra: Static extra fields to always include
        """
        super().__init__(logger, extra or {})

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Process the log message, adding context."""
        # Get extra dict from kwargs, or create new one
        extra = kwargs.get("extra", {})

        # Add adapter's static extra
        extra.update(self.extra)

        # Add request context
        context = get_request_context()
        if context:
            for key, value in context.to_dict().items():
                if key not in extra:
                    extra[key] = value

        kwargs["extra"] = extra
        return msg, kwargs

    def with_context(self, **context: Any) -> "LoggerAdapter":
        """
        Create a new adapter with additional static context.

        Args:
            **context: Additional context fields

        Returns:
            New LoggerAdapter with merged context
        """
        merged_extra = {**self.extra, **context}
        return LoggerAdapter(self.logger, merged_extra)


class StructuredLogger:
    """
    Structured logger that provides convenience methods for common log patterns.

    Wraps a LoggerAdapter and provides methods for specific log types.
    """

    def __init__(self, adapter: LoggerAdapter):
        """
        Initialize the structured logger.

        Args:
            adapter: LoggerAdapter to wrap
        """
        self._adapter = adapter

    @property
    def adapter(self) -> LoggerAdapter:
        """Get the underlying adapter."""
        return self._adapter

    def debug(self, msg: str, **kwargs: Any) -> None:
        """Log a debug message."""
        self._adapter.debug(msg, extra=kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        """Log an info message."""
        self._adapter.info(msg, extra=kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        """Log a warning message."""
        self._adapter.warning(msg, extra=kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        """Log an error message."""
        self._adapter.error(msg, extra=kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        """Log a critical message."""
        self._adapter.critical(msg, extra=kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        """Log an exception with stack trace."""
        self._adapter.exception(msg, extra=kwargs)

    def request_started(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> None:
        """Log request start."""
        self._adapter.info(
            f"Request started: {method} {path}",
            extra={"event": "request.started", "method": method, "path": path, **kwargs},
        )

    def request_completed(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        """Log request completion."""
        self._adapter.info(
            f"Request completed: {method} {path} -> {status_code} ({duration_ms:.2f}ms)",
            extra={
                "event": "request.completed",
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                **kwargs,
            },
        )

    def request_failed(
        self,
        method: str,
        path: str,
        status_code: int,
        error: str,
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        """Log request failure."""
        self._adapter.error(
            f"Request failed: {method} {path} -> {status_code} ({error})",
            extra={
                "event": "request.failed",
                "method": method,
                "path": path,
                "status_code": status_code,
                "error": error,
                "duration_ms": duration_ms,
                **kwargs,
            },
        )

    def operation_started(self, operation: str, **kwargs: Any) -> None:
        """Log operation start."""
        self._adapter.debug(
            f"Operation started: {operation}",
            extra={"event": "operation.started", "operation": operation, **kwargs},
        )

    def operation_completed(
        self,
        operation: str,
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        """Log operation completion."""
        self._adapter.debug(
            f"Operation completed: {operation} ({duration_ms:.2f}ms)",
            extra={
                "event": "operation.completed",
                "operation": operation,
                "duration_ms": duration_ms,
                **kwargs,
            },
        )

    def operation_failed(
        self,
        operation: str,
        error: str,
        duration_ms: float,
        **kwargs: Any,
    ) -> None:
        """Log operation failure."""
        self._adapter.error(
            f"Operation failed: {operation} ({error})",
            extra={
                "event": "operation.failed",
                "operation": operation,
                "error": error,
                "duration_ms": duration_ms,
                **kwargs,
            },
        )
