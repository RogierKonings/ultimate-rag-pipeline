"""
Security middleware for the Gateway.

Provides FastAPI middleware for authentication and rate limiting.
"""

import logging
import time
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import AuthContext, JWTAuth, get_auth_context
from .rate_limit import RateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for FastAPI.

    Validates JWT tokens and API keys, extracting auth context
    for downstream use.
    """

    def __init__(self, app, auth: JWTAuth | None = None):
        """
        Initialize auth middleware.

        Args:
            app: FastAPI application
            auth: JWTAuth instance (uses global if not provided)
        """
        super().__init__(app)
        self.auth = auth or get_auth_context()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request through auth middleware."""
        path = request.url.path

        # Skip auth for public paths
        if self.auth.is_path_public(path):
            return await call_next(request)

        # Skip auth if not required
        if not self.auth.config.require_auth:
            # Set default context
            request.state.auth_context = AuthContext(
                tenant_id="default",
                user_id="anonymous",
                auth_method="none",
            )
            return await call_next(request)

        # Extract auth credentials
        authorization = request.headers.get("Authorization")
        api_key = request.headers.get("X-API-Key")

        # Authenticate
        context = await self.auth.authenticate(authorization, api_key)

        if context is None:
            logger.warning(f"Authentication failed for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Authentication required",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    },
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Store context in request state
        request.state.auth_context = context

        # Log successful auth
        logger.debug(
            f"Authenticated: tenant={context.tenant_id} "
            f"user={context.user_id} method={context.auth_method}",
        )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for FastAPI.

    Enforces per-tenant and per-user rate limits using token bucket algorithm.
    """

    def __init__(
        self,
        app,
        rate_limiter: RateLimiter | None = None,
        skip_paths: list[str] | None = None,
    ):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application
            rate_limiter: RateLimiter instance (uses global if not provided)
            skip_paths: Paths to skip rate limiting
        """
        super().__init__(app)
        self.rate_limiter = rate_limiter or get_rate_limiter()
        self.skip_paths = skip_paths or [
            "/health",
            "/health/live",
            "/health/ready",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/metrics",
        ]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request through rate limit middleware."""
        path = request.url.path

        # Skip rate limiting for certain paths
        for skip_path in self.skip_paths:
            if path == skip_path or path.startswith(skip_path + "/"):
                return await call_next(request)

        # Get auth context (set by AuthMiddleware)
        auth_context: AuthContext | None = getattr(
            request.state, "auth_context", None,
        )

        if auth_context:
            tenant_id = auth_context.tenant_id
            user_id = auth_context.user_id
        else:
            # Fall back to headers or defaults
            tenant_id = request.headers.get("X-Tenant-ID", "default")
            user_id = request.headers.get("X-User-ID")

        # Check rate limit
        result = await self.rate_limiter.check_rate_limit(
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if not result.allowed:
            logger.warning(
                f"Rate limit exceeded: tenant={tenant_id} "
                f"user={user_id} path={path}",
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Rate limit exceeded",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    },
                },
                headers=result.to_headers(),
            )

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        # Add rate limit headers to response
        for header, value in result.to_headers().items():
            response.headers[header] = value

        # Record usage (tokens will be recorded separately after response)
        logger.debug(
            f"Request completed: tenant={tenant_id} user={user_id} "
            f"path={path} duration={duration:.3f}s remaining={result.remaining}",
        )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to responses.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Add security headers to response."""
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Add HSTS for HTTPS connections
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request/response logging with audit trail.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Log request and response details."""
        start_time = time.time()

        # Extract request info
        request_id = request.headers.get("X-Request-ID", f"req-{id(request)}")
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        # Get auth context if available
        auth_context: AuthContext | None = getattr(
            request.state, "auth_context", None,
        )
        tenant_id = auth_context.tenant_id if auth_context else "unknown"
        user_id = auth_context.user_id if auth_context else "unknown"

        logger.info(
            f"Request: {method} {path} | "
            f"request_id={request_id} client={client_ip} "
            f"tenant={tenant_id} user={user_id}",
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log response
        logger.info(
            f"Response: {method} {path} | "
            f"status={response.status_code} duration={duration_ms:.1f}ms | "
            f"request_id={request_id}",
        )

        # Add request ID to response
        response.headers["X-Request-ID"] = request_id

        return response
