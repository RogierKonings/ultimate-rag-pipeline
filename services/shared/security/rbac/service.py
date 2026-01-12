"""
Authorization service for RBAC.

This module provides the core authorization service that checks
permissions and enforces access control policies.
"""

import logging
from typing import Optional, Protocol
from uuid import UUID

from .permissions import (
    Permission,
    get_all_permissions_for_roles,
    has_permission,
    permission_implies,
)
from .roles import Role, RoleHierarchy, get_effective_roles, has_role_or_higher

logger = logging.getLogger(__name__)


class AuthorizationError(Exception):
    """Base exception for authorization errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InsufficientPermissionsError(AuthorizationError):
    """Raised when user lacks required permissions."""

    def __init__(
        self,
        required: str | list[str],
        user_id: Optional[UUID] = None,
        details: Optional[dict] = None,
    ):
        required_str = required if isinstance(required, str) else ", ".join(required)
        message = f"Insufficient permissions. Required: {required_str}"
        super().__init__(message, details)
        self.required = required
        self.user_id = user_id


class TenantMismatchError(AuthorizationError):
    """Raised when user attempts cross-tenant access."""

    def __init__(
        self,
        user_tenant: UUID,
        resource_tenant: UUID,
        details: Optional[dict] = None,
    ):
        message = f"Tenant mismatch: user tenant {user_tenant} cannot access tenant {resource_tenant}"
        super().__init__(message, details)
        self.user_tenant = user_tenant
        self.resource_tenant = resource_tenant


class RoleNotFoundError(AuthorizationError):
    """Raised when a specified role does not exist."""

    def __init__(self, role: str, details: Optional[dict] = None):
        message = f"Role not found: {role}"
        super().__init__(message, details)
        self.role = role


class UserIdentity(Protocol):
    """Protocol for user identity objects."""

    @property
    def sub(self) -> UUID:
        """User ID."""
        ...

    @property
    def tenant_id(self) -> UUID:
        """Tenant ID."""
        ...

    @property
    def roles(self) -> list[str]:
        """User's roles."""
        ...

    @property
    def permissions(self) -> list[str]:
        """User's explicit permissions."""
        ...

    @property
    def groups(self) -> list[str]:
        """User's groups."""
        ...


