# US-7.2: Authorization & RBAC

> **Epic:** Security & Compliance  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-7.1 (JWT Authentication)

## User Story

**As a** security engineer  
**I want** role-based access control  
**So that** users have appropriate permissions based on their roles

## Objective

Implement a comprehensive Role-Based Access Control (RBAC) system with role definitions, permission mapping, tenant isolation, group-based access, and authorization middleware for FastAPI endpoints.

## Architecture Reference

- **Model:** Role → Permissions mapping
- **Enforcement:** Middleware + decorator pattern
- **Tenant Isolation:** Mandatory tenant context on all operations
- **Hierarchy:** System roles → Tenant roles → Custom roles

## Implementation Tasks

### 1. Define Permission and Role Models

`services/shared/security/rbac/permissions.py`:

```python
from enum import Enum
from typing import Set, Dict, List
from dataclasses import dataclass


class Permission(str, Enum):
    """Fine-grained permissions for the RAG pipeline."""
    
    # Document permissions
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_CREATE = "documents:create"
    DOCUMENTS_UPDATE = "documents:update"
    DOCUMENTS_DELETE = "documents:delete"
    DOCUMENTS_ADMIN = "documents:admin"  # Full document management
    
    # Query permissions
    QUERY_EXECUTE = "query:execute"
    QUERY_HISTORY_READ = "query:history:read"
    QUERY_HISTORY_DELETE = "query:history:delete"
    
    # Ingestion permissions
    INGESTION_TRIGGER = "ingestion:trigger"
    INGESTION_STATUS = "ingestion:status"
    INGESTION_CANCEL = "ingestion:cancel"
    INGESTION_ADMIN = "ingestion:admin"
    
    # Collection permissions
    COLLECTIONS_READ = "collections:read"
    COLLECTIONS_CREATE = "collections:create"
    COLLECTIONS_UPDATE = "collections:update"
    COLLECTIONS_DELETE = "collections:delete"
    
    # User management
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_ADMIN = "users:admin"
    
    # Tenant management
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"
    TENANT_ADMIN = "tenant:admin"
    
    # API key management
    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_REVOKE = "api_keys:revoke"
    
    # Audit & compliance
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    
    # System administration
    SYSTEM_HEALTH = "system:health"
    SYSTEM_METRICS = "system:metrics"
    SYSTEM_CONFIG = "system:config"
    SYSTEM_ADMIN = "system:admin"


class Role(str, Enum):
    """Pre-defined roles with associated permissions."""
    
    # System-level roles
    SUPER_ADMIN = "super_admin"  # Full system access
    
    # Tenant-level roles
    TENANT_ADMIN = "tenant_admin"  # Full tenant access
    TENANT_USER = "tenant_user"  # Standard user
    TENANT_VIEWER = "tenant_viewer"  # Read-only access
    
    # Functional roles
    DATA_ENGINEER = "data_engineer"  # Ingestion management
    ANALYST = "analyst"  # Query and read access
    DEVELOPER = "developer"  # API integration
    COMPLIANCE_OFFICER = "compliance_officer"  # Audit access
    
    # Service accounts
    SERVICE_ACCOUNT = "service_account"  # Inter-service communication


@dataclass
class RoleDefinition:
    """Role with its permissions and metadata."""
    name: str
    description: str
    permissions: Set[Permission]
    inherits_from: List[str] = None  # Role inheritance
    is_system_role: bool = False


# Role to permissions mapping
ROLE_PERMISSIONS: Dict[Role, RoleDefinition] = {
    Role.SUPER_ADMIN: RoleDefinition(
        name="Super Admin",
        description="Full system access across all tenants",
        permissions=set(Permission),  # All permissions
        is_system_role=True,
    ),
    
    Role.TENANT_ADMIN: RoleDefinition(
        name="Tenant Admin",
        description="Full access within a tenant",
        permissions={
            Permission.DOCUMENTS_ADMIN,
            Permission.QUERY_EXECUTE,
            Permission.QUERY_HISTORY_READ,
            Permission.QUERY_HISTORY_DELETE,
            Permission.INGESTION_ADMIN,
            Permission.COLLECTIONS_READ,
            Permission.COLLECTIONS_CREATE,
            Permission.COLLECTIONS_UPDATE,
            Permission.COLLECTIONS_DELETE,
            Permission.USERS_ADMIN,
            Permission.TENANT_READ,
            Permission.TENANT_UPDATE,
            Permission.API_KEYS_READ,
            Permission.API_KEYS_CREATE,
            Permission.API_KEYS_REVOKE,
            Permission.AUDIT_READ,
            Permission.AUDIT_EXPORT,
        },
    ),
    
    Role.TENANT_USER: RoleDefinition(
        name="Tenant User",
        description="Standard user with read/write access",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.DOCUMENTS_CREATE,
            Permission.DOCUMENTS_UPDATE,
            Permission.QUERY_EXECUTE,
            Permission.QUERY_HISTORY_READ,
            Permission.INGESTION_TRIGGER,
            Permission.INGESTION_STATUS,
            Permission.COLLECTIONS_READ,
            Permission.TENANT_READ,
        },
    ),
    
    Role.TENANT_VIEWER: RoleDefinition(
        name="Tenant Viewer",
        description="Read-only access",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.QUERY_EXECUTE,
            Permission.QUERY_HISTORY_READ,
            Permission.COLLECTIONS_READ,
            Permission.TENANT_READ,
        },
    ),
    
    Role.DATA_ENGINEER: RoleDefinition(
        name="Data Engineer",
        description="Ingestion and data management",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.DOCUMENTS_CREATE,
            Permission.DOCUMENTS_UPDATE,
            Permission.DOCUMENTS_DELETE,
            Permission.INGESTION_ADMIN,
            Permission.COLLECTIONS_READ,
            Permission.COLLECTIONS_CREATE,
            Permission.COLLECTIONS_UPDATE,
            Permission.COLLECTIONS_DELETE,
            Permission.TENANT_READ,
        },
        inherits_from=[Role.TENANT_USER.value],
    ),
    
    Role.ANALYST: RoleDefinition(
        name="Analyst",
        description="Query and analytics focus",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.QUERY_EXECUTE,
            Permission.QUERY_HISTORY_READ,
            Permission.COLLECTIONS_READ,
            Permission.TENANT_READ,
            Permission.AUDIT_READ,
        },
    ),
    
    Role.DEVELOPER: RoleDefinition(
        name="Developer",
        description="API integration access",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.DOCUMENTS_CREATE,
            Permission.QUERY_EXECUTE,
            Permission.INGESTION_TRIGGER,
            Permission.INGESTION_STATUS,
            Permission.COLLECTIONS_READ,
            Permission.API_KEYS_READ,
            Permission.API_KEYS_CREATE,
            Permission.TENANT_READ,
        },
    ),
    
    Role.COMPLIANCE_OFFICER: RoleDefinition(
        name="Compliance Officer",
        description="Audit and compliance access",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.QUERY_HISTORY_READ,
            Permission.AUDIT_READ,
            Permission.AUDIT_EXPORT,
            Permission.TENANT_READ,
        },
    ),
    
    Role.SERVICE_ACCOUNT: RoleDefinition(
        name="Service Account",
        description="Inter-service communication",
        permissions={
            Permission.DOCUMENTS_READ,
            Permission.DOCUMENTS_CREATE,
            Permission.QUERY_EXECUTE,
            Permission.INGESTION_TRIGGER,
            Permission.INGESTION_STATUS,
            Permission.COLLECTIONS_READ,
            Permission.SYSTEM_HEALTH,
            Permission.SYSTEM_METRICS,
        },
        is_system_role=True,
    ),
}


def get_role_permissions(role: Role) -> Set[Permission]:
    """Get all permissions for a role, including inherited permissions."""
    definition = ROLE_PERMISSIONS.get(role)
    if not definition:
        return set()
    
    permissions = definition.permissions.copy()
    
    # Add inherited permissions
    if definition.inherits_from:
        for parent_role_name in definition.inherits_from:
            try:
                parent_role = Role(parent_role_name)
                permissions |= get_role_permissions(parent_role)
            except ValueError:
                pass
    
    return permissions


def get_permissions_for_roles(roles: List[str]) -> Set[Permission]:
    """Get combined permissions for multiple roles."""
    permissions = set()
    for role_name in roles:
        try:
            role = Role(role_name)
            permissions |= get_role_permissions(role)
        except ValueError:
            # Unknown role, skip
            pass
    return permissions
```

