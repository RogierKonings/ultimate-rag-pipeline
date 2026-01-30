"""
Service authentication middleware.

This module provides FastAPI middleware for validating service-to-service
authentication on internal endpoints.
"""

import structlog
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .handler import JWTHandler, TokenExpiredError, TokenInvalidError, TokenRevokedError
from .service_auth_config import ServiceAuthSettings

logger = structlog.get_logger(__name__)


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for service-to-service authentication.

    This middleware validates JWT service tokens on internal endpoints,
    ensuring that only authorized services can access protected APIs.

    Endpoints can be excluded from authentication via configuration
    (e.g., health checks, metrics).

    Example:
        ```python
        from fastapi import FastAPI
        from shared.security.jwt import JWTHandler, ServiceAuthMiddleware, ServiceAuthSettings

        app = FastAPI()
        settings = ServiceAuthSettings(service_name="retrieval")
        handler = JWTHandler()

        app.add_middleware(
            ServiceAuthMiddleware,
            handler=handler,
            settings=settings,
        )
        ```
    """

    def __init__(
        self,
        app,
        handler: JWTHandler,
        settings: ServiceAuthSettings | None = None,
        internal_path_prefix: str = "/internal",
    ):
        """
        Initialize service authentication middleware.

        Args:
            app: FastAPI application
            handler: JWT handler for token verification
            settings: Service authentication settings
            internal_path_prefix: Path prefix for internal endpoints
                                 (default: "/internal")
        """
        super().__init__(app)
        self.handler = handler
        self.settings = settings or ServiceAuthSettings()
        self.internal_path_prefix = internal_path_prefix

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from authentication."""
        return any(
            path == excluded or path.startswith(excluded + "/")
            for excluded in self.settings.exclude_paths
        )

    def _is_internal_path(self, path: str) -> bool:
        """Check if path is an internal endpoint requiring service auth."""
        return path.startswith(self.internal_path_prefix)

    def _extract_token(self, request: Request) -> str | None:
        """Extract Bearer token from Authorization header."""
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        Process request and validate service authentication.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            Response from downstream handler
        """
        # Skip if service auth is disabled
        if not self.settings.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip excluded paths (health, metrics, etc.)
        if self._is_excluded_path(path):
            return await call_next(request)

        # Only require service auth for internal endpoints
        if not self._is_internal_path(path):
            # External endpoints use user auth (handled by JWTAuthMiddleware)
            return await call_next(request)

        # Extract and validate service token
        token = self._extract_token(request)
        if not token:
            logger.warning(
                "missing_service_auth",
                path=path,
                method=request.method,
                client_host=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Service authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            # Verify service token
            claims = self.handler.verify_service_token(
                token=token,
                expected_audience=self.settings.service_name,
                endpoint=path,
            )

            # Check if service is trusted
            if (
                self.settings.trusted_services
                and claims.service_name not in self.settings.trusted_services
            ):
                logger.warning(
                    "untrusted_service",
                    path=path,
                    caller_service=claims.service_name,
                    trusted_services=self.settings.trusted_services,
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": f"Service '{claims.service_name}' is not trusted"},
                )

            # Store caller service in request state for logging/tracing
            request.state.caller_service = claims.service_name
            request.state.service_token_claims = claims

            logger.debug(
                "service_auth_success",
                path=path,
                method=request.method,
                caller_service=claims.service_name,
            )

            return await call_next(request)

        except TokenExpiredError:
            logger.warning(
                "service_token_expired",
                path=path,
                method=request.method,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Service token has expired"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        except TokenRevokedError:
            logger.warning(
                "service_token_revoked",
                path=path,
                method=request.method,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Service token has been revoked"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        except TokenInvalidError as e:
            error_msg = str(e)

            # Check if this is an authorization error (403) vs auth error (401)
            if "not authorized for endpoint" in error_msg:
                logger.warning(
                    "service_unauthorized_endpoint",
                    path=path,
                    method=request.method,
                    error=error_msg,
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": error_msg},
                )

            logger.warning(
                "service_auth_failed",
                path=path,
                method=request.method,
                error=error_msg,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": error_msg},
                headers={"WWW-Authenticate": "Bearer"},
            )


def get_caller_service(request: Request) -> str | None:
    """
    Get the calling service name from request state.

    Use this in route handlers to access the authenticated service identity.

    Args:
        request: FastAPI request object

    Returns:
        Service name or None if not a service-authenticated request

    Example:
        ```python
        @app.get("/internal/search")
        async def search(request: Request):
            caller = get_caller_service(request)
            logger.info("Search called by", service=caller)
            ...
        ```
    """
    return getattr(request.state, "caller_service", None)
