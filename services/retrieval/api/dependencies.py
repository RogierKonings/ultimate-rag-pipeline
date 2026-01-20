"""Dependency injection for API routes."""

from typing import Annotated
from uuid import UUID

from acl.context import UserContextExtractor
from acl.models import UserContext
from fastapi import Depends, Header, HTTPException, Request, status


async def get_user_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> UserContext:
    """
    Extract user context from JWT in Authorization header.

    For anonymous requests (no token), returns a default user context
    with limited access. If X-Tenant-Id header is provided (for internal
    service-to-service calls), uses that tenant for anonymous access.

    Args:
        request: FastAPI request
        authorization: Authorization header value
        x_tenant_id: Optional tenant ID header for internal calls

    Returns:
        UserContext extracted from JWT or default for anonymous

    Raises:
        HTTPException: If token is invalid
    """
    extractor: UserContextExtractor = request.app.state.user_extractor

    if not authorization:
        # Anonymous access - use tenant from header if provided
        if x_tenant_id:
            try:
                tenant_uuid = UUID(x_tenant_id)
                return UserContext.for_tenant(tenant_uuid)
            except ValueError:
                pass  # Fall through to default anonymous
        return UserContext.anonymous()

    # Extract Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]  # Remove "Bearer " prefix

    try:
        return await extractor.extract_from_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# Type alias for dependency
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
