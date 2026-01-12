"""
Tenant context management for multi-tenancy.

This module provides context management for tenant isolation,
ensuring all operations are scoped to the correct tenant.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Context variable for tenant context
_current_tenant: ContextVar[Optional["TenantContext"]] = ContextVar(
    "current_tenant",
    default=None,
)


@dataclass
class TenantContext:
    """
    Tenant context for multi-tenant operations.

    Contains tenant identity and configuration for request-scoped
    tenant isolation.

    Example:
        ```python
        from services.shared.security.rbac import TenantContext, get_current_tenant

        # Get current tenant
        tenant = get_current_tenant()
        if tenant:
            print(f"Operating in tenant: {tenant.tenant_id}")

        # Use in database queries
        query = select(Document).where(Document.tenant_id == tenant.tenant_id)
        ```
    """

    tenant_id: UUID
    tenant_name: str | None = None
    is_super_tenant: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Tenant-specific settings
    settings: dict[str, Any] = field(default_factory=dict)

    # Tenant limits and quotas
    max_documents: int | None = None
    max_storage_bytes: int | None = None
    max_users: int | None = None

    # Feature flags for tenant
    features: set[str] = field(default_factory=set)

    def has_feature(self, feature: str) -> bool:
        """Check if tenant has a feature enabled."""
        return feature in self.features

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a tenant-specific setting."""
        return self.settings.get(key, default)


class TenantContextManager:
    """
    Manager for tenant context lifecycle.

    Provides methods to set, get, and clear tenant context for
    the current request/task.

    Usage:
        ```python
        from services.shared.security.rbac import TenantContextManager

        manager = TenantContextManager()

        # Set tenant context
        with manager.tenant_scope(tenant_id):
            # All operations in this block are scoped to tenant
            ...

        # Or manually
        manager.set_tenant(TenantContext(tenant_id=tenant_id))
        try:
            # Operations...
        finally:
            manager.clear()
        ```
    """

    def __init__(
        self,
        default_tenant_id: UUID | None = None,
        super_tenant_id: UUID | None = None,
    ):
        """
        Initialize tenant context manager.

        Args:
            default_tenant_id: Default tenant ID if none is set.
            super_tenant_id: ID of the super tenant (can access all tenants).
        """
        self._default_tenant_id = default_tenant_id
        self._super_tenant_id = super_tenant_id

    def set_tenant(self, context: TenantContext) -> None:
        """
        Set the current tenant context.

        Args:
            context: TenantContext to set.
        """
        _current_tenant.set(context)
        logger.debug(f"Set tenant context: {context.tenant_id}")

    def get_tenant(self) -> TenantContext | None:
        """
        Get the current tenant context.

        Returns:
            Current TenantContext or None.
        """
        return _current_tenant.get()

    def get_tenant_id(self) -> UUID | None:
        """
        Get the current tenant ID.

        Returns:
            Current tenant ID or None.
        """
        context = self.get_tenant()
        return context.tenant_id if context else self._default_tenant_id

    def require_tenant(self) -> TenantContext:
        """
        Get current tenant context, raising if not set.

        Returns:
            Current TenantContext.

        Raises:
            RuntimeError: If no tenant context is set.
        """
        context = self.get_tenant()
        if context is None:
            raise RuntimeError("No tenant context set for operation")
        return context

    def clear(self) -> None:
        """Clear the current tenant context."""
        _current_tenant.set(None)
        logger.debug("Cleared tenant context")

    def tenant_scope(
        self,
        tenant_id: UUID,
        tenant_name: str | None = None,
        settings: dict | None = None,
        features: set[str] | None = None,
    ):
        """
        Context manager for scoped tenant operations.

        Args:
            tenant_id: Tenant ID for the scope.
            tenant_name: Optional tenant name.
            settings: Optional tenant settings.
            features: Optional enabled features.

        Returns:
            Context manager.

        Usage:
            ```python
            async with manager.tenant_scope(tenant_id):
                # All operations scoped to tenant
                documents = await get_documents()
            ```
        """
        return _TenantScope(
            self,
            TenantContext(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                is_super_tenant=tenant_id == self._super_tenant_id,
                settings=settings or {},
                features=features or set(),
            ),
        )

    def is_super_tenant(self, tenant_id: UUID) -> bool:
        """Check if a tenant ID is the super tenant."""
        return tenant_id == self._super_tenant_id


