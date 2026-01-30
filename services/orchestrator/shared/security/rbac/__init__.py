"""
RBAC (Role-Based Access Control) module for the RAG Pipeline.

This module provides role and permission management with support for
hierarchical roles, fine-grained permissions, and multi-tenancy.
"""

from .middleware import (
    require_admin,
    require_all_permissions,
    require_any_permission,
    require_any_role,
    require_permission,
    require_role,
    require_tenant_admin,
)
from .permissions import (
    ROLE_PERMISSIONS,
    Permission,
    PermissionScope,
    get_all_permissions_for_roles,
    get_role_permissions,
    has_permission,
    permission_implies,
)
from .roles import (
    Role,
    RoleHierarchy,
    get_effective_roles,
    has_role_or_higher,
)
from .service import (
    AuthorizationError,
    AuthorizationService,
    InsufficientPermissionsError,
    TenantMismatchError,
)
from .tenant import (
    TenantContext,
    TenantContextManager,
    get_current_tenant,
)

__all__ = [
    # Permissions
    "Permission",
    "PermissionScope",
    "ROLE_PERMISSIONS",
    "get_role_permissions",
    "get_all_permissions_for_roles",
    "has_permission",
    "permission_implies",
    # Roles
    "Role",
    "RoleHierarchy",
    "get_effective_roles",
    "has_role_or_higher",
    # Service
    "AuthorizationService",
    "AuthorizationError",
    "InsufficientPermissionsError",
    "TenantMismatchError",
    # Middleware
    "require_permission",
    "require_any_permission",
    "require_all_permissions",
    "require_role",
    "require_any_role",
    "require_admin",
    "require_tenant_admin",
    # Tenant
    "TenantContext",
    "TenantContextManager",
    "get_current_tenant",
]
