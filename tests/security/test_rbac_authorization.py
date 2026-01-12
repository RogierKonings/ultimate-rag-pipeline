"""
Tests for RBAC authorization module.

This module tests permissions, roles, authorization service,
and middleware functionality.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from services.shared.security.rbac import (
    AuthorizationService,
    InsufficientPermissionsError,
    Permission,
    PermissionScope,
    Role,
    RoleHierarchy,
    TenantContext,
    TenantContextManager,
    TenantMismatchError,
    get_all_permissions_for_roles,
    get_effective_roles,
    get_role_permissions,
    has_permission,
    has_role_or_higher,
    permission_implies,
)

# Test fixtures
TEST_USER_ID = uuid4()
TEST_TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()


@dataclass
class MockUser:
    """Mock user identity for testing."""

    sub: UUID
    tenant_id: UUID
    roles: list[str]
    permissions: list[str]
    groups: list[str]


@pytest.fixture
def basic_user():
    """Basic authenticated user."""
    return MockUser(
        sub=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        roles=["user"],
        permissions=[],
        groups=["engineering"],
    )


@pytest.fixture
def analyst_user():
    """Analyst user with enhanced permissions."""
    return MockUser(
        sub=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        roles=["analyst"],
        permissions=["analytics:export"],  # Extra explicit permission
        groups=["engineering", "ml-team"],
    )


@pytest.fixture
def admin_user():
    """Admin user with full access."""
    return MockUser(
        sub=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        roles=["admin"],
        permissions=[],
        groups=[],
    )


@pytest.fixture
def super_admin_user():
    """Super admin with cross-tenant access."""
    return MockUser(
        sub=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        roles=["super_admin"],
        permissions=[],
        groups=[],
    )


@pytest.fixture
def auth_service():
    """Authorization service for testing."""
    return AuthorizationService(admin_bypass=True)


class TestPermissions:
    """Tests for permission definitions."""

    def test_permission_scope(self):
        """Test extracting scope from permission."""
        assert Permission.DOCUMENTS_READ.scope == "documents"
        assert Permission.SEARCH_EXECUTE.scope == "search"
        assert Permission.USERS_ADMIN.scope == "users"

    def test_permission_action(self):
        """Test extracting action from permission."""
        assert Permission.DOCUMENTS_READ.action == "read"
        assert Permission.DOCUMENTS_WRITE.action == "write"
        assert Permission.DOCUMENTS_ADMIN.action == "admin"

    def test_permission_from_string(self):
        """Test converting string to Permission enum."""
        perm = Permission.from_string("documents:read")
        assert perm == Permission.DOCUMENTS_READ

        # Invalid permission
        assert Permission.from_string("invalid:permission") is None

    def test_get_scope_permissions(self):
        """Test getting all permissions for a scope."""
        doc_perms = Permission.get_scope_permissions(PermissionScope.DOCUMENTS)
        assert Permission.DOCUMENTS_READ in doc_perms
        assert Permission.DOCUMENTS_WRITE in doc_perms
        assert Permission.DOCUMENTS_DELETE in doc_perms
        assert Permission.DOCUMENTS_ADMIN in doc_perms
        assert Permission.SEARCH_EXECUTE not in doc_perms


class TestRolePermissions:
    """Tests for role-permission mappings."""

    def test_user_role_permissions(self):
        """Test basic user role permissions."""
        perms = get_role_permissions("user")
        assert Permission.DOCUMENTS_READ in perms
        assert Permission.SEARCH_EXECUTE in perms
        assert Permission.LLM_EXECUTE in perms
        # User should not have admin permissions
        assert Permission.USERS_ADMIN not in perms

    def test_analyst_role_permissions(self):
        """Test analyst role permissions."""
        perms = get_role_permissions("analyst")
        assert Permission.ANALYTICS_READ in perms
        assert Permission.ANALYTICS_EXPORT in perms
        assert Permission.EVALUATION_EXECUTE in perms

    def test_admin_role_has_all_permissions(self):
        """Test admin role has all permissions."""
        admin_perms = get_role_permissions("admin")
        for perm in Permission:
            assert perm in admin_perms, f"Admin missing permission: {perm}"

    def test_unknown_role_returns_empty(self):
        """Test unknown role returns empty set."""
        perms = get_role_permissions("nonexistent_role")
        assert perms == set()


class TestRoleHierarchy:
    """Tests for role hierarchy and inheritance."""

    def test_role_inheritance(self):
        """Test role inheritance chain."""
        hierarchy = RoleHierarchy()

        # Analyst inherits from user
        analyst_inherited = hierarchy.get_inherited_roles(Role.ANALYST)
        assert Role.USER in analyst_inherited
        assert Role.ANONYMOUS in analyst_inherited

        # Admin inherits from tenant_admin -> engineer -> analyst -> user
        admin_inherited = hierarchy.get_inherited_roles(Role.ADMIN)
        assert Role.TENANT_ADMIN in admin_inherited
        assert Role.ENGINEER in admin_inherited
        assert Role.ANALYST in admin_inherited
        assert Role.USER in admin_inherited

    def test_role_inherits_from(self):
        """Test checking if role inherits from another."""
        hierarchy = RoleHierarchy()

        assert hierarchy.role_inherits_from(Role.ADMIN, Role.USER) is True
        assert hierarchy.role_inherits_from(Role.USER, Role.ADMIN) is False
        assert hierarchy.role_inherits_from(Role.USER, Role.USER) is True

    def test_get_highest_role(self):
        """Test getting highest role from list."""
        hierarchy = RoleHierarchy()

        roles = [Role.USER, Role.ANALYST, Role.ENGINEER]
        highest = hierarchy.get_highest_role(roles)
        assert highest == Role.ENGINEER

    def test_get_effective_roles(self):
        """Test getting effective roles including inherited."""
        effective = get_effective_roles(["engineer"])
        assert "engineer" in effective
        assert "analyst" in effective
        assert "user" in effective
        assert "anonymous" in effective

    def test_has_role_or_higher(self):
        """Test role hierarchy checking."""
        user_roles = ["engineer"]

        # Engineer has analyst or higher
        assert has_role_or_higher(user_roles, "analyst") is True
        assert has_role_or_higher(user_roles, "user") is True

        # Engineer does not have admin
        assert has_role_or_higher(user_roles, "admin") is False


class TestPermissionImplication:
    """Tests for permission implication logic."""

    def test_admin_implies_all_in_scope(self):
        """Test admin permission implies all in scope."""
        assert (
            permission_implies(
                Permission.DOCUMENTS_ADMIN,
                Permission.DOCUMENTS_READ,
            )
            is True
        )
        assert (
            permission_implies(
                Permission.DOCUMENTS_ADMIN,
                Permission.DOCUMENTS_WRITE,
            )
            is True
        )
        assert (
            permission_implies(
                Permission.DOCUMENTS_ADMIN,
                Permission.DOCUMENTS_DELETE,
            )
            is True
        )

    def test_write_implies_read(self):
        """Test write implies read."""
        assert (
            permission_implies(
                Permission.DOCUMENTS_WRITE,
                Permission.DOCUMENTS_READ,
            )
            is True
        )

    def test_delete_implies_read_write(self):
        """Test delete implies read and write."""
        assert (
            permission_implies(
                Permission.DOCUMENTS_DELETE,
                Permission.DOCUMENTS_READ,
            )
            is True
        )
        assert (
            permission_implies(
                Permission.DOCUMENTS_DELETE,
                Permission.DOCUMENTS_WRITE,
            )
            is True
        )

    def test_cross_scope_no_implication(self):
        """Test permissions in different scopes don't imply each other."""
        assert (
            permission_implies(
                Permission.DOCUMENTS_ADMIN,
                Permission.SEARCH_EXECUTE,
            )
            is False
        )