### 2. Create Authorization Service

`services/shared/security/rbac/service.py`:

```python
from typing import List, Set, Optional
from uuid import UUID
import structlog

from .permissions import Permission, Role, get_permissions_for_roles, get_role_permissions
from ..jwt.models import TokenClaims

logger = structlog.get_logger(__name__)


class AuthorizationError(Exception):
    """Authorization failed."""
    pass


class AuthorizationService:
    """Service for checking user permissions and authorization."""
    
    def __init__(self):
        self._permission_cache = {}
    
    def get_user_permissions(self, user: TokenClaims) -> Set[Permission]:
        """Get all effective permissions for a user."""
        # Check cache
        cache_key = (user.user_id, tuple(sorted(user.roles)))
        if cache_key in self._permission_cache:
            return self._permission_cache[cache_key]
        
        # Calculate permissions from roles
        permissions = get_permissions_for_roles(user.roles)
        
        # Add direct permissions from token
        for perm_str in user.permissions:
            try:
                permissions.add(Permission(perm_str))
            except ValueError:
                pass
        
        # Cache result
        self._permission_cache[cache_key] = permissions
        return permissions
    
    def has_permission(self, user: TokenClaims, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        permissions = self.get_user_permissions(user)
        return permission in permissions
    
    def has_any_permission(self, user: TokenClaims, permissions: List[Permission]) -> bool:
        """Check if user has any of the specified permissions."""
        user_permissions = self.get_user_permissions(user)
        return any(p in user_permissions for p in permissions)
    
    def has_all_permissions(self, user: TokenClaims, permissions: List[Permission]) -> bool:
        """Check if user has all specified permissions."""
        user_permissions = self.get_user_permissions(user)
        return all(p in user_permissions for p in permissions)
    
    def check_permission(
        self,
        user: TokenClaims,
        permission: Permission,
        resource_tenant_id: Optional[UUID] = None
    ) -> None:
        """Check permission and raise if not authorized."""
        # Check tenant isolation
        if resource_tenant_id and user.tenant_id != resource_tenant_id:
            # Only super_admin can cross tenant boundaries
            if not user.has_role(Role.SUPER_ADMIN.value):
                logger.warning(
                    "tenant_isolation_violation",
                    user_id=user.user_id,
                    user_tenant=str(user.tenant_id),
                    resource_tenant=str(resource_tenant_id),
                )
                raise AuthorizationError("Access denied: tenant isolation violation")
        
        # Check permission
        if not self.has_permission(user, permission):
            logger.warning(
                "permission_denied",
                user_id=user.user_id,
                permission=permission.value,
                user_roles=user.roles,
            )
            raise AuthorizationError(f"Access denied: missing permission {permission.value}")
    
    def check_resource_access(
        self,
        user: TokenClaims,
        resource_owner_id: str,
        resource_tenant_id: UUID,
        required_permission: Permission,
        allow_owner: bool = True
    ) -> None:
        """Check access to a specific resource."""
        # Owner always has access (if enabled)
        if allow_owner and user.user_id == resource_owner_id:
            return
        
        # Check tenant and permission
        self.check_permission(user, required_permission, resource_tenant_id)
    
    def filter_for_tenant(self, user: TokenClaims) -> dict:
        """Get filter criteria for tenant isolation."""
        if user.has_role(Role.SUPER_ADMIN.value):
            return {}  # No filter for super admin
        
        return {"tenant_id": user.tenant_id}
    
    def can_access_tenant(self, user: TokenClaims, tenant_id: UUID) -> bool:
        """Check if user can access a specific tenant."""
        if user.has_role(Role.SUPER_ADMIN.value):
            return True
        return user.tenant_id == tenant_id


# Singleton instance
_authz_service: Optional[AuthorizationService] = None

def get_authorization_service() -> AuthorizationService:
    global _authz_service
    if _authz_service is None:
        _authz_service = AuthorizationService()
    return _authz_service
```

