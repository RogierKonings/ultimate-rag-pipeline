"""
Permission definitions and mappings for RBAC.

This module defines all system permissions organized by resource type,
along with role-to-permission mappings.
"""

from enum import Enum
from typing import Optional


class PermissionScope(str, Enum):
    """Scope/resource categories for permissions."""

    # Document operations
    DOCUMENTS = "documents"
    CHUNKS = "chunks"

    # Search and retrieval
    SEARCH = "search"
    RETRIEVAL = "retrieval"

    # Ingestion operations
    INGESTION = "ingestion"
    CONNECTORS = "connectors"

    # LLM operations
    LLM = "llm"
    PROMPTS = "prompts"

    # Evaluation and analytics
    EVALUATION = "evaluation"
    ANALYTICS = "analytics"

    # User and tenant management
    USERS = "users"
    ROLES = "roles"
    TENANTS = "tenants"
    GROUPS = "groups"

    # System administration
    SYSTEM = "system"
    AUDIT = "audit"
    SECRETS = "secrets"

    # API keys and integrations
    API_KEYS = "api_keys"
    INTEGRATIONS = "integrations"


class Permission(str, Enum):
    """
    Fine-grained permissions for RAG pipeline operations.

    Permission format: {scope}:{action}
    Actions: read, write, delete, execute, admin

    Example:
        Permission.DOCUMENTS_READ -> "documents:read"
        Permission.INGESTION_EXECUTE -> "ingestion:execute"
    """

    # Document permissions
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_WRITE = "documents:write"
    DOCUMENTS_DELETE = "documents:delete"
    DOCUMENTS_ADMIN = "documents:admin"  # Manage ACLs

    # Chunk permissions
    CHUNKS_READ = "chunks:read"
    CHUNKS_WRITE = "chunks:write"
    CHUNKS_DELETE = "chunks:delete"

    # Search permissions
    SEARCH_EXECUTE = "search:execute"
    SEARCH_ADVANCED = "search:advanced"  # Access to advanced search features
    SEARCH_ADMIN = "search:admin"  # Configure search settings

    # Retrieval permissions
    RETRIEVAL_EXECUTE = "retrieval:execute"
    RETRIEVAL_RERANK = "retrieval:rerank"
    RETRIEVAL_ADMIN = "retrieval:admin"

    # Ingestion permissions
    INGESTION_EXECUTE = "ingestion:execute"
    INGESTION_BATCH = "ingestion:batch"  # Batch ingestion jobs
    INGESTION_ADMIN = "ingestion:admin"  # Configure ingestion settings

    # Connector permissions
    CONNECTORS_READ = "connectors:read"
    CONNECTORS_WRITE = "connectors:write"
    CONNECTORS_EXECUTE = "connectors:execute"
    CONNECTORS_ADMIN = "connectors:admin"

    # LLM permissions
    LLM_EXECUTE = "llm:execute"
    LLM_STREAM = "llm:stream"
    LLM_ADMIN = "llm:admin"  # Model configuration

    # Prompt permissions
    PROMPTS_READ = "prompts:read"
    PROMPTS_WRITE = "prompts:write"
    PROMPTS_ADMIN = "prompts:admin"

    # Evaluation permissions
    EVALUATION_READ = "evaluation:read"
    EVALUATION_EXECUTE = "evaluation:execute"
    EVALUATION_ADMIN = "evaluation:admin"

    # Analytics permissions
    ANALYTICS_READ = "analytics:read"
    ANALYTICS_EXPORT = "analytics:export"
    ANALYTICS_ADMIN = "analytics:admin"

    # User management permissions
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"
    USERS_ADMIN = "users:admin"

    # Role management permissions
    ROLES_READ = "roles:read"
    ROLES_WRITE = "roles:write"
    ROLES_ASSIGN = "roles:assign"
    ROLES_ADMIN = "roles:admin"

    # Tenant management permissions
    TENANTS_READ = "tenants:read"
    TENANTS_WRITE = "tenants:write"
    TENANTS_ADMIN = "tenants:admin"

    # Group management permissions
    GROUPS_READ = "groups:read"
    GROUPS_WRITE = "groups:write"
    GROUPS_ADMIN = "groups:admin"

    # System permissions
    SYSTEM_READ = "system:read"  # Health, status
    SYSTEM_ADMIN = "system:admin"  # Configuration

    # Audit permissions
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    AUDIT_ADMIN = "audit:admin"

    # Secrets management
    SECRETS_READ = "secrets:read"
    SECRETS_WRITE = "secrets:write"
    SECRETS_ADMIN = "secrets:admin"

    # API key management
    API_KEYS_READ = "api_keys:read"
    API_KEYS_WRITE = "api_keys:write"
    API_KEYS_REVOKE = "api_keys:revoke"
    API_KEYS_ADMIN = "api_keys:admin"

    # Integration management
    INTEGRATIONS_READ = "integrations:read"
    INTEGRATIONS_WRITE = "integrations:write"
    INTEGRATIONS_ADMIN = "integrations:admin"

    @property
    def scope(self) -> str:
        """Extract the scope/resource from the permission."""
        return self.value.split(":")[0]

    @property
    def action(self) -> str:
        """Extract the action from the permission."""
        return self.value.split(":")[1]

    @classmethod
    def from_string(cls, permission_str: str) -> Optional["Permission"]:
        """
        Convert a permission string to Permission enum.

        Args:
            permission_str: Permission string like "documents:read"

        Returns:
            Permission enum value or None if not found.
        """
        for perm in cls:
            if perm.value == permission_str:
                return perm
        return None

    @classmethod
    def get_scope_permissions(cls, scope: PermissionScope) -> list["Permission"]:
        """
        Get all permissions for a given scope.

        Args:
            scope: The permission scope to filter by.

        Returns:
            List of permissions for that scope.
        """
        return [p for p in cls if p.scope == scope.value]


