"""
Authentication API router.

This module provides FastAPI endpoints for JWT authentication:
- POST /auth/token - Obtain tokens
- POST /auth/refresh - Refresh tokens
- POST /auth/logout - Revoke tokens
- POST /auth/introspect - Token introspection
"""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..jwt import (
    JWTHandler,
    JWTSettings,
    TokenClaims,
    TokenType,
)
from ..jwt.handler import (
    JWTError,
    TokenBlocklist,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from ..jwt.models import (
    TokenIntrospectionResponse,
    TokenRequest,
    TokenRevocationRequest,
)


class AuthResponse(BaseModel):
    """Authentication response with tokens."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration in seconds")


class LogoutResponse(BaseModel):
    """Logout response."""

    success: bool = Field(..., description="Whether logout was successful")
    message: str = Field(default="Successfully logged out", description="Status message")


class ErrorResponse(BaseModel):
    """Error response for authentication failures."""

    error: str = Field(..., description="Error code")
    error_description: str = Field(..., description="Human-readable error description")


# Type for user lookup function
UserLookupFunc = Callable[[str, str], tuple[UUID, UUID, list[str], list[str]] | None]


def create_auth_router(
    settings: JWTSettings | None = None,
    handler: JWTHandler | None = None,
    blocklist: TokenBlocklist | None = None,
    user_lookup: UserLookupFunc | None = None,
    prefix: str = "/auth",
    tags: list[str] | None = None,
) -> APIRouter:
    """
    Create authentication router.

    Args:
        settings: JWT configuration settings
        handler: Pre-configured JWT handler
        blocklist: Token blocklist for revocation
        user_lookup: Function to lookup user by username/password.
                    Returns (user_id, tenant_id, roles, groups) or None.
        prefix: URL prefix for auth routes
        tags: OpenAPI tags

    Returns:
        Configured FastAPI router

    Example:
        ```python
        from services.shared.security.api import create_auth_router

        async def lookup_user(username: str, password: str):
            user = await db.get_user_by_credentials(username, password)
            if user:
                return (user.id, user.tenant_id, user.roles, user.groups)
            return None

        auth_router = create_auth_router(user_lookup=lookup_user)
        app.include_router(auth_router, prefix="/api/v1")
        ```
    """
    router = APIRouter(prefix=prefix, tags=tags or ["Authentication"])

    # Initialize JWT handler
    jwt_settings = settings or JWTSettings()
    jwt_handler = handler or JWTHandler(jwt_settings, blocklist)

    @router.post(
        "/token",
        response_model=AuthResponse,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid request"},
            401: {"model": ErrorResponse, "description": "Authentication failed"},
        },
        summary="Obtain access token",
        description="Authenticate and obtain JWT tokens using various grant types.",
    )
    async def obtain_token(
        request: Request,
        token_request: TokenRequest,
    ) -> AuthResponse:
        """
        Obtain JWT tokens.

        Supports grant types:
        - password: Username/password authentication
        - refresh_token: Token refresh
        - client_credentials: Service-to-service auth
        """
        if token_request.grant_type == "password":
            return await _handle_password_grant(
                token_request, jwt_handler, user_lookup,
            )
        if token_request.grant_type == "refresh_token":
            return await _handle_refresh_grant(token_request, jwt_handler)
        if token_request.grant_type == "client_credentials":
            return await _handle_client_credentials_grant(
                token_request, jwt_handler, user_lookup,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unsupported_grant_type", "error_description": f"Grant type '{token_request.grant_type}' not supported"},
        )

    @router.post(
        "/refresh",
        response_model=AuthResponse,
        responses={
            401: {"model": ErrorResponse, "description": "Invalid refresh token"},
        },
        summary="Refresh access token",
        description="Obtain new tokens using a valid refresh token.",
    )
    async def refresh_token(
        request: Request,
        refresh_token: str = None,
    ) -> AuthResponse:
        """Refresh tokens using a refresh token."""
        # Get refresh token from body or cookie
        token = refresh_token
        if not token:
            token = request.cookies.get("refresh_token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_request", "error_description": "Missing refresh_token"},
            )

        try:
            token_pair = jwt_handler.refresh_tokens(token)
            return AuthResponse(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                token_type=token_pair.token_type,
                expires_in=token_pair.expires_in,
            )
        except TokenExpiredError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_grant", "error_description": "Refresh token has expired"},
            ) from None
        except (TokenInvalidError, TokenRevokedError) as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_grant", "error_description": str(e)},
            ) from e

    @router.post(
        "/logout",
        response_model=LogoutResponse,
        summary="Logout and revoke tokens",
        description="Revoke the current access and refresh tokens.",
    )
    async def logout(
        request: Request,
        response: Response,
        revocation: TokenRevocationRequest | None = None,
    ) -> LogoutResponse:
        """Revoke tokens and logout."""
        # Get token from request body, header, or cookie
        token = None
        if revocation and revocation.token:
            token = revocation.token
        else:
            # Try Authorization header
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                # Try cookie
                token = request.cookies.get("access_token")

        if token:
            jwt_handler.revoke_token(token)

        # Also revoke refresh token if available
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token:
            jwt_handler.revoke_token(refresh_token)

        # Clear cookies
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")

        return LogoutResponse(success=True, message="Successfully logged out")

    @router.post(
        "/introspect",
        response_model=TokenIntrospectionResponse,
        summary="Introspect token",
        description="Get information about a token's validity and claims.",
    )
    async def introspect_token(
        token: str,
        token_type_hint: str | None = None,
    ) -> TokenIntrospectionResponse:
        """
        Introspect a token (RFC 7662).

        Returns token validity and claims.
        """
        try:
            expected_type = None
            if token_type_hint == "access_token":
                expected_type = TokenType.ACCESS
            elif token_type_hint == "refresh_token":
                expected_type = TokenType.REFRESH

            claims = jwt_handler.verify_token(token, expected_type=expected_type)

            return TokenIntrospectionResponse(
                active=True,
                sub=str(claims.sub),
                token_type=claims.token_type.value,
                exp=int(claims.exp.timestamp()) if claims.exp else None,
                iat=int(claims.iat.timestamp()) if claims.iat else None,
                nbf=int(claims.nbf.timestamp()) if claims.nbf else None,
                aud=claims.aud,
                iss=claims.iss,
                jti=claims.jti,
                tenant_id=str(claims.tenant_id),
                roles=claims.roles,
                groups=claims.groups,
            )
        except JWTError:
            return TokenIntrospectionResponse(active=False)

    return router


async def _handle_password_grant(
    request: TokenRequest,
    handler: JWTHandler,
    user_lookup: UserLookupFunc | None,
) -> AuthResponse:
    """Handle password grant type."""
    if not request.username or not request.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "error_description": "Missing username or password"},
        )

    if not user_lookup:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"error": "server_error", "error_description": "User authentication not configured"},
        )

    # Lookup user
    result = await user_lookup(request.username, request.password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_grant", "error_description": "Invalid username or password"},
        )

    user_id, tenant_id, roles, groups = result

    # Create token claims
    claims = TokenClaims(
        sub=user_id,
        tenant_id=tenant_id,
        roles=roles,
        groups=groups,
        email=request.username if "@" in request.username else None,
    )

    # Create token pair
    token_pair = handler.create_token_pair(claims)

    return AuthResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
    )


async def _handle_refresh_grant(
    request: TokenRequest,
    handler: JWTHandler,
) -> AuthResponse:
    """Handle refresh_token grant type."""
    if not request.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "error_description": "Missing refresh_token"},
        )

    try:
        token_pair = handler.refresh_tokens(request.refresh_token)
        return AuthResponse(
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            token_type=token_pair.token_type,
            expires_in=token_pair.expires_in,
        )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_grant", "error_description": "Refresh token has expired"},
        ) from None
    except (TokenInvalidError, TokenRevokedError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_grant", "error_description": str(e)},
        ) from e


async def _handle_client_credentials_grant(
    request: TokenRequest,
    handler: JWTHandler,
    user_lookup: UserLookupFunc | None,
) -> AuthResponse:
    """Handle client_credentials grant type for service-to-service auth."""
    if not request.client_id or not request.client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "error_description": "Missing client_id or client_secret"},
        )

    if not user_lookup:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"error": "server_error", "error_description": "Client authentication not configured"},
        )

    # Use same lookup function for client credentials
    result = await user_lookup(request.client_id, request.client_secret)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_client", "error_description": "Invalid client credentials"},
        )

    user_id, tenant_id, roles, groups = result

    # Create token claims for service account
    claims = TokenClaims(
        sub=user_id,
        tenant_id=tenant_id,
        roles=roles + ["service_account"],
        groups=groups,
    )

    # Create token pair
    token_pair = handler.create_token_pair(claims)

    return AuthResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
    )
