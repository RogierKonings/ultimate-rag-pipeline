"""FastAPI middleware for correlation ID propagation."""

from __future__ import annotations

import time
from typing import Callable

import structlog
from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .context import (
    CorrelationContext,
    clear_correlation_context,
    set_correlation_context,
)

logger = structlog.get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware for correlation ID propagation.

    This middleware:
    - Extracts or generates correlation IDs from incoming requests
    - Sets the correlation context for the duration of the request
    - Binds correlation data to structlog and OpenTelemetry spans
    - Adds correlation headers to responses
    - Clears context after request completion

    Example:
        ```python
        from fastapi import FastAPI
        from correlation.middleware import CorrelationMiddleware

        app = FastAPI()
        app.add_middleware(
            CorrelationMiddleware,
            service_name="my-service",
            excluded_paths=["/health", "/metrics"]
        )
        ```
    """

    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "unknown",
        excluded_paths: list[str] | None = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application.
            service_name: Name of this service for logging context.
            excluded_paths: List of path prefixes to exclude from processing.
                Defaults to common health/metrics endpoints.
        """
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or [
            "/health",
            "/healthz",
            "/ready",
            "/readyz",
            "/live",
            "/livez",
            "/metrics",
        ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request and propagate correlation context.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response with correlation headers added.
        """
        # Skip excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Extract or generate correlation context
        headers = {k.lower(): v for k, v in request.headers.items()}
        ctx = CorrelationContext.from_headers(headers)

        # Set in context variable
        set_correlation_context(ctx)

        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            request_id=ctx.request_id,
            trace_id=ctx.trace_id,
            tenant_id=ctx.tenant_id or "unknown",
            service=self.service_name,
        )

        # Add to OTEL span
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("request_id", ctx.request_id)
            span.set_attribute("trace_id", ctx.trace_id)
            if ctx.tenant_id:
                span.set_attribute("tenant_id", ctx.tenant_id)

        # Log request start
        start_time = time.perf_counter()
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)

            # Add correlation headers to response
            response.headers["X-Request-ID"] = ctx.request_id
            response.headers["X-Trace-ID"] = ctx.trace_id

            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration_ms, 2),
            )
            raise

        finally:
            # Clear context
            structlog.contextvars.unbind_contextvars(
                "request_id", "trace_id", "tenant_id", "service"
            )
            clear_correlation_context()

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from processing.

        Args:
            path: The request URL path.

        Returns:
            True if the path should be excluded, False otherwise.
        """
        return any(path.startswith(excluded) for excluded in self.excluded_paths)