# Role to permissions mapping
# This defines what permissions each role has by default
ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    # Anonymous users - minimal public access
    "anonymous": {
        Permission.SEARCH_EXECUTE,
        Permission.RETRIEVAL_EXECUTE,
        Permission.DOCUMENTS_READ,
    },
    # Basic authenticated user
    "user": {
        # Document access
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.CHUNKS_READ,
        # Search and retrieval
        Permission.SEARCH_EXECUTE,
        Permission.SEARCH_ADVANCED,
        Permission.RETRIEVAL_EXECUTE,
        Permission.RETRIEVAL_RERANK,
        # LLM
        Permission.LLM_EXECUTE,
        Permission.LLM_STREAM,
        Permission.PROMPTS_READ,
        # Analytics
        Permission.ANALYTICS_READ,
        # System
        Permission.SYSTEM_READ,
    },
    # Data analyst - enhanced search and evaluation
    "analyst": {
        # All user permissions plus:
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.CHUNKS_READ,
        Permission.CHUNKS_WRITE,
        Permission.SEARCH_EXECUTE,
        Permission.SEARCH_ADVANCED,
        Permission.RETRIEVAL_EXECUTE,
        Permission.RETRIEVAL_RERANK,
        Permission.LLM_EXECUTE,
        Permission.LLM_STREAM,
        Permission.PROMPTS_READ,
        Permission.PROMPTS_WRITE,
        Permission.ANALYTICS_READ,
        Permission.ANALYTICS_EXPORT,
        Permission.EVALUATION_READ,
        Permission.EVALUATION_EXECUTE,
        Permission.SYSTEM_READ,
    },
    # Data engineer - ingestion and connector management
    "engineer": {
        # All analyst permissions plus:
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_DELETE,
        Permission.CHUNKS_READ,
        Permission.CHUNKS_WRITE,
        Permission.CHUNKS_DELETE,
        Permission.SEARCH_EXECUTE,
        Permission.SEARCH_ADVANCED,
        Permission.RETRIEVAL_EXECUTE,
        Permission.RETRIEVAL_RERANK,
        Permission.INGESTION_EXECUTE,
        Permission.INGESTION_BATCH,
        Permission.CONNECTORS_READ,
        Permission.CONNECTORS_WRITE,
        Permission.CONNECTORS_EXECUTE,
        Permission.LLM_EXECUTE,
        Permission.LLM_STREAM,
        Permission.PROMPTS_READ,
        Permission.PROMPTS_WRITE,
        Permission.ANALYTICS_READ,
        Permission.ANALYTICS_EXPORT,
        Permission.EVALUATION_READ,
        Permission.EVALUATION_EXECUTE,
        Permission.SYSTEM_READ,
        Permission.API_KEYS_READ,
        Permission.INTEGRATIONS_READ,
        Permission.INTEGRATIONS_WRITE,
    },
    # Tenant administrator
    "tenant_admin": {
        # Full access within tenant
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.DOCUMENTS_DELETE,
        Permission.DOCUMENTS_ADMIN,
        Permission.CHUNKS_READ,
        Permission.CHUNKS_WRITE,
        Permission.CHUNKS_DELETE,
        Permission.SEARCH_EXECUTE,
        Permission.SEARCH_ADVANCED,
        Permission.SEARCH_ADMIN,
        Permission.RETRIEVAL_EXECUTE,
        Permission.RETRIEVAL_RERANK,
        Permission.RETRIEVAL_ADMIN,
        Permission.INGESTION_EXECUTE,
        Permission.INGESTION_BATCH,
        Permission.INGESTION_ADMIN,
        Permission.CONNECTORS_READ,
        Permission.CONNECTORS_WRITE,
        Permission.CONNECTORS_EXECUTE,
        Permission.CONNECTORS_ADMIN,
        Permission.LLM_EXECUTE,
        Permission.LLM_STREAM,
        Permission.LLM_ADMIN,
        Permission.PROMPTS_READ,
        Permission.PROMPTS_WRITE,
        Permission.PROMPTS_ADMIN,
        Permission.ANALYTICS_READ,
        Permission.ANALYTICS_EXPORT,
        Permission.ANALYTICS_ADMIN,
        Permission.EVALUATION_READ,
        Permission.EVALUATION_EXECUTE,
        Permission.EVALUATION_ADMIN,
        Permission.USERS_READ,
        Permission.USERS_WRITE,
        Permission.USERS_DELETE,
        Permission.ROLES_READ,
        Permission.ROLES_ASSIGN,
        Permission.GROUPS_READ,
        Permission.GROUPS_WRITE,
        Permission.GROUPS_ADMIN,
        Permission.SYSTEM_READ,
        Permission.AUDIT_READ,
        Permission.API_KEYS_READ,
        Permission.API_KEYS_WRITE,
        Permission.API_KEYS_REVOKE,
        Permission.INTEGRATIONS_READ,
        Permission.INTEGRATIONS_WRITE,
        Permission.INTEGRATIONS_ADMIN,
    },
    # Super admin - full system access
    "admin": set(Permission),
    "super_admin": set(Permission),
    # Service account - internal service-to-service
    "service": {
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_WRITE,
        Permission.CHUNKS_READ,
        Permission.CHUNKS_WRITE,
        Permission.SEARCH_EXECUTE,
        Permission.RETRIEVAL_EXECUTE,
        Permission.RETRIEVAL_RERANK,
        Permission.INGESTION_EXECUTE,
        Permission.LLM_EXECUTE,
        Permission.SYSTEM_READ,
    },
}


