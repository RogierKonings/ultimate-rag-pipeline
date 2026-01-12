"""
FastAPI middleware and dependencies for RBAC authorization.

This module provides FastAPI dependency functions for enforcing
permissions and roles in route handlers.
"""

import logging
from functools import wraps
from typing import Callable, Optional, Any

from fastapi import Depends, HTTPException, Request

from .permissions import Permission
from .roles import Role
from .service import (
    AuthorizationService,
    InsufficientPermissionsError,
    TenantMismatchError,
    get_authorization_service,
)

logger = logging.getLogger(__name__)


def _get_user_from_request(request: Request) -> Any:
    """
    Extract user from request state.

    The JWT middleware should set request.state.user.

    Args:
        request: FastAPI request object.

    Returns:
        User identity object.

    Raises:
        HTTPException: 401 if user not found.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )
    return user


def require_permission(
    permission: Permission | str,
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    FastAPI dependency that requires a specific permission.

    Usage:
        ```python
        @router.get("/documents")
        async def list_documents(
            _auth: None = Depends(require_permission(Permission.DOCUMENTS_READ))
        ):
            ...
        ```

    Args:
        permission: Required permission.
        auth_service: Authorization service instance (uses default if None).

    Returns:
        FastAPI dependency function.
    """
    service = auth_service or get_authorization_service()

    async def dependency(request: Request) -> None:
        user = _get_user_from_request(request)
        try:
            service.authorize_permission(user, permission)
        except InsufficientPermissionsError as e:
            raise HTTPException(
                status_code=403,
                detail=e.message,
            )

    return dependency