class _TenantScope:
    """Context manager for tenant scope."""

    def __init__(self, manager: TenantContextManager, context: TenantContext):
        self._manager = manager
        self._context = context
        self._previous: TenantContext | None = None

    def __enter__(self) -> TenantContext:
        self._previous = self._manager.get_tenant()
        self._manager.set_tenant(self._context)
        return self._context

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._previous is not None:
            self._manager.set_tenant(self._previous)
        else:
            self._manager.clear()

    async def __aenter__(self) -> TenantContext:
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)


# Global tenant context manager
_tenant_manager: TenantContextManager | None = None


def get_tenant_manager() -> TenantContextManager:
    """Get or create the global tenant context manager."""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantContextManager()
    return _tenant_manager


def configure_tenant_manager(
    default_tenant_id: UUID | None = None,
    super_tenant_id: UUID | None = None,
) -> TenantContextManager:
    """
    Configure the global tenant context manager.

    Args:
        default_tenant_id: Default tenant ID.
        super_tenant_id: Super tenant ID.

    Returns:
        Configured TenantContextManager.
    """
    global _tenant_manager
    _tenant_manager = TenantContextManager(
        default_tenant_id=default_tenant_id,
        super_tenant_id=super_tenant_id,
    )
    return _tenant_manager


def get_current_tenant() -> TenantContext | None:
    """
    Get the current tenant context.

    Convenience function for accessing tenant context.

    Returns:
        Current TenantContext or None.
    """
    return get_tenant_manager().get_tenant()


def get_current_tenant_id() -> UUID | None:
    """
    Get the current tenant ID.

    Returns:
        Current tenant ID or None.
    """
    return get_tenant_manager().get_tenant_id()


def require_current_tenant() -> TenantContext:
    """
    Get current tenant, raising if not set.

    Returns:
        Current TenantContext.

    Raises:
        RuntimeError: If no tenant is set.
    """
    return get_tenant_manager().require_tenant()


# FastAPI dependency for tenant context
async def get_tenant_from_request(request) -> TenantContext:
    """
    FastAPI dependency to get tenant context from request.

    Extracts tenant from authenticated user or path parameter.

    Args:
        request: FastAPI request object.

    Returns:
        TenantContext for the request.

    Raises:
        HTTPException: 400 if tenant cannot be determined.
    """
    from fastapi import HTTPException

    # First, try to get from authenticated user
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "tenant_id"):
        return TenantContext(
            tenant_id=user.tenant_id,
            tenant_name=getattr(user, "tenant_name", None),
        )

    # Try path parameter
    tenant_id_str = request.path_params.get("tenant_id")
    if tenant_id_str:
        try:
            return TenantContext(tenant_id=UUID(tenant_id_str))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid tenant_id format",
            ) from None

    # Try query parameter
    tenant_id_str = request.query_params.get("tenant_id")
    if tenant_id_str:
        try:
            return TenantContext(tenant_id=UUID(tenant_id_str))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid tenant_id format",
            ) from None

    # Try header
    tenant_id_str = request.headers.get("X-Tenant-ID")
    if tenant_id_str:
        try:
            return TenantContext(tenant_id=UUID(tenant_id_str))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid X-Tenant-ID header",
            ) from None

    raise HTTPException(
        status_code=400,
        detail="Tenant context required but not found",
    )


class TenantMiddleware:
    """
    ASGI middleware for tenant context injection.

    Extracts tenant context from the request and sets it for
    the duration of the request.

    Usage:
        ```python
        from fastapi import FastAPI
        from services.shared.security.rbac import TenantMiddleware

        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        ```
    """

    def __init__(
        self,
        app,
        tenant_header: str = "X-Tenant-ID",
        require_tenant: bool = False,
    ):
        """
        Initialize tenant middleware.

        Args:
            app: ASGI application.
            tenant_header: Header name for tenant ID.
            require_tenant: Whether to require tenant on all requests.
        """
        self.app = app
        self.tenant_header = tenant_header
        self.require_tenant = require_tenant
        self._manager = get_tenant_manager()

    async def __call__(self, scope, receive, send):
        """ASGI entrypoint."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract tenant from headers
        headers = dict(scope.get("headers", []))
        tenant_id_bytes = headers.get(self.tenant_header.lower().encode())

        if tenant_id_bytes:
            try:
                tenant_id = UUID(tenant_id_bytes.decode())
                context = TenantContext(tenant_id=tenant_id)
                self._manager.set_tenant(context)
            except ValueError:
                # Invalid tenant ID, continue without context
                pass

        try:
            await self.app(scope, receive, send)
        finally:
            self._manager.clear()
