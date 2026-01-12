"""Custom middleware for the ingestion API."""

import logging
import time
from collections.abc import Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging all HTTP requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Log request details and response timing.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            The HTTP response.
        """
        # Generate request ID
        request_id = str(uuid4())[:8]
        request.state.request_id = request_id

        # Log request
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
            },
        )

        # Time the request
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time

            # Log response
            logger.info(
                f"[{request_id}] {response.status_code} ({duration:.3f}s)",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "duration_seconds": duration,
                },
            )

            # Add headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration:.3f}s"

            return response

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"[{request_id}] Error: {e} ({duration:.3f}s)",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "duration_seconds": duration,
                },
            )
            raise


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware to extract and validate tenant context from requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Extract tenant ID from JWT token and add to request state.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            The HTTP response.
        """
        # Skip for health check and docs
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # Extract tenant from Authorization header if present
        # The actual validation happens in get_current_user dependency
        # This middleware just sets up the context
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jose import jwt

                from config import get_settings

                settings = get_settings()
                token = auth_header[7:]  # Remove "Bearer " prefix
                payload = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=[settings.jwt_algorithm],
                    options={"verify_exp": False},  # Just extract, don't validate here
                )
                request.state.tenant_id = payload.get("tenant_id")
            except Exception:  # noqa: S110
                # Validation will happen in the dependency
                pass

        return await call_next(request)
