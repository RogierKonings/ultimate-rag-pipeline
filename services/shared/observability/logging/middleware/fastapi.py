"""
FastAPI Request Logging Middleware.

Provides automatic request logging with timing and error tracking.
"""

import time
import uuid
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from opentelemetry import trace

from ..logger import get_structured_logger
from ..context import set_request_context, clear_request_context
from ..config import LoggingConfig


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.

    Features:
    - Request/response logging with timing
    - Request ID generation and propagation
    - Trace context extraction
    - Error logging with stack traces
    - Configurable path exclusion
    """

    def __init__(
        self,
        app: ASGIApp,
        config: Optional[LoggingConfig] = None,
        service_name: str = "unknown",
        excluded_paths: Optional[list[str]] = None,
        log_request_headers: bool = False,
        log_response_headers: bool = False,
    ):
        """
        Initialize the middleware.

        Args:
            app: ASGI application
            config: Logging configuration
            service_name: Service name for logging
            excluded_paths: Paths to exclude from logging
            log_request_headers: Whether to log request headers
            log_response_headers: Whether to log response headers
        """
        super().__init__(app)
        self.logger = get_structured_logger(__name__)
        self.service_name = service_name
        self.log_request_headers = log_request_headers
        self.log_response_headers = log_response_headers

        if config:
            self.excluded_paths = config.excluded_paths
            self.log_request_body = config.log_request_body
            self.log_response_body = config.log_response_body
            self.max_body_length = config.max_body_length
        else:
            self.excluded_paths = excluded_paths or [
                "/health", "/healthz", "/ready", "/readyz",
                "/live", "/livez", "/metrics", "/favicon.ico",
            ]
            self.log_request_body = False
            self.log_response_body = False
            self.max_body_length = 1000

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request and log it."""
        # Skip excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Generate or extract request ID
        request_id = self._get_request_id(request)

        # Get trace context
        trace_id, span_id = self._get_trace_context()

        # Extract tenant/user from headers
        tenant_id = request.headers.get("x-tenant-id")
        user_id = request.headers.get("x-user-id")

        # Set request context for logging
        set_request_context(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id,
            span_id=span_id,
            method=request.method,
            path=request.url.path,
        )

        # Start timing
        start_time = time.perf_counter()

        # Build extra context
        extra = {
            "request_id": request_id,
            "client_host": request.client.host if request.client else None,
            "query_params": dict(request.query_params) if request.query_params else None,
        }

        if self.log_request_headers:
            extra["request_headers"] = dict(request.headers)

        # Log request start
        self.logger.request_started(
            method=request.method,
            path=request.url.path,
            **extra,
        )

        # Process request
        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Build response extra
            response_extra = {
                "request_id": request_id,
            }

            if self.log_response_headers:
                response_extra["response_headers"] = dict(response.headers)

            # Log based on status code
            if response.status_code >= 500:
                self.logger.request_failed(
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    error="Server error",
                    duration_ms=duration_ms,
                    **response_extra,
                )
            elif response.status_code >= 400:
                self.logger.warning(
                    f"Client error: {request.method} {request.url.path} -> {response.status_code}",
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    **response_extra,
                )
            else:
                self.logger.request_completed(
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    **response_extra,
                )

            # Add request ID to response headers
            response.headers["x-request-id"] = request_id

            return response

        except Exception as e:
            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log exception
            self.logger.adapter.exception(
                f"Request exception: {request.method} {request.url.path}",
                extra={
                    "event": "request.exception",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                },
            )
            raise

        finally:
            # Clear request context
            clear_request_context()

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from logging."""
        for excluded in self.excluded_paths:
            if path.startswith(excluded):
                return True
        return False

    def _get_request_id(self, request: Request) -> str:
        """Get or generate request ID."""
        # Check for existing request ID header
        request_id = request.headers.get("x-request-id")
        if request_id:
            return request_id

        # Generate new UUID
        return str(uuid.uuid4())

    def _get_trace_context(self) -> tuple[Optional[str], Optional[str]]:
        """Get current trace context from OpenTelemetry."""
        try:
            span = trace.get_current_span()
            if span is None:
                return None, None

            ctx = span.get_span_context()
            if ctx is None or not ctx.is_valid:
                return None, None

            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
        except Exception:
            return None, None


def create_request_logging_middleware(
    config: Optional[LoggingConfig] = None,
    service_name: str = "unknown",
) -> type:
    """
    Create a configured RequestLoggingMiddleware class.

    This is useful when you need to add the middleware using add_middleware().

    Args:
        config: Logging configuration
        service_name: Service name

    Returns:
        Configured middleware class
    """

    class ConfiguredRequestLoggingMiddleware(RequestLoggingMiddleware):
        def __init__(self, app: ASGIApp):
            super().__init__(
                app,
                config=config,
                service_name=service_name,
            )

    return ConfiguredRequestLoggingMiddleware
