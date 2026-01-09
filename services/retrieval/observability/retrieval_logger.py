"""Structured logging for retrieval operations."""

import hashlib
import logging
import sys
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Try to import structlog, fallback to basic logging if not available
try:
    import structlog
    from structlog.types import Processor

    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


class LogLevel(str, Enum):
    """Log level options."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RetrievalLogEntry(BaseModel):
    """Structured log entry for retrieval operations."""

    # Identifiers
    query_id: UUID
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    # Request info
    query: str
    query_type: Optional[str] = None
    mode: str  # hybrid, semantic, keyword

    # User context (anonymized)
    tenant_id: UUID
    user_id_hash: Optional[str] = None  # Hashed for privacy

    # Results
    result_count: int
    top_scores: list[float] = Field(default_factory=list)

    # Timing
    total_ms: float
    preprocessing_ms: float
    search_ms: float
    rerank_ms: Optional[float] = None

    # Components used
    used_semantic: bool = False
    used_keyword: bool = False
    used_reranking: bool = False

    # Timestamps
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Error info
    error: Optional[str] = None
    error_type: Optional[str] = None


class RetrievalLogger:
    """
    Structured logger for retrieval operations.

    Outputs JSON-formatted logs suitable for log aggregation
    systems like ELK, Loki, or CloudWatch.
    """

    def __init__(
        self,
        service_name: str = "retrieval-service",
        log_level: str = "INFO",
        output_format: str = "json",  # "json" or "console"
    ):
        """
        Initialize the retrieval logger.

        Args:
            service_name: Name of the service for log attribution
            log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
            output_format: Output format ("json" for production, "console" for dev)
        """
        self.service_name = service_name
        self.log_level = log_level
        self.output_format = output_format

        if HAS_STRUCTLOG:
            self._configure_structlog()
            self._logger = structlog.get_logger()
        else:
            self._configure_basic_logging()
            self._logger = logging.getLogger(service_name)

    def _configure_structlog(self) -> None:
        """Configure structlog with appropriate processors."""
        processors: list[Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        if self.output_format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, self.log_level.upper())
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

    def _configure_basic_logging(self) -> None:
        """Configure basic Python logging as fallback."""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, self.log_level.upper()))

        if self.output_format == "json":
            import json

            class JsonFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    log_data = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "level": record.levelname.lower(),
                        "message": record.getMessage(),
                        "service": self.service_name,
                    }
                    if hasattr(record, "extra"):
                        log_data.update(record.extra)
                    return json.dumps(log_data)

            formatter = JsonFormatter()
            formatter.service_name = self.service_name
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        handler.setFormatter(formatter)

        logger = logging.getLogger(self.service_name)
        logger.setLevel(getattr(logging, self.log_level.upper()))
        logger.addHandler(handler)

    def log_retrieval(
        self,
        query_id: UUID,
        query: str,
        mode: str,
        tenant_id: UUID,
        user_id: Optional[UUID],
        result_count: int,
        top_scores: list[float],
        total_ms: float,
        preprocessing_ms: float,
        search_ms: float,
        rerank_ms: Optional[float] = None,
        used_semantic: bool = False,
        used_keyword: bool = False,
        used_reranking: bool = False,
        error: Optional[str] = None,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """
        Log a retrieval operation.

        Args:
            query_id: Unique identifier for this query
            query: The search query text
            mode: Search mode (hybrid, semantic, keyword)
            tenant_id: Tenant identifier
            user_id: User identifier (will be hashed)
            result_count: Number of results returned
            top_scores: List of top result scores
            total_ms: Total request time in milliseconds
            preprocessing_ms: Query preprocessing time
            search_ms: Search execution time
            rerank_ms: Reranking time (if used)
            used_semantic: Whether semantic search was used
            used_keyword: Whether keyword search was used
            used_reranking: Whether reranking was used
            error: Error message if failed
            trace_id: OpenTelemetry trace ID
            span_id: OpenTelemetry span ID
            extra: Additional context
        """
        # Hash user_id for privacy
        user_id_hash = None
        if user_id:
            user_id_hash = hashlib.sha256(str(user_id).encode()).hexdigest()[:16]

        log_data = {
            "event": "retrieval",
            "service": self.service_name,
            "query_id": str(query_id),
            "query_length": len(query),
            "query_word_count": len(query.split()),
            "mode": mode,
            "tenant_id": str(tenant_id),
            "user_id_hash": user_id_hash,
            "result_count": result_count,
            "top_score": top_scores[0] if top_scores else None,
            "avg_score": sum(top_scores) / len(top_scores) if top_scores else None,
            "total_ms": round(total_ms, 2),
            "preprocessing_ms": round(preprocessing_ms, 2),
            "search_ms": round(search_ms, 2),
            "rerank_ms": round(rerank_ms, 2) if rerank_ms else None,
            "used_semantic": used_semantic,
            "used_keyword": used_keyword,
            "used_reranking": used_reranking,
        }

        if trace_id:
            log_data["trace_id"] = trace_id
        if span_id:
            log_data["span_id"] = span_id
        if extra:
            log_data.update(extra)

        if error:
            log_data["error"] = error
            self._log("error", **log_data)
        else:
            self._log("info", **log_data)

    def log_query_expansion(
        self,
        query_id: UUID,
        original_query: str,
        expanded_queries: list[str],
        method: str,  # "synonym", "llm", "hyde"
        duration_ms: float,
    ) -> None:
        """Log query expansion operation."""
        self._log(
            "info",
            event="query_expansion",
            query_id=str(query_id),
            original_length=len(original_query),
            expansion_count=len(expanded_queries),
            method=method,
            duration_ms=round(duration_ms, 2),
        )

    def log_cache_operation(
        self,
        operation: str,  # "hit", "miss", "set"
        cache_type: str,  # "query", "embedding", "rerank"
        key_prefix: str,
        duration_ms: float,
    ) -> None:
        """Log cache operation."""
        self._log(
            "debug",
            event="cache_operation",
            operation=operation,
            cache_type=cache_type,
            key_prefix=key_prefix,
            duration_ms=round(duration_ms, 2),
        )

    def log_error(
        self,
        error: Exception,
        context: dict[str, Any],
        query_id: Optional[UUID] = None,
    ) -> None:
        """Log error with context."""
        self._log(
            "error",
            event="error",
            query_id=str(query_id) if query_id else None,
            error_type=type(error).__name__,
            error_message=str(error),
            **context,
        )

    def _log(self, level: str, event: str, **kwargs: Any) -> None:
        """Internal logging method that handles both structlog and basic logging."""
        if HAS_STRUCTLOG:
            log_method = getattr(self._logger, level)
            log_method(event, **kwargs)
        else:
            import json

            log_method = getattr(self._logger, level)
            if self.output_format == "json":
                log_method(json.dumps({"event": event, **kwargs}))
            else:
                log_method(f"{event}: {kwargs}")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._log("info", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._log("debug", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._log("error", message, **kwargs)