### 3. Create Authorization Middleware

`services/shared/security/rbac/middleware.py`:

```python
from fastapi import Request, HTTPException, Depends
from functools import wraps
from typing import List, Callable, Union
import structlog

from .permissions import Permission
from .service import get_authorization_service, AuthorizationService, AuthorizationError
from ..jwt.models import TokenClaims
from ..jwt.middleware import get_current_user

logger = structlog.get_logger(__name__)


class ForbiddenError(HTTPException):
    """Access forbidden."""
    def __init__(self, detail: str = "Access denied"):
        super().__init__(status_code=403, detail=detail)


def require_permission(*permissions: Permission, require_all: bool = False):
    """
    Dependency to require specific permissions.
    
    Args:
        permissions: Required permissions
        require_all: If True, user must have ALL permissions. If False, ANY permission suffices.
    """
    async def permission_checker(
        user: TokenClaims = Depends(get_current_user),
        authz: AuthorizationService = Depends(get_authorization_service),
    ) -> TokenClaims:
        if require_all:
            if not authz.has_all_permissions(user, list(permissions)):
                raise ForbiddenError(f"Missing required permissions: {[p.value for p in permissions]}")
        else:
            if not authz.has_any_permission(user, list(permissions)):
                raise ForbiddenError(f"Missing required permission: one of {[p.value for p in permissions]}")
        
        return user
    
    return permission_checker


def require_role(*roles: str):
    """Dependency to require specific roles."""
    async def role_checker(
        user: TokenClaims = Depends(get_current_user),
    ) -> TokenClaims:
        if not user.has_any_role(list(roles)):
            raise ForbiddenError(f"Required role: one of {list(roles)}")
        return user
    
    return role_checker


def require_tenant_access(tenant_id_param: str = "tenant_id"):
    """
    Dependency to verify tenant access from path/query parameter.
    
    Usage:
        @router.get("/tenants/{tenant_id}/documents")
        async def get_docs(
            tenant_id: UUID,
            user: TokenClaims = Depends(require_tenant_access("tenant_id"))
        ):
    """
    async def tenant_checker(
        request: Request,
        user: TokenClaims = Depends(get_current_user),
        authz: AuthorizationService = Depends(get_authorization_service),
    ) -> TokenClaims:
        from uuid import UUID
        
        # Get tenant_id from path or query params
        tenant_id = request.path_params.get(tenant_id_param) or request.query_params.get(tenant_id_param)
        
        if tenant_id:
            try:
                tenant_uuid = UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
                if not authz.can_access_tenant(user, tenant_uuid):
                    raise ForbiddenError("Access denied: tenant isolation violation")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid tenant ID format")
        
        return user
    
    return tenant_checker


class PermissionChecker:
    """
    Reusable permission checker for complex authorization logic.
    
    Usage:
        checker = PermissionChecker(Permission.DOCUMENTS_READ, Permission.DOCUMENTS_ADMIN)
        
        @router.get("/documents")
        async def get_documents(
            user: TokenClaims = Depends(checker)
        ):
    """
    
    def __init__(
        self,
        *permissions: Permission,
        require_all: bool = False,
        allow_roles: List[str] = None,
    ):
        self.permissions = list(permissions)
        self.require_all = require_all
        self.allow_roles = allow_roles or []
    
    async def __call__(
        self,
        user: TokenClaims = Depends(get_current_user),
        authz: AuthorizationService = Depends(get_authorization_service),
    ) -> TokenClaims:
        # Check if user has any of the allowed roles (bypass permission check)
        if self.allow_roles and user.has_any_role(self.allow_roles):
            return user
        
        # Check permissions
        if self.require_all:
            if not authz.has_all_permissions(user, self.permissions):
                raise ForbiddenError("Insufficient permissions")
        else:
            if not authz.has_any_permission(user, self.permissions):
                raise ForbiddenError("Insufficient permissions")
        
        return user


def authorize(
    permissions: List[Permission] = None,
    roles: List[str] = None,
    require_all_permissions: bool = False,
):
    """
    Decorator for route-level authorization.
    
    Usage:
        @router.get("/admin/users")
        @authorize(permissions=[Permission.USERS_ADMIN])
        async def admin_users(request: Request):
            user = request.state.user
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get request from args/kwargs
            request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if not request or not hasattr(request.state, "user"):
                raise HTTPException(status_code=401, detail="Not authenticated")
            
            user: TokenClaims = request.state.user
            authz = get_authorization_service()
            
            # Check roles
            if roles and not user.has_any_role(roles):
                raise ForbiddenError(f"Required role: one of {roles}")
            
            # Check permissions
            if permissions:
                if require_all_permissions:
                    if not authz.has_all_permissions(user, permissions):
                        raise ForbiddenError("Insufficient permissions")
                else:
                    if not authz.has_any_permission(user, permissions):
                        raise ForbiddenError("Insufficient permissions")
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
```