class TestHasPermission:
    """Tests for has_permission helper function."""

    def test_explicit_permission(self):
        """Test checking explicit permission."""
        user_perms = ["documents:read", "documents:write"]
        assert has_permission(user_perms, Permission.DOCUMENTS_READ) is True
        assert has_permission(user_perms, Permission.DOCUMENTS_DELETE) is False

    def test_role_based_permission(self):
        """Test checking permission via role."""
        user_perms: list[str] = []
        user_roles = ["analyst"]

        assert (
            has_permission(
                user_perms,
                Permission.ANALYTICS_READ,
                user_roles,
            )
            is True
        )
        assert (
            has_permission(
                user_perms,
                Permission.USERS_ADMIN,
                user_roles,
            )
            is False
        )


class TestAuthorizationService:
    """Tests for the authorization service."""

    def test_basic_user_document_read(self, auth_service, basic_user):
        """Test basic user can read documents."""
        assert (
            auth_service.has_permission(
                basic_user,
                Permission.DOCUMENTS_READ,
            )
            is True
        )

    def test_basic_user_cannot_delete(self, auth_service, basic_user):
        """Test basic user cannot delete documents."""
        assert (
            auth_service.has_permission(
                basic_user,
                Permission.DOCUMENTS_DELETE,
            )
            is False
        )

    def test_admin_bypass(self, auth_service, admin_user):
        """Test admin bypasses permission checks."""
        # Admin can do anything
        assert (
            auth_service.has_permission(
                admin_user,
                Permission.SECRETS_ADMIN,
            )
            is True
        )

    def test_has_any_permission(self, auth_service, basic_user):
        """Test has_any_permission check."""
        assert (
            auth_service.has_any_permission(
                basic_user,
                [Permission.DOCUMENTS_DELETE, Permission.DOCUMENTS_READ],
            )
            is True
        )

    def test_has_all_permissions(self, auth_service, basic_user):
        """Test has_all_permissions check."""
        # User has read but not delete
        assert (
            auth_service.has_all_permissions(
                basic_user,
                [Permission.DOCUMENTS_READ, Permission.DOCUMENTS_DELETE],
            )
            is False
        )

        # User has both read and search
        assert (
            auth_service.has_all_permissions(
                basic_user,
                [Permission.DOCUMENTS_READ, Permission.SEARCH_EXECUTE],
            )
            is True
        )

    def test_authorize_permission_success(self, auth_service, basic_user):
        """Test authorize_permission does not raise on success."""
        # Should not raise
        auth_service.authorize_permission(basic_user, Permission.DOCUMENTS_READ)

    def test_authorize_permission_failure(self, auth_service, basic_user):
        """Test authorize_permission raises on failure."""
        with pytest.raises(InsufficientPermissionsError) as exc_info:
            auth_service.authorize_permission(
                basic_user,
                Permission.DOCUMENTS_DELETE,
            )
        assert "documents:delete" in str(exc_info.value)

    def test_has_role(self, auth_service, basic_user):
        """Test has_role check."""
        assert auth_service.has_role(basic_user, "user") is True
        assert auth_service.has_role(basic_user, "admin") is False

    def test_has_role_hierarchy(self, auth_service, analyst_user):
        """Test has_role with hierarchy check."""
        # Analyst inherits from user
        assert auth_service.has_role(analyst_user, "user") is True

    def test_tenant_access_same_tenant(self, auth_service, basic_user):
        """Test tenant access within same tenant."""
        # Should not raise
        auth_service.authorize_tenant_access(basic_user, TEST_TENANT_ID)

    def test_tenant_access_different_tenant(self, auth_service, basic_user):
        """Test tenant access to different tenant."""
        with pytest.raises(TenantMismatchError):
            auth_service.authorize_tenant_access(basic_user, OTHER_TENANT_ID)

    def test_super_admin_cross_tenant(self, auth_service, super_admin_user):
        """Test super admin can access any tenant."""
        # Super admin should be able to access any tenant
        auth_service.authorize_tenant_access(super_admin_user, OTHER_TENANT_ID)

    def test_get_effective_permissions(self, auth_service, analyst_user):
        """Test getting all effective permissions."""
        perms = auth_service.get_effective_permissions(analyst_user)

        # Should have role-based permissions
        assert Permission.ANALYTICS_READ in perms
        assert Permission.EVALUATION_EXECUTE in perms

        # Should have explicit permission
        assert Permission.ANALYTICS_EXPORT in perms

    def test_get_effective_roles(self, auth_service, analyst_user):
        """Test getting all effective roles."""
        roles = auth_service.get_effective_roles(analyst_user)

        assert "analyst" in roles
        assert "user" in roles
        assert "anonymous" in roles