def get_role_permissions(role: str) -> set[Permission]:
    """
    Get the set of permissions for a given role.

    Args:
        role: Role name (e.g., "user", "admin").

    Returns:
        Set of Permission enums for the role.
        Empty set if role not found.
    """
    return ROLE_PERMISSIONS.get(role, set())


def get_all_permissions_for_roles(roles: list[str]) -> set[Permission]:
    """
    Get the union of all permissions for multiple roles.

    Args:
        roles: List of role names.

    Returns:
        Combined set of all permissions from all roles.
    """
    all_perms: set[Permission] = set()
    for role in roles:
        all_perms |= get_role_permissions(role)
    return all_perms


def has_permission(
    user_permissions: list[str] | set[str],
    required: Permission | str,
    user_roles: list[str] | None = None,
) -> bool:
    """
    Check if a user has a required permission.

    Checks both explicit permissions and role-based permissions.

    Args:
        user_permissions: User's explicit permissions (strings).
        required: Required permission (Permission enum or string).
        user_roles: Optional list of user roles to check role-based permissions.

    Returns:
        True if user has the permission.
    """
    # Convert required to string if enum
    required_str = required.value if isinstance(required, Permission) else required

    # Check explicit permissions
    if required_str in user_permissions:
        return True

    # Check role-based permissions
    if user_roles:
        role_perms = get_all_permissions_for_roles(user_roles)
        required_enum = (
            required
            if isinstance(required, Permission)
            else Permission.from_string(required_str)
        )
        if required_enum and required_enum in role_perms:
            return True

    return False


def permission_implies(higher: Permission, lower: Permission) -> bool:
    """
    Check if one permission implies another.

    Admin permissions imply all permissions for that scope.

    Args:
        higher: The permission that might imply the lower.
        lower: The permission that might be implied.

    Returns:
        True if higher implies lower.
    """
    # Same permission
    if higher == lower:
        return True

    # Admin implies all in scope
    if higher.action == "admin" and higher.scope == lower.scope:
        return True

    # Write implies read
    if higher.scope == lower.scope:
        if higher.action == "write" and lower.action == "read":
            return True
        if higher.action == "delete" and lower.action in ("read", "write"):
            return True

    return False