### 4. Create Tenant Context Manager

`services/shared/security/rbac/tenant.py`:

```python
from contextvars import ContextVar
from typing import Optional
from uuid import UUID
from dataclasses import dataclass

from ..jwt.models import TokenClaims


@dataclass
class TenantContext:
    """Current tenant context for request processing."""
    tenant_id: UUID
    user_id: str
    user_roles: list[str]
    user_groups: list[str]


# Context variable for current tenant
_tenant_context: ContextVar[Optional[TenantContext]] = ContextVar("tenant_context", default=None)


def set_tenant_context(user: TokenClaims) -> TenantContext:
    """Set tenant context from authenticated user."""
    ctx = TenantContext(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        user_roles=user.roles,
        user_groups=user.groups,
    )
    _tenant_context.set(ctx)
    return ctx


def get_tenant_context() -> Optional[TenantContext]:
    """Get current tenant context."""
    return _tenant_context.get()


def get_current_tenant_id() -> Optional[UUID]:
    """Get current tenant ID from context."""
    ctx = get_tenant_context()
    return ctx.tenant_id if ctx else None


def require_tenant_context() -> TenantContext:
    """Get tenant context or raise error."""
    ctx = get_tenant_context()
    if not ctx:
        raise RuntimeError("Tenant context not set")
    return ctx


def clear_tenant_context() -> None:
    """Clear tenant context."""
    _tenant_context.set(None)
```

