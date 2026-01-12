"""FastAPI middleware for logging and metrics."""

import time
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from observability.metrics import RetrievalMetrics, get_metrics_output
from observability.retrieval_logger import RetrievalLogger
from observability.tracing import TracingSetup


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic request/response logging.
    """

    def __init__(
        self,
        app: FastAPI,
        logger: RetrievalLogger,
        metrics: RetrievalMetrics,
    ):
        """
        Initialize logging middleware.

        Args:
            app: FastAPI application
            logger: Retrieval logger instance
            metrics: Retrieval metrics instance
        """
        super().__init__(app)
        self.logger = logger
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """
        Process request and log details.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response from handler
        """
        start_time = time.time()

        # Track active requests
        self.metrics.active_requests.inc()

        try:
            response = await call_next(request)

            # Log request completion
            duration = time.time() - start_time

            self.logger._log(
                "info",
                event="http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
            )

            return response
        except Exception as e:
            duration = time.time() - start_time

            self.logger._log(
                "error",
                event="http_request_error",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration * 1000, 2),
            )
            raise
        finally:
            self.metrics.active_requests.dec()


def setup_observability(
    app: FastAPI,
    config: Any,
) -> tuple[RetrievalLogger, RetrievalMetrics, TracingSetup]:
    """
    Set up all observability components for FastAPI app.

    Args:
        app: FastAPI application
        config: Configuration object with service_name, log_level, otlp_endpoint

    Returns:
        Tuple of (logger, metrics, tracing)
    """
    # Logger
    service_name = getattr(config, "service_name", "retrieval-service")
    log_level = getattr(config, "log_level", "INFO")
    log_format = getattr(config, "log_format", "json")
    otlp_endpoint = getattr(config, "otlp_endpoint", "http://localhost:4317")

    logger = RetrievalLogger(
        service_name=service_name,
        log_level=log_level,
        output_format=log_format,
    )

    # Metrics
    metrics = RetrievalMetrics(service_name.replace("-", "_"))
    metrics.set_service_info(version="1.0.0")

    # Tracing
    tracing = TracingSetup(
        service_name=service_name,
        otlp_endpoint=otlp_endpoint,
    )
    tracing.instrument_app(app)

    # Add middleware
    app.add_middleware(LoggingMiddleware, logger=logger, metrics=metrics)

    # Metrics endpoint
    @app.get("/metrics")
    async def get_metrics() -> Response:
        content, content_type = get_metrics_output()
        return Response(content=content, media_type=content_type)

    # Store in app state
    app.state.logger = logger
    app.state.metrics = metrics
    app.state.tracing = tracing

    return logger, metrics, tracing
