"""
JSON Log Formatters.

Provides structured JSON formatting for log records with trace context.
"""

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter with trace context injection.

    Produces structured JSON logs with:
    - ISO 8601 timestamps
    - Service metadata
    - Source location
    - Trace context (trace_id, span_id)
    - Exception details
    """

    def __init__(
        self,
        service_name: str = "unknown",
        service_version: str = "0.0.0",
        environment: str = "development",
        include_trace_context: bool = True,
        static_fields: dict[str, Any] | None = None,
    ):
        """
        Initialize the formatter.

        Args:
            service_name: Name of the service
            service_version: Version of the service
            environment: Deployment environment
            include_trace_context: Whether to include trace_id/span_id
            static_fields: Additional static fields to include in all logs
        """
        super().__init__()
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.include_trace_context = include_trace_context
        self.static_fields = static_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_dict = self._build_log_dict(record)
        return json.dumps(log_dict, default=str, ensure_ascii=False)

    def _build_log_dict(self, record: logging.LogRecord) -> dict[str, Any]:
        """Build the log dictionary from the record."""
        # Base log structure
        log_dict: dict[str, Any] = {
            "timestamp": self._format_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Service metadata
        log_dict["service"] = {
            "name": self.service_name,
            "version": self.service_version,
            "environment": self.environment,
        }

        # Source location
        log_dict["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
            "module": record.module,
        }

        # Trace context
        if self.include_trace_context:
            trace_context = self._get_trace_context()
            if trace_context:
                log_dict["trace"] = trace_context

        # Exception info
        if record.exc_info:
            log_dict["exception"] = self._format_exception(record)

        # Extra fields from the log record
        extra_fields = self._get_extra_fields(record)
        if extra_fields:
            log_dict["extra"] = extra_fields

        # Static fields
        if self.static_fields:
            log_dict.update(self.static_fields)

        return log_dict

    def _format_timestamp(self, record: logging.LogRecord) -> str:
        """Format timestamp as ISO 8601 with timezone."""
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.isoformat()

    def _get_trace_context(self) -> dict[str, str] | None:
        """Get current trace context from OpenTelemetry."""
        try:
            span = trace.get_current_span()
            if span is None:
                return None

            ctx = span.get_span_context()
            if ctx is None or not ctx.is_valid:
                return None

            return {
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
            }
        except Exception:
            return None

    def _format_exception(self, record: logging.LogRecord) -> dict[str, Any]:
        """Format exception information."""
        exc_info = record.exc_info
        if exc_info is None:
            return {}

        exc_type, exc_value, exc_tb = exc_info

        return {
            "type": exc_type.__name__ if exc_type else "Unknown",
            "message": str(exc_value) if exc_value else "",
            "stacktrace": "".join(traceback.format_exception(*exc_info)),
        }

    def _get_extra_fields(self, record: logging.LogRecord) -> dict[str, Any]:
        """Extract extra fields from the log record."""
        # Standard LogRecord attributes to exclude
        standard_attrs = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "exc_info", "exc_text", "thread", "threadName",
            "message", "asctime",
        }

        extra = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra[key] = value

        return extra


class PrettyJSONFormatter(JSONFormatter):
    """
    Pretty-printed JSON formatter for development.

    Same as JSONFormatter but with indentation for readability.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as pretty-printed JSON."""
        log_dict = self._build_log_dict(record)
        return json.dumps(log_dict, default=str, ensure_ascii=False, indent=2)


class TextFormatter(logging.Formatter):
    """
    Text log formatter with trace context.

    Provides human-readable log format for development/debugging.
    """

    def __init__(
        self,
        include_trace_context: bool = True,
        include_source: bool = True,
    ):
        """
        Initialize the formatter.

        Args:
            include_trace_context: Whether to include trace_id
            include_source: Whether to include source location
        """
        super().__init__()
        self.include_trace_context = include_trace_context
        self.include_source = include_source

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as text."""
        parts = []

        # Timestamp
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        parts.append(dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])

        # Level
        parts.append(f"[{record.levelname:8}]")

        # Trace context
        if self.include_trace_context:
            try:
                span = trace.get_current_span()
                if span:
                    ctx = span.get_span_context()
                    if ctx and ctx.is_valid:
                        trace_id = format(ctx.trace_id, "032x")[-12:]  # Last 12 chars
                        parts.append(f"[{trace_id}]")
            except Exception:
                pass

        # Logger name
        parts.append(f"{record.name}:")

        # Message
        parts.append(record.getMessage())

        # Source location
        if self.include_source:
            parts.append(f"({record.filename}:{record.lineno})")

        result = " ".join(parts)

        # Exception
        if record.exc_info:
            result += "\n" + "".join(traceback.format_exception(*record.exc_info))

        return result