### 5. Update Database Models for RBAC

`services/shared/database/models/user.py`:

```python
from sqlalchemy import Column, String, Boolean, DateTime, JSON, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from .base import Base


# Association tables for many-to-many relationships
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
)

user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("group_id", UUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True),
)


class User(Base):
    """User model with RBAC support."""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Identity
    username = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)  # Null for SSO users
    
    # Profile
    display_name = Column(String(255))
    
    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # External identity provider
    idp_id = Column(String(255), nullable=True)  # ID from external IdP
    idp_type = Column(String(50), nullable=True)  # auth0, azure_ad, etc.
    
    # Direct permissions (in addition to role-based)
    direct_permissions = Column(ARRAY(String), default=[])
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    
    # Relationships
    roles = relationship("RoleModel", secondary=user_roles, back_populates="users")
    groups = relationship("GroupModel", secondary=user_groups, back_populates="users")
    
    def verify_password(self, password: str) -> bool:
        """Verify password hash."""
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.verify(password, self.password_hash)
    
    @property
    def role_names(self) -> list[str]:
        return [role.name for role in self.roles]
    
    @property
    def group_names(self) -> list[str]:
        return [group.name for group in self.groups]


class RoleModel(Base):
    """Role model for RBAC."""
    __tablename__ = "roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)  # Null for system roles
    
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    permissions = Column(ARRAY(String), default=[])
    is_system_role = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", secondary=user_roles, back_populates="roles")


class GroupModel(Base):
    """Group model for group-based access."""
    __tablename__ = "groups"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(String(500))
    
    # Metadata
    metadata = Column(JSON, default={})
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", secondary=user_groups, back_populates="groups")
```