class TestTenantContext:
    """Tests for tenant context management."""

    def test_tenant_context_creation(self):
        """Test creating tenant context."""
        ctx = TenantContext(
            tenant_id=TEST_TENANT_ID,
            tenant_name="Test Tenant",
            features={"feature_a", "feature_b"},
            settings={"key": "value"},
        )

        assert ctx.tenant_id == TEST_TENANT_ID
        assert ctx.tenant_name == "Test Tenant"
        assert ctx.has_feature("feature_a") is True
        assert ctx.has_feature("feature_c") is False
        assert ctx.get_setting("key") == "value"
        assert ctx.get_setting("missing", "default") == "default"

    def test_tenant_context_manager(self):
        """Test tenant context manager."""
        manager = TenantContextManager()

        # Initially no tenant
        assert manager.get_tenant() is None

        # Set tenant
        ctx = TenantContext(tenant_id=TEST_TENANT_ID)
        manager.set_tenant(ctx)

        assert manager.get_tenant_id() == TEST_TENANT_ID

        # Clear tenant
        manager.clear()
        assert manager.get_tenant() is None

    def test_tenant_scope_context_manager(self):
        """Test tenant scope as context manager."""
        manager = TenantContextManager()

        with manager.tenant_scope(TEST_TENANT_ID, tenant_name="Test"):
            assert manager.get_tenant_id() == TEST_TENANT_ID
            assert manager.get_tenant().tenant_name == "Test"

        # After scope, tenant is cleared
        assert manager.get_tenant() is None

    def test_nested_tenant_scope(self):
        """Test nested tenant scopes."""
        manager = TenantContextManager()

        with manager.tenant_scope(TEST_TENANT_ID):
            assert manager.get_tenant_id() == TEST_TENANT_ID

            with manager.tenant_scope(OTHER_TENANT_ID):
                assert manager.get_tenant_id() == OTHER_TENANT_ID

            # After inner scope, outer is restored
            assert manager.get_tenant_id() == TEST_TENANT_ID

        assert manager.get_tenant() is None

    def test_require_tenant_raises_when_not_set(self):
        """Test require_tenant raises when no tenant set."""
        manager = TenantContextManager()

        with pytest.raises(RuntimeError, match="No tenant context"):
            manager.require_tenant()


