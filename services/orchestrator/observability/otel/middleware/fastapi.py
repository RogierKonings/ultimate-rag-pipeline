"""
FastAPI OpenTelemetry Middleware.

Provides automatic tracing for FastAPI applications with:
- Request/response span creation
- Trace context extraction from headers
- RAG-specific attribute enrichment
- Tenant/user ID extraction
- Configurable path exclusions
"""

import time
from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..attributes import RAGAttributes
from ..context import extract_trace_context, get_current_span_id, get_current_trace_id
from ..tracer import get_tracer

logger = structlog.get_logger(__name__)

# Default paths to exclude from tracing
DEFAULT_EXCLUDED_PATHS: set[str] = {
    "/health",
    "/healthz",
    "/ready",
    "/readyz",
    "/live",
    "/livez",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
}


class OTELMiddleware(BaseHTTPMiddleware):
    """
    OpenTelemetry middleware for FastAPI with RAG-specific attributes.

    This middleware:
    - Creates spans for all HTTP requests
    - Extracts trace context from incoming headers (W3C Trace Context)
    - Extracts tenant_id and user_id from headers
    - Adds RAG-specific attributes to spans
    - Excludes configurable paths (health checks, metrics, etc.)

    Usage:
        app = FastAPI()
        app.add_middleware(
            OTELMiddleware,
            service_name="retrieval-service",
            excluded_paths={"/health", "/metrics"},
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "rag-service",
        excluded_paths: set[str] | None = None,
        tenant_header: str = "X-Tenant-ID",
        user_header: str = "X-User-ID",
        request_id_header: str = "X-Request-ID",
        record_request_body: bool = False,
        record_response_body: bool = False,
        max_body_size: int = 1024,
    ):
        """
        Initialize the middleware.

        Args:
            app: ASGI application
            service_name: Service name for spans
            excluded_paths: Paths to exclude from tracing
            tenant_header: Header name for tenant ID
            user_header: Header name for user ID
            request_id_header: Header name for request ID
            record_request_body: Whether to record request body as attribute
            record_response_body: Whether to record response body as attribute
            max_body_size: Max body size to record (bytes)
        """
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS
        self.tenant_header = tenant_header.lower()
        self.user_header = user_header.lower()
        self.request_id_header = request_id_header.lower()
        self.record_request_body = record_request_body
        self.record_response_body = record_response_body
        self.max_body_size = max_body_size
        self.tracer = get_tracer(service_name)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Process a request with tracing.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response from handler
        """
        # Skip excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Extract trace context from headers
        headers = dict(request.headers)
        context = extract_trace_context(headers)

        # Create span name from method and route
        span_name = f"{request.method} {self._get_route_pattern(request)}"

        start_time = time.perf_counter()

        with self.tracer.start_as_current_span(
            span_name,
            context=context,
            kind=SpanKind.SERVER,
        ) as span:
            try:
                # Set standard HTTP attributes
                self._set_request_attributes(span, request)

                # Set RAG-specific attributes
                self._set_rag_attributes(span, request)

                # Process request
                response = await call_next(request)

                # Set response attributes
                self._set_response_attributes(span, response, start_time)

                # Add trace ID to response headers
                self._add_trace_headers(response)

                return response

            except Exception as e:
                # Record error
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute(RAGAttributes.ERROR_TYPE, type(e).__name__)
                span.set_attribute(RAGAttributes.ERROR_MESSAGE, str(e)[:500])
                raise

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded from tracing."""
        # Exact match
        if path in self.excluded_paths:
            return True

        # Prefix match for paths with trailing content
        for excluded in self.excluded_paths:
            if path.startswith((excluded + "/", excluded + "?")):
                return True

        return False

    def _get_route_pattern(self, request: Request) -> str:
        """Get the route pattern for span naming."""
        # Try to get the route pattern from the scope
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path

        # Fall back to the actual path (less ideal for cardinality)
        return request.url.path

    def _set_request_attributes(self, span: trace.Span, request: Request) -> None:
        """Set standard HTTP request attributes."""
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        span.set_attribute("http.scheme", request.url.scheme)
        span.set_attribute("http.host", request.url.hostname or "")
        span.set_attribute("http.target", request.url.path)
        span.set_attribute("http.route", self._get_route_pattern(request))

        # Client info
        if request.client:
            span.set_attribute("http.client_ip", request.client.host)

        # User agent
        user_agent = request.headers.get("user-agent")
        if user_agent:
            span.set_attribute("http.user_agent", user_agent[:200])

        # Content type and length
        content_type = request.headers.get("content-type")
        if content_type:
            span.set_attribute("http.request.content_type", content_type)

        content_length = request.headers.get("content-length")
        if content_length:
            span.set_attribute("http.request.content_length", int(content_length))

    def _set_rag_attributes(self, span: trace.Span, request: Request) -> None:
        """Set RAG-specific attributes from headers."""
        headers = request.headers

        # Tenant ID
        tenant_id = headers.get(self.tenant_header)
        if tenant_id:
            span.set_attribute(RAGAttributes.TENANT_ID, tenant_id)

        # User ID
        user_id = headers.get(self.user_header)
        if user_id:
            span.set_attribute(RAGAttributes.USER_ID, user_id)

        # Request ID
        request_id = headers.get(self.request_id_header)
        if request_id:
            span.set_attribute(RAGAttributes.REQUEST_ID, request_id)

        # Service name
        span.set_attribute("service.name", self.service_name)

    def _set_response_attributes(
        self,
        span: trace.Span,
        response: Response,
        start_time: float,
    ) -> None:
        """Set response attributes on span."""
        # Status code
        span.set_attribute("http.status_code", response.status_code)

        # Duration
        duration_ms = (time.perf_counter() - start_time) * 1000
        span.set_attribute(RAGAttributes.DURATION_MS, duration_ms)

        # Content type and length
        content_type = response.headers.get("content-type")
        if content_type:
            span.set_attribute("http.response.content_type", content_type)

        content_length = response.headers.get("content-length")
        if content_length:
            span.set_attribute("http.response.content_length", int(content_length))

        # Set span status based on HTTP status
        if response.status_code >= 500:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        elif response.status_code >= 400:
            # Client errors are not necessarily span errors
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.OK))

    def _add_trace_headers(self, response: Response) -> None:
        """Add trace context to response headers."""
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()

        if trace_id:
            response.headers["X-Trace-ID"] = trace_id
        if span_id:
            response.headers["X-Span-ID"] = span_id


def instrument_fastapi_app(
    app: FastAPI,
    service_name: str = "rag-service",
    excluded_urls: str | None = None,
) -> None:
    """
    Instrument a FastAPI app with OpenTelemetry auto-instrumentation.

    This uses the official opentelemetry-instrumentation-fastapi package
    for comprehensive instrumentation.

    Args:
        app: FastAPI application
        service_name: Service name for traces
        excluded_urls: Comma-separated URLs to exclude (regex patterns)
    """
    # Default exclusions
    if excluded_urls is None:
        excluded_urls = ",".join(
            [f".*{path}.*" for path in DEFAULT_EXCLUDED_PATHS],
        )

    try:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=excluded_urls,
            tracer_provider=trace.get_tracer_provider(),
        )
        logger.info(f"FastAPI instrumentation enabled for {service_name}")
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")


def get_trace_context_dependency():
    """
    FastAPI dependency for extracting trace context.

    Usage:
        @app.get("/items")
        async def get_items(trace_ctx: dict = Depends(get_trace_context_dependency())):
            logger.info(f"Processing request", extra=trace_ctx)
    """

    async def _get_context(request: Request) -> dict[str, str | None]:
        return {
            "trace_id": get_current_trace_id(),
            "span_id": get_current_span_id(),
            "tenant_id": request.headers.get("x-tenant-id"),
            "user_id": request.headers.get("x-user-id"),
            "request_id": request.headers.get("x-request-id"),
        }

    return _get_context
