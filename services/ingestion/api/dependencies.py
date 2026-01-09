"""FastAPI dependencies for dependency injection."""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> dict:
    """
    Extract and validate user from JWT token.

    Token structure (per architecture):
    {
        "sub": "user-uuid",
        "tenant_id": "tenant-uuid",
        "groups": ["group-1", "group-2"],
        "roles": ["user", "admin"],
        "permissions": ["read:documents", "write:documents"]
    }

    Returns:
        Dict containing user claims from the JWT token.

    Raises:
        HTTPException: If authentication fails.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        from jose import JWTError, jwt

        settings = get_settings()
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload

    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_permission(permission: str):
    """
    Dependency factory to require a specific permission.

    Args:
        permission: The permission string required (e.g., "write:documents").

    Returns:
        A dependency that validates the user has the required permission.
    """

    async def check_permission(user: dict = Depends(get_current_user)) -> dict:
        """Check that user has the required permission."""
        permissions = user.get("permissions", [])
        if permission not in permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required",
            )
        return user

    return check_permission


async def get_job_tracker():
    """
    Get job status tracker instance.

    Returns:
        Connected JobStatusTracker instance.
    """
    from tasks.status import JobStatusTracker

    tracker = JobStatusTracker()
    await tracker.connect()
    try:
        yield tracker
    finally:
        await tracker.disconnect()


async def get_document_service():
    """
    Get document service instance.

    Returns:
        DocumentService instance with database connection.
    """
    from services.documents import DocumentService

    service = DocumentService()
    await service.connect()
    try:
        yield service
    finally:
        await service.disconnect()
