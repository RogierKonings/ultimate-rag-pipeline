"""
FastAPI authentication middleware and dependencies.

This module provides middleware and dependencies for JWT authentication
in FastAPI applications.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import JWTSettings
from .handler import (
    JWTError,
    JWTHandler,
    TokenBlocklist,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from .models import TokenClaims, TokenType

# HTTP Bearer scheme for OpenAPI documentation
oauth2_scheme = HTTPBearer(auto_error=False)


class JWTAuthMiddleware:
    """
    JWT Authentication middleware for FastAPI.

    This class provides authentication functionality that can be used
    as a FastAPI dependency or as ASGI middleware.

    Example:
        ```python
        from fastapi import Depends, FastAPI
        from services.shared.security.jwt import JWTAuthMiddleware

        app = FastAPI()
        auth = JWTAuthMiddleware()

        @app.get("/protected")
        async def protected_route(
            claims: TokenClaims = Depends(auth.get_current_user)
        ):
            return {"user_id": str(claims.sub)}
        ```
    """

    def __init__(
        self,
        settings: JWTSettings | None = None,
        handler: JWTHandler | None = None,
        blocklist: TokenBlocklist | None = None,
        excluded_paths: list[str] | None = None,
    ):
        """
        Initialize JWT authentication middleware.

        Args:
            settings: JWT configuration settings
            handler: Pre-configured JWT handler
            blocklist: Token blocklist for revocation
            excluded_paths: Paths to exclude from authentication
        """
        self.settings = settings or JWTSettings()
        self.handler = handler or JWTHandler(self.settings, blocklist)
        self.excluded_paths = excluded_paths or [
            "/health",
            "/healthz",
            "/ready",
            "/readyz",
            "/live",
            "/livez",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/auth/token",
            "/api/v1/auth/refresh",
        ]

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from authentication."""
        return any(
            path == excluded or path.startswith(excluded + "/") for excluded in self.excluded_paths
        )

    def _extract_token(self, request: Request) -> str | None:
        """
        Extract JWT token from request.

        Looks for token in:
        1. Authorization header (Bearer token)
        2. Cookie (access_token)
        3. Query parameter (token) - for WebSocket/SSE

        Args:
            request: FastAPI request object

        Returns:
            Token string or None
        """
        # Try Authorization header first
        auth_header = request.headers.get("Authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]

        # Try cookie
        token = request.cookies.get("access_token")
        if token:
            return token

        # Try query parameter (for WebSocket/SSE)
        token = request.query_params.get("token")
        if token:
            return token

        return None

    async def get_current_user(
        self,
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(oauth2_scheme),
        ] = None,
    ) -> TokenClaims:
        """
        FastAPI dependency to get the current authenticated user.

        Args:
            request: FastAPI request
            credentials: HTTP Bearer credentials (for OpenAPI)

        Returns:
            Verified token claims

        Raises:
            HTTPException: If authentication fails
        """
        # Try to get token from various sources
        token = None
        token = credentials.credentials if credentials else self._extract_token(request)

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            claims = self.handler.verify_token(token, expected_type=TokenType.ACCESS)

            # Store claims in request state for later use
            request.state.user = claims
            request.state.tenant_id = claims.tenant_id

            return claims

        except TokenExpiredError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        except TokenRevokedError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        except TokenInvalidError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication error: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    async def get_current_user_optional(
        self,
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(oauth2_scheme),
        ] = None,
    ) -> TokenClaims | None:
        """
        FastAPI dependency to get the current user if authenticated.

        Unlike get_current_user, this returns None instead of raising
        an exception if no token is provided.

        Args:
            request: FastAPI request
            credentials: HTTP Bearer credentials

        Returns:
            Token claims or None
        """
        token = None
        token = credentials.credentials if credentials else self._extract_token(request)

        if not token:
            return None

        try:
            claims = self.handler.verify_token(token, expected_type=TokenType.ACCESS)
            request.state.user = claims
            request.state.tenant_id = claims.tenant_id
            return claims
        except JWTError:
            return None


def require_roles(*required_roles: str) -> Callable:
    """
    Decorator factory for requiring specific roles.

    Usage:
        ```python
        @app.get("/admin")
        @require_roles("admin", "super_admin")
        async def admin_route(claims: TokenClaims = Depends(get_current_user)):
            return {"admin": True}
        ```

    Args:
        *required_roles: Roles that grant access (any match)

    Returns:
        Dependency function
    """

    async def role_checker(claims: TokenClaims) -> TokenClaims:
        if not any(role in claims.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(required_roles)}",
            )
        return claims

    return role_checker


def require_permissions(*required_permissions: str) -> Callable:
    """
    Decorator factory for requiring specific permissions.

    Usage:
        ```python
        @app.delete("/documents/{id}")
        @require_permissions("documents:delete")
        async def delete_doc(claims: TokenClaims = Depends(get_current_user)):
            return {"deleted": True}
        ```

    Args:
        *required_permissions: Permissions that grant access (all required)

    Returns:
        Dependency function
    """

    async def permission_checker(claims: TokenClaims) -> TokenClaims:
        missing = [p for p in required_permissions if p not in claims.permissions]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permissions: {', '.join(missing)}",
            )
        return claims

    return permission_checker


def require_tenant(tenant_id_param: str = "tenant_id") -> Callable:
    """
    Dependency factory for tenant isolation enforcement.

    Ensures the user can only access resources in their tenant.

    Usage:
        ```python
        @app.get("/tenants/{tenant_id}/documents")
        async def list_docs(
            tenant_id: UUID,
            claims: TokenClaims = Depends(require_tenant())
        ):
            return {"tenant_id": tenant_id}
        ```

    Args:
        tenant_id_param: Name of path parameter containing tenant ID

    Returns:
        Dependency function
    """

    async def tenant_checker(request: Request, claims: TokenClaims) -> TokenClaims:
        # Get tenant_id from path parameters
        path_tenant_id = request.path_params.get(tenant_id_param)

        if (
            path_tenant_id
            and str(claims.tenant_id) != str(path_tenant_id)
            and not claims.is_admin()
        ):
            # Admin can access any tenant, others are denied
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: tenant mismatch",
            )

        return claims

    return tenant_checker


def create_auth_dependencies(
    settings: JWTSettings | None = None,
    blocklist: TokenBlocklist | None = None,
) -> tuple:
    """
    Create authentication dependencies for FastAPI.

    Returns a tuple of dependencies that can be used in routes.

    Args:
        settings: JWT configuration settings
        blocklist: Optional token blocklist

    Returns:
        Tuple of (get_current_user, get_current_user_optional, auth_middleware)

    Example:
        ```python
        from services.shared.security.jwt import create_auth_dependencies

        get_current_user, get_optional_user, auth = create_auth_dependencies()

        @app.get("/me")
        async def get_me(user: TokenClaims = Depends(get_current_user)):
            return {"user_id": str(user.sub)}
        ```
    """
    auth = JWTAuthMiddleware(settings=settings, blocklist=blocklist)

    return (
        auth.get_current_user,
        auth.get_current_user_optional,
        auth,
    )


# Convenience type aliases for dependency injection
CurrentUser = Annotated[TokenClaims, Depends(JWTAuthMiddleware().get_current_user)]
OptionalUser = Annotated[
    TokenClaims | None,
    Depends(JWTAuthMiddleware().get_current_user_optional),
]
