"""Tests for ACL models."""

from uuid import uuid4

import pytest
from acl.models import (
    ACLFilterConfig,
    DocumentACL,
    UserContext,
    Visibility,
)


class TestVisibility:
    """Tests for Visibility enum."""

    def test_visibility_values(self):
        """Test that visibility has expected values."""
        assert Visibility.PUBLIC.value == "public"
        assert Visibility.PRIVATE.value == "private"
        assert Visibility.GROUP.value == "group"
        assert Visibility.TENANT.value == "tenant"

    def test_visibility_is_string_enum(self):
        """Test visibility can be used as string."""
        # As a str Enum, the value equals its string representation
        assert Visibility.PUBLIC.value == "public"
        # And it equals the string value
        assert Visibility.PUBLIC == "public"


class TestUserContext:
    """Tests for UserContext model."""

    @pytest.fixture
    def user_context(self):
        """Create a basic user context."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering", "ml-team"],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def admin_context(self):
        """Create an admin user context."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["admins"],
            roles=["admin", "user"],
            permissions=["read:documents", "write:documents", "delete:documents"],
        )

    def test_user_context_creation(self, user_context):
        """Test basic user context creation."""
        assert user_context.user_id is not None
        assert user_context.tenant_id is not None
        assert "engineering" in user_context.groups
        assert "ml-team" in user_context.groups

    def test_has_permission(self, user_context):
        """Test permission checking."""
        assert user_context.has_permission("read:documents") is True
        assert user_context.has_permission("delete:documents") is False

    def test_has_role(self, user_context, admin_context):
        """Test role checking."""
        assert user_context.has_role("user") is True
        assert user_context.has_role("admin") is False
        assert admin_context.has_role("admin") is True

    def test_is_admin(self, user_context, admin_context):
        """Test admin check."""
        assert user_context.is_admin() is False
        assert admin_context.is_admin() is True

    def test_is_member_of(self, user_context):
        """Test group membership."""
        assert user_context.is_member_of("engineering") is True
        assert user_context.is_member_of("finance") is False

    def test_optional_fields(self):
        """Test optional email and name fields."""
        context = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            email="user@example.com",
            name="Test User",
        )
        assert context.email == "user@example.com"
        assert context.name == "Test User"

    def test_default_empty_lists(self):
        """Test that lists default to empty."""
        context = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
        )
        assert context.groups == []
        assert context.roles == []
        assert context.permissions == []


class TestDocumentACL:
    """Tests for DocumentACL model."""

    def test_document_acl_defaults(self):
        """Test default values."""
        acl = DocumentACL(tenant_id=uuid4())
        assert acl.visibility == Visibility.PRIVATE
        assert acl.owner_id is None
        assert acl.allowed_groups == []
        assert acl.allowed_users == []
        assert acl.denied_groups == []
        assert acl.denied_users == []

    def test_document_acl_full(self):
        """Test with all fields."""
        tenant_id = uuid4()
        owner_id = uuid4()
        allowed_user = uuid4()
        denied_user = uuid4()

        acl = DocumentACL(
            tenant_id=tenant_id,
            visibility=Visibility.GROUP,
            owner_id=owner_id,
            allowed_groups=["engineering"],
            allowed_users=[allowed_user],
            denied_groups=["contractors"],
            denied_users=[denied_user],
        )

        assert acl.tenant_id == tenant_id
        assert acl.visibility == Visibility.GROUP
        assert acl.owner_id == owner_id
        assert "engineering" in acl.allowed_groups
        assert allowed_user in acl.allowed_users
        assert "contractors" in acl.denied_groups
        assert denied_user in acl.denied_users


class TestACLFilterConfig:
    """Tests for ACLFilterConfig model."""

    def test_default_config(self):
        """Test default configuration."""
        config = ACLFilterConfig()
        assert config.enabled is True
        assert config.admin_bypass is True
        assert config.super_tenant_id is None
        assert config.default_visibility == Visibility.PRIVATE

    def test_custom_config(self):
        """Test custom configuration."""
        super_tenant = uuid4()
        config = ACLFilterConfig(
            enabled=False,
            admin_bypass=False,
            super_tenant_id=super_tenant,
            default_visibility=Visibility.TENANT,
        )
        assert config.enabled is False
        assert config.admin_bypass is False
        assert config.super_tenant_id == super_tenant
        assert config.default_visibility == Visibility.TENANT
