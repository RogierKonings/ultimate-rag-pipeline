"""Dependency injection for API routes."""

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status

from acl.context import UserContextExtractor
from acl.models import UserContext


async def get_user_context(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
) -> UserContext:
    """
    Extract user context from JWT in Authorization header.

    For anonymous requests (no token), returns a default user context
    with limited access.

    Args:
        request: FastAPI request
        authorization: Authorization header value

    Returns:
        UserContext extracted from JWT or default for anonymous

    Raises:
        HTTPException: If token is invalid
    """
    extractor: UserContextExtractor = request.app.state.user_extractor

    if not authorization:
        # Anonymous access - return limited context
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
        )


# Type alias for dependency
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