### 6. Example Protected Routes

`services/api-gateway/routers/documents.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from uuid import UUID

from shared.security.jwt.models import TokenClaims
from shared.security.jwt.middleware import get_current_user
from shared.security.rbac.middleware import (
    require_permission,
    require_role,
    PermissionChecker,
    ForbiddenError,
)
from shared.security.rbac.permissions import Permission, Role
from shared.security.rbac.service import get_authorization_service

router = APIRouter(prefix="/documents", tags=["documents"])


# Simple permission check
@router.get("")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_READ)),
):
    """List documents accessible to the current user."""
    # Tenant filtering is automatic based on user context
    return {"documents": [], "total": 0, "tenant_id": str(user.tenant_id)}


# Multiple permission options (OR)
@router.post("")
async def create_document(
    user: TokenClaims = Depends(require_permission(
        Permission.DOCUMENTS_CREATE,
        Permission.DOCUMENTS_ADMIN,
    )),
):
    """Create a new document."""
    return {"message": "Document created", "owner_id": user.user_id}


# Role-based access
@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    user: TokenClaims = Depends(require_role(
        Role.TENANT_ADMIN.value,
        Role.DATA_ENGINEER.value,
    )),
):
    """Delete a document (admin/data engineer only)."""
    return {"message": f"Document {document_id} deleted"}


# Complex permission checker
document_admin_checker = PermissionChecker(
    Permission.DOCUMENTS_ADMIN,
    allow_roles=[Role.SUPER_ADMIN.value, Role.TENANT_ADMIN.value],
)


@router.post("/{document_id}/reindex")
async def reindex_document(
    document_id: UUID,
    user: TokenClaims = Depends(document_admin_checker),
):
    """Re-index a document (requires admin)."""
    return {"message": f"Document {document_id} queued for re-indexing"}


# Manual permission check with custom logic
@router.patch("/{document_id}")
async def update_document(
    document_id: UUID,
    user: TokenClaims = Depends(get_current_user),
):
    """Update document - owner or admin can update."""
    authz = get_authorization_service()
    
    # Fetch document to check ownership
    document = await get_document(document_id)  # Your repository method
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check: must be owner OR have admin permission
    is_owner = document.owner_id == user.user_id
    has_admin = authz.has_permission(user, Permission.DOCUMENTS_ADMIN)
    
    if not is_owner and not has_admin:
        raise ForbiddenError("You can only update your own documents")
    
    # Proceed with update
    return {"message": f"Document {document_id} updated"}
```

### 7. Create Tests

`tests/security/test_authorization.py`:

```python
import pytest
from uuid import uuid4

from shared.security.rbac.permissions import (
    Permission,
    Role,
    get_role_permissions,
    get_permissions_for_roles,
)
from shared.security.rbac.service import AuthorizationService
from shared.security.jwt.models import TokenClaims


@pytest.fixture
def authz_service():
    return AuthorizationService()


@pytest.fixture
def admin_user():
    return TokenClaims(
        sub="admin-user",
        iss="test",
        aud="test",
        exp=9999999999,
        iat=1000000000,
        jti=str(uuid4()),
        tenant_id=uuid4(),
        roles=[Role.TENANT_ADMIN.value],
        groups=["admins"],
        permissions=[],
    )


@pytest.fixture
def regular_user():
    return TokenClaims(
        sub="regular-user",
        iss="test",
        aud="test",
        exp=9999999999,
        iat=1000000000,
        jti=str(uuid4()),
        tenant_id=uuid4(),
        roles=[Role.TENANT_USER.value],
        groups=["users"],
        permissions=[],
    )


class TestRolePermissions:
    def test_tenant_admin_has_user_admin(self):
        permissions = get_role_permissions(Role.TENANT_ADMIN)
        assert Permission.USERS_ADMIN in permissions
    
    def test_tenant_user_cannot_delete_documents(self):
        permissions = get_role_permissions(Role.TENANT_USER)
        assert Permission.DOCUMENTS_DELETE not in permissions
    
    def test_super_admin_has_all_permissions(self):
        permissions = get_role_permissions(Role.SUPER_ADMIN)
        assert permissions == set(Permission)
    
    def test_combined_roles_merge_permissions(self):
        permissions = get_permissions_for_roles([
            Role.TENANT_USER.value,
            Role.COMPLIANCE_OFFICER.value,
        ])
        assert Permission.DOCUMENTS_READ in permissions
        assert Permission.AUDIT_EXPORT in permissions


class TestAuthorizationService:
    def test_admin_has_permission(self, authz_service, admin_user):
        assert authz_service.has_permission(admin_user, Permission.USERS_ADMIN)
    
    def test_user_lacks_admin_permission(self, authz_service, regular_user):
        assert not authz_service.has_permission(regular_user, Permission.USERS_ADMIN)
    
    def test_tenant_isolation(self, authz_service, regular_user):
        other_tenant = uuid4()
        
        with pytest.raises(Exception) as exc:
            authz_service.check_permission(
                regular_user,
                Permission.DOCUMENTS_READ,
                resource_tenant_id=other_tenant,
            )
        
        assert "tenant isolation" in str(exc.value).lower()
    
    def test_filter_for_tenant(self, authz_service, regular_user):
        filter_dict = authz_service.filter_for_tenant(regular_user)
        assert filter_dict["tenant_id"] == regular_user.tenant_id
```

## Acceptance Criteria

- [ ] Role definitions implemented (user, admin, data_engineer, etc.)
- [ ] Permission mapping to all API endpoints
- [ ] Tenant isolation enforced on all operations
- [ ] Group-based access support implemented
- [ ] Authorization middleware for FastAPI routes
- [ ] Permission inheritance from roles working
- [ ] Database models for users, roles, groups created
- [ ] Unit tests for permission checking passing
- [ ] Integration tests for protected routes passing

## Verification Commands

```bash
# Run authorization tests
pytest tests/security/test_authorization.py -v

# Test role-based endpoint access
TOKEN=$(get_user_token)  # Get token for regular user
curl -X DELETE "http://localhost:8000/documents/123" \
  -H "Authorization: Bearer $TOKEN"
# Should return 403 Forbidden

ADMIN_TOKEN=$(get_admin_token)  # Get token for admin
curl -X DELETE "http://localhost:8000/documents/123" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Should return 200 OK

# Verify tenant isolation
curl -X GET "http://localhost:8000/tenants/other-tenant-id/documents" \
  -H "Authorization: Bearer $TOKEN"
# Should return 403 Forbidden
```

## Files to Create

1. `services/shared/security/rbac/__init__.py`
2. `services/shared/security/rbac/permissions.py`
3. `services/shared/security/rbac/service.py`
4. `services/shared/security/rbac/middleware.py`
5. `services/shared/security/rbac/tenant.py`
6. `services/shared/database/models/user.py`
7. `services/shared/database/migrations/versions/xxx_add_rbac_tables.py`
8. `tests/security/test_authorization.py`

## Security Considerations

- **Principle of least privilege** - Users get minimum permissions needed
- **Defense in depth** - Check permissions at multiple layers
- **Tenant isolation** - Always enforce tenant boundaries
- **Audit all authorization failures** - Log for security monitoring
- **Regular permission reviews** - Periodically audit role assignments
- **No hardcoded bypasses** - All access goes through authorization layer