def require_any_permission(
    *permissions: Permission | str,
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    FastAPI dependency that requires any one of the permissions.

    Usage:
        ```python
        @router.get("/data")
        async def get_data(
            _auth: None = Depends(require_any_permission(
                Permission.DOCUMENTS_READ,
                Permission.ANALYTICS_READ
            ))
        ):
            ...
        ```

    Args:
        permissions: Required permissions (any one).
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    service = auth_service or get_authorization_service()

    async def dependency(request: Request) -> None:
        user = _get_user_from_request(request)
        try:
            service.authorize_any_permission(user, list(permissions))
        except InsufficientPermissionsError as e:
            raise HTTPException(
                status_code=403,
                detail=e.message,
            )

    return dependency


def require_all_permissions(
    *permissions: Permission | str,
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    FastAPI dependency that requires all of the permissions.

    Usage:
        ```python
        @router.post("/admin/config")
        async def update_config(
            _auth: None = Depends(require_all_permissions(
                Permission.SYSTEM_ADMIN,
                Permission.SECRETS_WRITE
            ))
        ):
            ...
        ```

    Args:
        permissions: Required permissions (all).
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    service = auth_service or get_authorization_service()

    async def dependency(request: Request) -> None:
        user = _get_user_from_request(request)
        try:
            service.authorize_all_permissions(user, list(permissions))
        except InsufficientPermissionsError as e:
            raise HTTPException(
                status_code=403,
                detail=e.message,
            )

    return dependency


def require_role(
    role: str | Role,
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    FastAPI dependency that requires a specific role.

    Usage:
        ```python
        @router.get("/admin")
        async def admin_panel(
            _auth: None = Depends(require_role(Role.ADMIN))
        ):
            ...
        ```

    Args:
        role: Required role.
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    service = auth_service or get_authorization_service()

    async def dependency(request: Request) -> None:
        user = _get_user_from_request(request)
        try:
            service.authorize_role(user, role)
        except InsufficientPermissionsError as e:
            raise HTTPException(
                status_code=403,
                detail=e.message,
            )

    return dependency


def require_any_role(
    *roles: str | Role,
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    FastAPI dependency that requires any one of the roles.

    Usage:
        ```python
        @router.get("/manage")
        async def manage_resources(
            _auth: None = Depends(require_any_role(
                Role.ADMIN,
                Role.TENANT_ADMIN
            ))
        ):
            ...
        ```

    Args:
        roles: Required roles (any one).
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    service = auth_service or get_authorization_service()

    async def dependency(request: Request) -> None:
        user = _get_user_from_request(request)
        if not service.has_any_role(user, list(roles)):
            role_strs = [r.value if isinstance(r, Role) else r for r in roles]
            raise HTTPException(
                status_code=403,
                detail=f"Required one of roles: {', '.join(role_strs)}",
            )

    return dependency


def require_admin(
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    Shortcut dependency that requires admin role.

    Usage:
        ```python
        @router.delete("/users/{user_id}")
        async def delete_user(
            user_id: str,
            _auth: None = Depends(require_admin())
        ):
            ...
        ```

    Args:
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    return require_any_role(
        Role.ADMIN,
        Role.SUPER_ADMIN,
        auth_service=auth_service,
    )


def require_tenant_admin(
    auth_service: Optional[AuthorizationService] = None,
) -> Callable:
    """
    Shortcut dependency that requires tenant admin or higher.

    Args:
        auth_service: Authorization service instance.

    Returns:
        FastAPI dependency function.
    """
    return require_any_role(
        Role.TENANT_ADMIN,
        Role.ADMIN,
        Role.SUPER_ADMIN,
        auth_service=auth_service,
    )


class PermissionChecker:
    """
    Class-based permission checker for complex authorization logic.

    Usage:
        ```python
        checker = PermissionChecker(Permission.DOCUMENTS_WRITE)

        @router.post("/documents")
        async def create_document(
            authorized: bool = Depends(checker)
        ):
            if not authorized:
                raise HTTPException(403)
            ...
        ```
    """

    def __init__(
        self,
        permission: Permission | str,
        auth_service: Optional[AuthorizationService] = None,
        raise_on_deny: bool = True,
    ):
        """
        Initialize permission checker.

        Args:
            permission: Required permission.
            auth_service: Authorization service instance.
            raise_on_deny: Raise exception if denied (default True).
        """
        self.permission = permission
        self.auth_service = auth_service or get_authorization_service()
        self.raise_on_deny = raise_on_deny

    async def __call__(self, request: Request) -> bool:
        """Check permission for request."""
        user = _get_user_from_request(request)
        has_perm = self.auth_service.has_permission(user, self.permission)

        if not has_perm and self.raise_on_deny:
            perm_str = (
                self.permission.value
                if isinstance(self.permission, Permission)
                else self.permission
            )
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {perm_str}",
            )

        return has_perm


class TenantAccessChecker:
    """
    Dependency for checking tenant access to a resource.

    Extracts tenant_id from path parameters and validates access.

    Usage:
        ```python
        @router.get("/tenants/{tenant_id}/documents")
        async def list_tenant_documents(
            tenant_id: UUID,
            _access: None = Depends(TenantAccessChecker())
        ):
            ...
        ```
    """

    def __init__(
        self,
        tenant_param: str = "tenant_id",
        auth_service: Optional[AuthorizationService] = None,
    ):
        """
        Initialize tenant access checker.

        Args:
            tenant_param: Name of the tenant_id path parameter.
            auth_service: Authorization service instance.
        """
        self.tenant_param = tenant_param
        self.auth_service = auth_service or get_authorization_service()

    async def __call__(self, request: Request) -> None:
        """Check tenant access for request."""
        from uuid import UUID

        user = _get_user_from_request(request)

        # Get tenant_id from path parameters
        tenant_id_str = request.path_params.get(self.tenant_param)
        if not tenant_id_str:
            raise HTTPException(
                status_code=400,
                detail=f"Missing {self.tenant_param} parameter",
            )

        try:
            tenant_id = UUID(tenant_id_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {self.tenant_param} format",
            )

        try:
            self.auth_service.authorize_tenant_access(user, tenant_id)
        except TenantMismatchError as e:
            raise HTTPException(
                status_code=403,
                detail=e.message,
            )


def authorize(
    permission: Optional[Permission | str] = None,
    role: Optional[str | Role] = None,
    check_tenant: bool = False,
    tenant_param: str = "tenant_id",
) -> Callable:
    """
    Decorator for combining multiple authorization checks.

    Usage:
        ```python
        @router.put("/tenants/{tenant_id}/documents/{doc_id}")
        @authorize(
            permission=Permission.DOCUMENTS_WRITE,
            check_tenant=True
        )
        async def update_document(...):
            ...
        ```

    Args:
        permission: Required permission (optional).
        role: Required role (optional).
        check_tenant: Whether to check tenant access.
        tenant_param: Name of tenant_id parameter.

    Returns:
        Decorator function.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request")
            if request is None:
                # Try to find request in args
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is None:
                raise RuntimeError(
                    "@authorize decorator requires 'request' parameter"
                )

            service = get_authorization_service()
            user = _get_user_from_request(request)

            # Check permission
            if permission is not None:
                try:
                    service.authorize_permission(user, permission)
                except InsufficientPermissionsError as e:
                    raise HTTPException(status_code=403, detail=e.message)

            # Check role
            if role is not None:
                try:
                    service.authorize_role(user, role)
                except InsufficientPermissionsError as e:
                    raise HTTPException(status_code=403, detail=e.message)

            # Check tenant access
            if check_tenant:
                from uuid import UUID

                tenant_id_str = request.path_params.get(tenant_param)
                if tenant_id_str:
                    try:
                        tenant_id = UUID(tenant_id_str)
                        service.authorize_tenant_access(user, tenant_id)
                    except TenantMismatchError as e:
                        raise HTTPException(status_code=403, detail=e.message)
                    except ValueError:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid {tenant_param} format",
                        )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