class AuthorizationService:
    """
    Core authorization service for the RAG pipeline.

    Provides methods for checking permissions, roles, and tenant access.
    Can be used with dependency injection in FastAPI.

    Example:
        ```python
        from services.shared.security.rbac import AuthorizationService

        auth_service = AuthorizationService()

        # Check single permission
        if not auth_service.has_permission(user, Permission.DOCUMENTS_READ):
            raise HTTPException(status_code=403, detail="Access denied")

        # Check with tenant isolation
        auth_service.authorize_tenant_access(user, document.tenant_id)
        ```
    """

    def __init__(
        self,
        role_hierarchy: Optional[RoleHierarchy] = None,
        super_tenant_id: Optional[UUID] = None,
        admin_bypass: bool = True,
    ):
        """
        Initialize authorization service.

        Args:
            role_hierarchy: Custom role hierarchy, or use default.
            super_tenant_id: Optional super tenant that can access all tenants.
            admin_bypass: Whether admins bypass permission checks.
        """
        self._hierarchy = role_hierarchy or RoleHierarchy()
        self._super_tenant_id = super_tenant_id
        self._admin_bypass = admin_bypass

    def has_permission(
        self,
        user: UserIdentity,
        required: Permission | str,
        check_implied: bool = True,
    ) -> bool:
        """
        Check if user has a required permission.

        Args:
            user: User identity with roles and permissions.
            required: Required permission.
            check_implied: Whether to check permission implication.

        Returns:
            True if user has the permission.
        """
        # Admin bypass
        if self._admin_bypass and self._is_admin(user):
            return True

        # Convert to Permission enum if string
        required_perm = (
            required
            if isinstance(required, Permission)
            else Permission.from_string(required)
        )

        # Check explicit permissions
        if has_permission(user.permissions, required, user.roles):
            return True

        # Check role-based permissions
        role_perms = get_all_permissions_for_roles(user.roles)
        if required_perm and required_perm in role_perms:
            return True

        # Check permission implication
        if check_implied and required_perm:
            for perm in role_perms:
                if permission_implies(perm, required_perm):
                    return True

            # Check explicit permissions for implication
            for perm_str in user.permissions:
                perm = Permission.from_string(perm_str)
                if perm and permission_implies(perm, required_perm):
                    return True

        return False

    def has_any_permission(
        self,
        user: UserIdentity,
        required: list[Permission | str],
    ) -> bool:
        """
        Check if user has any of the required permissions.

        Args:
            user: User identity.
            required: List of required permissions (any one).

        Returns:
            True if user has at least one permission.
        """
        return any(self.has_permission(user, perm) for perm in required)

    def has_all_permissions(
        self,
        user: UserIdentity,
        required: list[Permission | str],
    ) -> bool:
        """
        Check if user has all of the required permissions.

        Args:
            user: User identity.
            required: List of required permissions (all).

        Returns:
            True if user has all permissions.
        """
        return all(self.has_permission(user, perm) for perm in required)

    def has_role(
        self,
        user: UserIdentity,
        required: str | Role,
        check_hierarchy: bool = True,
    ) -> bool:
        """
        Check if user has a required role.

        Args:
            user: User identity.
            required: Required role.
            check_hierarchy: Whether to check role hierarchy.

        Returns:
            True if user has the role.
        """
        required_str = required.value if isinstance(required, Role) else required

        # Direct match
        if required_str in user.roles:
            return True

        # Hierarchy check
        if check_hierarchy:
            return has_role_or_higher(user.roles, required_str)

        return False

    def has_any_role(
        self,
        user: UserIdentity,
        required: list[str | Role],
    ) -> bool:
        """
        Check if user has any of the required roles.

        Args:
            user: User identity.
            required: List of required roles (any one).

        Returns:
            True if user has at least one role.
        """
        return any(self.has_role(user, role) for role in required)

    def authorize_permission(
        self,
        user: UserIdentity,
        required: Permission | str,
    ) -> None:
        """
        Authorize user for a permission, raising exception if denied.

        Args:
            user: User identity.
            required: Required permission.

        Raises:
            InsufficientPermissionsError: If user lacks permission.
        """
        if not self.has_permission(user, required):
            required_str = required.value if isinstance(required, Permission) else required
            logger.warning(
                f"Permission denied: user={user.sub} required={required_str}"
            )
            raise InsufficientPermissionsError(
                required=required_str,
                user_id=user.sub,
                details={"roles": user.roles, "permissions": user.permissions},
            )

    def authorize_any_permission(
        self,
        user: UserIdentity,
        required: list[Permission | str],
    ) -> None:
        """
        Authorize user for any of the permissions.

        Args:
            user: User identity.
            required: List of required permissions (any one).

        Raises:
            InsufficientPermissionsError: If user lacks all permissions.
        """
        if not self.has_any_permission(user, required):
            required_strs = [
                p.value if isinstance(p, Permission) else p for p in required
            ]
            raise InsufficientPermissionsError(
                required=required_strs,
                user_id=user.sub,
            )

    def authorize_all_permissions(
        self,
        user: UserIdentity,
        required: list[Permission | str],
    ) -> None:
        """
        Authorize user for all permissions.

        Args:
            user: User identity.
            required: List of required permissions (all).

        Raises:
            InsufficientPermissionsError: If user lacks any permission.
        """
        missing = [
            p for p in required if not self.has_permission(user, p)
        ]
        if missing:
            missing_strs = [
                p.value if isinstance(p, Permission) else p for p in missing
            ]
            raise InsufficientPermissionsError(
                required=missing_strs,
                user_id=user.sub,
            )

    def authorize_role(
        self,
        user: UserIdentity,
        required: str | Role,
    ) -> None:
        """
        Authorize user for a role, raising exception if denied.

        Args:
            user: User identity.
            required: Required role.

        Raises:
            InsufficientPermissionsError: If user lacks role.
        """
        if not self.has_role(user, required):
            required_str = required.value if isinstance(required, Role) else required
            raise InsufficientPermissionsError(
                required=f"role:{required_str}",
                user_id=user.sub,
            )

    def authorize_tenant_access(
        self,
        user: UserIdentity,
        resource_tenant_id: UUID,
        allow_super_tenant: bool = True,
    ) -> None:
        """
        Authorize user to access a resource in a specific tenant.

        Args:
            user: User identity.
            resource_tenant_id: Tenant ID of the resource.
            allow_super_tenant: Whether super tenant bypasses check.

        Raises:
            TenantMismatchError: If user cannot access tenant.
        """
        # Super admin can access any tenant
        if self._admin_bypass and self._is_super_admin(user):
            return

        # Super tenant bypass
        if (
            allow_super_tenant
            and self._super_tenant_id
            and user.tenant_id == self._super_tenant_id
        ):
            return

        # Tenant must match
        if user.tenant_id != resource_tenant_id:
            logger.warning(
                f"Tenant mismatch: user={user.sub} "
                f"user_tenant={user.tenant_id} "
                f"resource_tenant={resource_tenant_id}"
            )
            raise TenantMismatchError(
                user_tenant=user.tenant_id,
                resource_tenant=resource_tenant_id,
            )

    def get_effective_permissions(
        self,
        user: UserIdentity,
    ) -> set[Permission]:
        """
        Get all effective permissions for a user.

        Combines explicit permissions with role-based permissions.

        Args:
            user: User identity.

        Returns:
            Set of all effective permissions.
        """
        # Get role-based permissions
        permissions = get_all_permissions_for_roles(user.roles)

        # Add explicit permissions
        for perm_str in user.permissions:
            perm = Permission.from_string(perm_str)
            if perm:
                permissions.add(perm)

        return permissions

    def get_effective_roles(
        self,
        user: UserIdentity,
    ) -> set[str]:
        """
        Get all effective roles for a user including inherited.

        Args:
            user: User identity.

        Returns:
            Set of all effective role strings.
        """
        return get_effective_roles(user.roles)

    def _is_admin(self, user: UserIdentity) -> bool:
        """Check if user has admin role."""
        admin_roles = {"admin", "super_admin", "tenant_admin"}
        return bool(set(user.roles) & admin_roles)

    def _is_super_admin(self, user: UserIdentity) -> bool:
        """Check if user has super admin role."""
        return "super_admin" in user.roles


# Default service instance
_default_service: Optional[AuthorizationService] = None


def get_authorization_service() -> AuthorizationService:
    """Get or create the default authorization service."""
    global _default_service
    if _default_service is None:
        _default_service = AuthorizationService()
    return _default_service


def configure_authorization_service(
    super_tenant_id: Optional[UUID] = None,
    admin_bypass: bool = True,
) -> AuthorizationService:
    """
    Configure and return the authorization service.

    Args:
        super_tenant_id: Super tenant ID for cross-tenant access.
        admin_bypass: Whether admins bypass permission checks.

    Returns:
        Configured AuthorizationService instance.
    """
    global _default_service
    _default_service = AuthorizationService(
        super_tenant_id=super_tenant_id,
        admin_bypass=admin_bypass,
    )
    return _default_service
