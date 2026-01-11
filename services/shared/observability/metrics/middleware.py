"""
Prometheus Middleware for FastAPI.

Provides automatic HTTP request metrics collection with:
- Request counting and duration tracking
- Endpoint labeling using route patterns (not raw paths)
- Status code tracking
- Active request gauge
"""

import logging
import time
from typing import Callable, Optional, Set

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from prometheus_client import Counter, Histogram, Gauge, REGISTRY

logger = logging.getLogger(__name__)

# Default paths to exclude from metrics
DEFAULT_EXCLUDED_PATHS: Set[str] = {
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


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for Prometheus metrics.

    Tracks:
    - http_requests_total: Total requests by method, path, status
    - http_request_duration_seconds: Request latency histogram
    - http_requests_in_progress: Currently active requests
    """

    # Class-level metrics (shared across instances)
    _requests_total: Optional[Counter] = None
    _request_duration: Optional[Histogram] = None
    _requests_in_progress: Optional[Gauge] = None
    _initialized: bool = False

    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "rag_service",
        excluded_paths: Optional[Set[str]] = None,
        buckets: Optional[tuple] = None,
    ):
        """
        Initialize the middleware.

        Args:
            app: ASGI application
            service_name: Service name for metric labels
            excluded_paths: Paths to exclude from metrics
            buckets: Custom histogram buckets for latency
        """
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or DEFAULT_EXCLUDED_PATHS

        # Initialize metrics once
        self._init_metrics(buckets)

    @classmethod
    def _init_metrics(cls, buckets: Optional[tuple] = None) -> None:
        """Initialize Prometheus metrics (class method for singleton pattern)."""
        if cls._initialized:
            return

        if buckets is None:
            buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

        cls._requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["service", "method", "path", "status"],
            registry=REGISTRY,
        )

        cls._request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["service", "method", "path"],
            buckets=buckets,
            registry=REGISTRY,
        )

        cls._requests_in_progress = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests in progress",
            ["service", "method"],
            registry=REGISTRY,
        )

        cls._initialized = True
        logger.info("Prometheus HTTP metrics initialized")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Process request with metrics.

        Args:
            request: Incoming request
            call_next: Next handler

        Returns:
            Response from handler
        """
        # Skip excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        method = request.method
        path = self._get_path_template(request)

        # Track in-progress
        self._requests_in_progress.labels(
            service=self.service_name,
            method=method,
        ).inc()

        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response

        except Exception as e:
            status_code = 500
            raise

        finally:
            duration = time.perf_counter() - start_time

            # Record metrics
            self._requests_total.labels(
                service=self.service_name,
                method=method,
                path=path,
                status=self._status_bucket(status_code),
            ).inc()

            self._request_duration.labels(
                service=self.service_name,
                method=method,
                path=path,
            ).observe(duration)

            self._requests_in_progress.labels(
                service=self.service_name,
                method=method,
            ).dec()

    def _should_exclude(self, path: str) -> bool:
        """Check if path should be excluded."""
        if path in self.excluded_paths:
            return True

        for excluded in self.excluded_paths:
            if path.startswith(excluded + "/") or path.startswith(excluded + "?"):
                return True

        return False

    def _get_path_template(self, request: Request) -> str:
        """
        Get the route template for the request.

        Uses route pattern to avoid high cardinality from path parameters.
        """
        # Try to get route from scope
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path

        # Fall back to normalized path
        path = request.url.path
        # Remove trailing slashes for consistency
        return path.rstrip("/") or "/"

    def _status_bucket(self, status_code: int) -> str:
        """
        Get status code bucket for labeling.

        Groups status codes to reduce cardinality:
        - 2xx -> "2xx"
        - 3xx -> "3xx"
        - 4xx -> "4xx"
        - 5xx -> "5xx"
        """
        if 200 <= status_code < 300:
            return "2xx"
        elif 300 <= status_code < 400:
            return "3xx"
        elif 400 <= status_code < 500:
            return "4xx"
        else:
            return "5xx"


def add_prometheus_middleware(
    app: FastAPI,
    service_name: str = "rag_service",
    excluded_paths: Optional[Set[str]] = None,
) -> None:
    """
    Add Prometheus middleware to FastAPI app.

    Convenience function for adding the middleware.

    Args:
        app: FastAPI application
        service_name: Service name for labels
        excluded_paths: Paths to exclude
    """
    app.add_middleware(
        PrometheusMiddleware,
        service_name=service_name,
        excluded_paths=excluded_paths,
    )
    logger.info(f"Prometheus middleware added to {service_name}")