class TestGetAllPermissionsForRoles:
    """Tests for combining permissions from multiple roles."""

    def test_single_role(self):
        """Test permissions for single role."""
        perms = get_all_permissions_for_roles(["user"])
        user_perms = get_role_permissions("user")
        assert perms == user_perms

    def test_multiple_roles(self):
        """Test permissions are combined from multiple roles."""
        perms = get_all_permissions_for_roles(["user", "analyst"])

        # Should have user permissions
        assert Permission.DOCUMENTS_READ in perms

        # Should have analyst permissions
        assert Permission.ANALYTICS_EXPORT in perms

    def test_empty_roles(self):
        """Test empty role list returns empty permissions."""
        perms = get_all_permissions_for_roles([])
        assert perms == set()


class TestRoleEnum:
    """Tests for Role enum."""

    def test_role_from_string(self):
        """Test converting string to Role enum."""
        assert Role.from_string("user") == Role.USER
        assert Role.from_string("ADMIN") == Role.ADMIN
        assert Role.from_string("invalid") is None

    def test_is_admin_level(self):
        """Test admin level check."""
        assert Role.ADMIN.is_admin_level() is True
        assert Role.SUPER_ADMIN.is_admin_level() is True
        assert Role.TENANT_ADMIN.is_admin_level() is True
        assert Role.USER.is_admin_level() is False
        assert Role.ANALYST.is_admin_level() is False
