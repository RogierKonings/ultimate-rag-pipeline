"""FastAPI middleware and dependencies for ACL.

This module provides FastAPI integration for ACL filtering,
including dependency injection functions and middleware.
"""

from typing import Any, Callable, Optional

from fastapi import Depends, Request

from .context import UserContextExtractor
from .filter import ACLFilter
from .models import ACLFilterConfig, UserContext


class ACLMiddleware:
    """FastAPI dependency provider for ACL context injection.

    Usage:
        middleware = ACLMiddleware(extractor, acl_filter)

        @app.get("/retrieve")
        async def retrieve(
            user_context: UserContext = Depends(middleware.get_user_context)
        ):
            ...
    """

    def __init__(
        self,
        extractor: UserContextExtractor,
        acl_filter: ACLFilter,
    ):
        """Initialize ACL middleware.

        Args:
            extractor: User context extractor for JWT parsing.
            acl_filter: ACL filter for building database filters.
        """
        self.extractor = extractor
        self.acl_filter = acl_filter

    async def get_user_context(self, request: Request) -> UserContext:
        """Extract user context from request.

        This is designed to be used as a FastAPI dependency.

        Args:
            request: FastAPI request object.

        Returns:
            UserContext extracted from the request's JWT token.
        """
        return await self.extractor.extract(request)

    async def get_acl_filter(
        self,
        request: Request,
        additional_filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Get ACL filter dict for current user.

        This is designed to be used as a FastAPI dependency.

        Args:
            request: FastAPI request object.
            additional_filters: Extra filters to merge with ACL.

        Returns:
            Filter dict ready for use with Qdrant/OpenSearch.
        """
        user_context = await self.extractor.extract(request)
        return self.acl_filter.build_filter(user_context, additional_filters)


def create_acl_dependencies(
    secret_key: str,
    config: Optional[ACLFilterConfig] = None,
    algorithm: str = "HS256",
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
) -> tuple[Callable, Callable]:
    """Create FastAPI dependencies for ACL.

    Factory function that creates configured dependency functions
    for user context extraction and ACL filter building.

    Usage:
        get_user, get_filter = create_acl_dependencies("secret")

        @app.get("/retrieve")
        async def retrieve(user: UserContext = Depends(get_user)):
            ...

    Args:
        secret_key: Secret key for JWT validation.
        config: ACL filter configuration.
        algorithm: JWT algorithm (default: HS256).
        issuer: Expected token issuer (optional).
        audience: Expected token audience (optional).

    Returns:
        Tuple of (get_user_context, get_acl_filter) dependency functions.
    """
    extractor = UserContextExtractor(
        secret_key=secret_key,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )
    acl_filter = ACLFilter(config or ACLFilterConfig())
    middleware = ACLMiddleware(extractor, acl_filter)

    return middleware.get_user_context, middleware.get_acl_filter


def get_user_context_dependency(
    secret_key: str,
    algorithm: str = "HS256",
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
) -> Callable:
    """Create a standalone user context dependency.

    This is useful when you only need user context extraction
    without the full ACL filter.

    Args:
        secret_key: Secret key for JWT validation.
        algorithm: JWT algorithm (default: HS256).
        issuer: Expected token issuer (optional).
        audience: Expected token audience (optional).

    Returns:
        Dependency function for FastAPI.
    """
    extractor = UserContextExtractor(
        secret_key=secret_key,
        algorithm=algorithm,
        issuer=issuer,
        audience=audience,
    )

    async def dependency(request: Request) -> UserContext:
        return await extractor.extract(request)

    return dependency
