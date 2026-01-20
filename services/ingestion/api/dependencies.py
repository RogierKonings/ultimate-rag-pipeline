"""FastAPI dependencies for dependency injection."""

import logging
import os
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rate_limiting.limiter import IngestionRateLimiter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings

logger = logging.getLogger(__name__)

# Singleton database engine and session factory
_async_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_async_engine():
    """Get or create the async database engine."""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        db_url = settings.database_url
        if not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        _async_engine = create_async_engine(db_url, echo=settings.debug)
    return _async_engine


def _get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        engine = _get_async_engine()
        _async_session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.

    Yields:
        AsyncSession for database operations.
    """
    session_factory = _get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Singleton rate limiter for API
_api_redis_client: aioredis.Redis | None = None
_api_rate_limiter: IngestionRateLimiter | None = None

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
    tenant_id: str | None = None,
) -> dict:
    """
    Extract and validate user from JWT token.

    In debug mode, allows unauthenticated requests with tenant_id query param.

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
    settings = get_settings()

    # Dev mode bypass: allow tenant_id query param when debug is enabled
    if settings.debug and credentials is None and tenant_id:
        logger.debug(f"Dev mode: using tenant_id from query param: {tenant_id}")
        return {
            "sub": "dev-user",
            "tenant_id": tenant_id,
            "groups": [],
            "roles": ["admin"],
            "permissions": ["read:documents", "write:documents", "delete:documents"],
        }

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        from jose import JWTError, jwt

        token = credentials.credentials
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


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


async def get_rate_limiter() -> IngestionRateLimiter:
    """
    Get rate limiter instance for admin API endpoints.

    Returns:
        IngestionRateLimiter instance with Redis connection.
    """
    global _api_redis_client, _api_rate_limiter

    if _api_rate_limiter is None:
        settings = get_settings()
        redis_url = settings.redis_url
        default_max = int(os.getenv("RATE_LIMIT_DEFAULT_MAX_CONCURRENT", "10"))
        _api_redis_client = aioredis.from_url(redis_url)
        _api_rate_limiter = IngestionRateLimiter(_api_redis_client, default_max)

    return _api_rate_limiter


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that requires admin role.

    Args:
        user: Current user from JWT token.

    Returns:
        User dict if admin.

    Raises:
        HTTPException: If user is not an admin.
    """
    roles = user.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Admin role required",
        )
    return user
