"""Comprehensive integration tests for ACL (Access Control List) scenarios.

This module tests all ACL visibility levels and edge cases to ensure
consistency between query-level ACL filtering and the safety net.

Test Coverage:
- AC-4.2: All visibility levels (public, private, group, tenant)
- AC-4.3: Edge cases (user with no groups, empty groups list)
- AC-4.4: Admin bypass behavior
- Tenant isolation enforcement
- Anonymous user restrictions
- Cross-tenant access prevention
"""

from uuid import uuid4

import pytest
from acl.filter import ACLFilter, AnonymousAccessFilter
from acl.models import ACLFilterConfig, UserContext
from acl.safety_net import ACLSafetyNet
from search.fusion import FusedResult

# =============================================================================
# Helper Functions
# =============================================================================


def make_fused_result(
    tenant_id: str,
    visibility: str = "public",
    owner_id: str | None = None,
    allowed_groups: list[str] | None = None,
    allowed_users: list[str] | None = None,
    denied_groups: list[str] | None = None,
    denied_users: list[str] | None = None,
    status: str = "active",
) -> FusedResult:
    """Helper to create a FusedResult with ACL metadata."""
    return FusedResult(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Test content",
        fused_score=0.9,
        semantic_score=0.85,
        keyword_score=0.75,
        metadata={
            "tenant_id": tenant_id,
            "visibility": visibility,
            "owner_id": owner_id,
            "allowed_groups": allowed_groups or [],
            "allowed_users": allowed_users or [],
            "denied_groups": denied_groups or [],
            "denied_users": denied_users or [],
            "status": status,
        },
        title="Test Document",
        source="test://source",
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tenant_id():
    """Generate a unique tenant ID for tests."""
    return uuid4()


@pytest.fixture
def other_tenant_id():
    """Generate a different tenant ID for cross-tenant tests."""
    return uuid4()


@pytest.fixture
def regular_user(tenant_id):
    """Create a regular user context with group memberships."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=tenant_id,
        groups=["engineering", "ml-team"],
        roles=["user"],
        permissions=["read:documents"],
    )


@pytest.fixture
def admin_user(tenant_id):
    """Create an admin user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=tenant_id,
        groups=["admins"],
        roles=["admin"],
        permissions=["read:documents", "write:documents"],
    )


@pytest.fixture
def user_no_groups(tenant_id):
    """Create a user context without any group memberships."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=tenant_id,
        groups=[],
        roles=["user"],
        permissions=["read:documents"],
    )


@pytest.fixture
def anonymous_user(tenant_id):
    """Create an anonymous user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=tenant_id,
        groups=[],
        roles=["anonymous"],
        permissions=["read:public"],
    )


@pytest.fixture
def acl_filter():
    """Create default ACL filter."""
    return ACLFilter()


@pytest.fixture
def safety_net():
    """Create ACL safety net instance."""
    return ACLSafetyNet()


# =============================================================================
# AC-4.2: All Visibility Levels Tests
# =============================================================================


class TestAllVisibilityLevels:
    """Test all visibility levels work correctly at both query and safety net levels."""

    # -------------------------------------------------------------------------
    # Public Visibility Tests
    # -------------------------------------------------------------------------

    class TestPublicVisibility:
        """Test PUBLIC visibility: accessible to all users in tenant."""

        def test_public_doc_accessible_to_regular_user(self, acl_filter, safety_net, regular_user):
            """Public document should be accessible to any authenticated user in tenant."""
            # Verify query-level filter allows public visibility
            filter_dict = acl_filter.build_filter(regular_user)
            should_clauses = filter_dict.get("should", [])
            public_clause = next(
                (
                    c
                    for c in should_clauses
                    if c["key"] == "visibility" and c["match"]["value"] == "public"
                ),
                None,
            )
            assert public_clause is not None, "Filter should include public visibility"

            # Verify safety net passes public documents
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="public",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1
            assert filtered[0].chunk_id == result.chunk_id

        def test_public_doc_accessible_to_user_with_no_groups(
            self, acl_filter, safety_net, user_no_groups
        ):
            """Public document should be accessible even to users without groups."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="public",
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 1

        def test_public_doc_blocked_from_other_tenant(
            self, acl_filter, safety_net, regular_user, other_tenant_id
        ):
            """Public document from another tenant should be blocked."""
            # Verify query-level filter includes tenant restriction
            filter_dict = acl_filter.build_filter(regular_user)
            must_clauses = filter_dict.get("must", [])
            tenant_clause = next(
                (c for c in must_clauses if c["key"] == "tenant_id"),
                None,
            )
            assert tenant_clause is not None
            assert tenant_clause["match"]["value"] == str(regular_user.tenant_id)

            # Verify safety net blocks cross-tenant access
            result = make_fused_result(
                tenant_id=str(other_tenant_id),
                visibility="public",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

    # -------------------------------------------------------------------------
    # Private Visibility Tests
    # -------------------------------------------------------------------------

    class TestPrivateVisibility:
        """Test PRIVATE visibility: accessible only to owner or allowed_users."""

        def test_private_doc_accessible_to_owner(self, acl_filter, safety_net, regular_user):
            """Private document should be accessible to its owner."""
            # Verify query-level filter includes owner clause
            filter_dict = acl_filter.build_filter(regular_user)
            should_clauses = filter_dict.get("should", [])
            owner_clause = next(
                (c for c in should_clauses if c["key"] == "owner_id"),
                None,
            )
            assert owner_clause is not None
            assert owner_clause["match"]["value"] == str(regular_user.user_id)

            # Verify safety net passes owner access
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=str(regular_user.user_id),
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1
            assert filtered[0].chunk_id == result.chunk_id

        def test_private_doc_accessible_to_allowed_user(self, acl_filter, safety_net, regular_user):
            """Private document should be accessible to explicitly allowed users."""
            other_owner = str(uuid4())

            # Verify query-level filter includes allowed_users clause
            filter_dict = acl_filter.build_filter(regular_user)
            should_clauses = filter_dict.get("should", [])
            allowed_users_clause = next(
                (c for c in should_clauses if c["key"] == "allowed_users"),
                None,
            )
            assert allowed_users_clause is not None
            assert str(regular_user.user_id) in allowed_users_clause["match"]["any"]

            # Verify safety net passes allowed user access
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=other_owner,
                allowed_users=[str(regular_user.user_id)],
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1

        def test_private_doc_blocked_from_non_owner_non_allowed(self, safety_net, regular_user):
            """Private document should be blocked from non-owners who aren't allowed."""
            other_owner = str(uuid4())
            other_user = str(uuid4())

            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=other_owner,
                allowed_users=[other_user],  # Different user allowed, not our user
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_private_doc_without_owner_blocked(self, safety_net, regular_user):
            """Private document with no owner and user not in allowed_users should be blocked."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=None,
                allowed_users=[],
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

    # -------------------------------------------------------------------------
    # Group Visibility Tests
    # -------------------------------------------------------------------------

    class TestGroupVisibility:
        """Test GROUP visibility: accessible only to group members."""

        def test_group_doc_accessible_to_group_member(self, acl_filter, safety_net, regular_user):
            """Group document should be accessible to users in allowed groups."""
            # Verify query-level filter includes group clause
            filter_dict = acl_filter.build_filter(regular_user)
            should_clauses = filter_dict.get("should", [])
            group_clause = next(
                (c for c in should_clauses if c["key"] == "allowed_groups"),
                None,
            )
            assert group_clause is not None
            assert set(group_clause["match"]["any"]) == {"engineering", "ml-team"}

            # Verify safety net passes group member access
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=["engineering"],  # User is in this group
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1
            assert filtered[0].chunk_id == result.chunk_id

        def test_group_doc_accessible_with_any_matching_group(self, safety_net, regular_user):
            """Access granted if user is in ANY of the allowed groups."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=["finance", "ml-team"],  # User is in ml-team
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1

        def test_group_doc_blocked_from_non_member(self, safety_net, regular_user):
            """Group document should be blocked from users not in allowed groups."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=["finance", "hr"],  # User not in these groups
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_group_doc_with_empty_allowed_groups_blocked(self, safety_net, regular_user):
            """Group document with no allowed_groups should block everyone."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=[],
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

    # -------------------------------------------------------------------------
    # Tenant Visibility Tests
    # -------------------------------------------------------------------------

    class TestTenantVisibility:
        """Test TENANT visibility: accessible to all users in the same tenant."""

        def test_tenant_doc_accessible_to_tenant_user(self, acl_filter, safety_net, regular_user):
            """Tenant-visible document should be accessible to all tenant members."""
            # Verify query-level filter includes tenant visibility
            filter_dict = acl_filter.build_filter(regular_user)
            should_clauses = filter_dict.get("should", [])
            tenant_clause = next(
                (
                    c
                    for c in should_clauses
                    if c["key"] == "visibility" and c["match"]["value"] == "tenant"
                ),
                None,
            )
            assert tenant_clause is not None

            # Verify safety net passes tenant visibility
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="tenant",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1
            assert filtered[0].chunk_id == result.chunk_id

        def test_tenant_doc_accessible_to_user_with_no_groups(self, safety_net, user_no_groups):
            """Tenant document should be accessible even to users without groups."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="tenant",
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 1

        def test_tenant_doc_blocked_from_other_tenant(
            self, safety_net, regular_user, other_tenant_id
        ):
            """Tenant document from another tenant should be blocked."""
            result = make_fused_result(
                tenant_id=str(other_tenant_id),
                visibility="tenant",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0


# =============================================================================
# AC-4.3: Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    class TestUserWithNoGroups:
        """Test users without any group memberships."""

        def test_no_group_clause_when_user_has_no_groups(self, acl_filter, user_no_groups):
            """ACL filter should not include group clause for groupless users."""
            filter_dict = acl_filter.build_filter(user_no_groups)
            should_clauses = filter_dict.get("should", [])

            group_clause = next(
                (c for c in should_clauses if c["key"] == "allowed_groups"),
                None,
            )
            assert group_clause is None, "Should not have group clause for groupless user"

        def test_no_denied_groups_check_when_user_has_no_groups(self, acl_filter, user_no_groups):
            """ACL filter should not check denied_groups for groupless users."""
            filter_dict = acl_filter.build_filter(user_no_groups)
            must_not_clauses = filter_dict.get("must_not", [])

            denied_groups = next(
                (c for c in must_not_clauses if c["key"] == "denied_groups"),
                None,
            )
            assert denied_groups is None, "Should not have denied_groups for groupless user"

        def test_groupless_user_can_access_public_docs(self, safety_net, user_no_groups):
            """User without groups should still access public documents."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="public",
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 1

        def test_groupless_user_can_access_tenant_docs(self, safety_net, user_no_groups):
            """User without groups should still access tenant documents."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="tenant",
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 1

        def test_groupless_user_cannot_access_group_docs(self, safety_net, user_no_groups):
            """User without groups cannot access group-restricted documents."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="group",
                allowed_groups=["engineering"],
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 0

        def test_groupless_user_can_access_own_private_docs(self, safety_net, user_no_groups):
            """User without groups can still access their own private documents."""
            result = make_fused_result(
                tenant_id=str(user_no_groups.tenant_id),
                visibility="private",
                owner_id=str(user_no_groups.user_id),
            )
            filtered = safety_net.filter([result], user_no_groups)
            assert len(filtered) == 1

    class TestEmptyGroupsList:
        """Test documents with empty groups list."""

        def test_group_doc_empty_allowed_groups_blocks_all_users(self, safety_net, regular_user):
            """Group document with empty allowed_groups blocks everyone."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=[],
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_user_with_groups_blocked_when_doc_has_no_groups(self, safety_net, regular_user):
            """Even users with groups cannot access group docs with empty allowed_groups."""
            assert len(regular_user.groups) > 0  # User has groups

            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=[],
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

    class TestMissingMetadata:
        """Test handling of documents with missing metadata fields."""

        def test_missing_visibility_blocked(self, safety_net, regular_user):
            """Document without visibility metadata should be blocked."""
            result = FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test content",
                fused_score=0.9,
                metadata={
                    "tenant_id": str(regular_user.tenant_id),
                    # No visibility field
                },
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_missing_tenant_id_blocked(self, safety_net, regular_user):
            """Document without tenant_id should be blocked."""
            result = FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test content",
                fused_score=0.9,
                metadata={
                    "visibility": "public",
                    # No tenant_id field
                },
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_missing_status_treated_as_active(self, safety_net, regular_user):
            """Document without status field should be treated as active."""
            result = FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test content",
                fused_score=0.9,
                metadata={
                    "tenant_id": str(regular_user.tenant_id),
                    "visibility": "public",
                    # No status field - should default to active
                },
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 1

        def test_unknown_visibility_blocked(self, safety_net, regular_user):
            """Unknown visibility value should block access."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="unknown_visibility_level",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

    class TestSoftDeletedDocuments:
        """Test handling of soft-deleted (status != active) documents."""

        def test_deleted_doc_blocked(self, safety_net, regular_user):
            """Soft-deleted document should be blocked regardless of visibility."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="public",
                status="deleted",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_deleted_private_doc_blocked_even_for_owner(self, safety_net, regular_user):
            """Soft-deleted private document blocked even for owner."""
            result = make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=str(regular_user.user_id),
                status="deleted",
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0

        def test_filter_includes_status_active_clause(self, acl_filter, regular_user):
            """ACL filter should always include status=active clause."""
            filter_dict = acl_filter.build_filter(regular_user)
            must_clauses = filter_dict.get("must", [])

            status_clause = next(
                (c for c in must_clauses if c["key"] == "status"),
                None,
            )
            assert status_clause is not None
            assert status_clause["match"]["value"] == "active"


# =============================================================================
# AC-4.4: Admin Bypass Tests
# =============================================================================


class TestAdminBypass:
    """Test admin bypass functionality."""

    def test_admin_bypass_enabled_returns_empty_filter(self, admin_user):
        """Admin with bypass enabled should have empty ACL filter."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(admin_user)

        # Should be empty (no restrictions)
        assert filter_dict == {}, "Admin bypass should return empty filter"

    def test_admin_bypass_disabled_applies_normal_acl(self, admin_user):
        """Admin with bypass disabled should have normal ACL filters."""
        config = ACLFilterConfig(admin_bypass=False)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(admin_user)

        # Should have normal ACL filters
        assert "must" in filter_dict or "should" in filter_dict
        # Should include tenant_id filter
        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_clause is not None

    def test_admin_with_bypass_can_see_private_docs(self, admin_user):
        """Admin with bypass can access any document (handled at query level)."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        # With admin bypass, filter is empty - all docs returned at query level
        filter_dict = acl.build_filter(admin_user)
        assert filter_dict == {}

        # Qdrant filter should be None for admin bypass
        qdrant_filter = acl.build_qdrant_filter(admin_user)
        assert qdrant_filter is None

    def test_admin_with_bypass_opensearch_filter_empty(self, admin_user):
        """Admin with bypass should have empty OpenSearch filter."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        os_filter = acl.build_opensearch_filter(admin_user)
        assert os_filter == []

    def test_admin_without_bypass_opensearch_filter_populated(self, admin_user):
        """Admin without bypass should have normal OpenSearch filter."""
        config = ACLFilterConfig(admin_bypass=False)
        acl = ACLFilter(config)

        os_filter = acl.build_opensearch_filter(admin_user)
        assert len(os_filter) > 0

    def test_non_admin_not_affected_by_admin_bypass_setting(self, regular_user):
        """Non-admin users should not be affected by admin_bypass setting."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(regular_user)

        # Regular user should still have ACL filters
        assert "must" in filter_dict or "should" in filter_dict


# =============================================================================
# Tenant Isolation Tests
# =============================================================================


class TestTenantIsolation:
    """Test that tenant isolation is always enforced."""

    def test_tenant_id_always_in_filter(self, acl_filter, regular_user):
        """Tenant ID filter should always be present for regular users."""
        filter_dict = acl_filter.build_filter(regular_user)

        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )

        assert tenant_clause is not None
        assert tenant_clause["match"]["value"] == str(regular_user.tenant_id)

    def test_cross_tenant_access_blocked_at_query_level(
        self, acl_filter, regular_user, other_tenant_id
    ):
        """Query-level filter should prevent cross-tenant queries."""
        filter_dict = acl_filter.build_filter(regular_user)

        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )

        # Tenant filter should match user's tenant, not other tenant
        assert tenant_clause["match"]["value"] == str(regular_user.tenant_id)
        assert tenant_clause["match"]["value"] != str(other_tenant_id)

    def test_cross_tenant_access_blocked_at_safety_net(
        self, safety_net, regular_user, other_tenant_id
    ):
        """Safety net should block any cross-tenant documents that slip through."""
        # Even if query-level fails, safety net should block
        result = make_fused_result(
            tenant_id=str(other_tenant_id),  # Different tenant
            visibility="public",
        )

        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 0

    def test_cross_tenant_blocked_regardless_of_visibility(
        self, safety_net, regular_user, other_tenant_id
    ):
        """Cross-tenant access blocked for all visibility levels."""
        for visibility in ["public", "private", "group", "tenant"]:
            result = make_fused_result(
                tenant_id=str(other_tenant_id),
                visibility=visibility,
            )
            filtered = safety_net.filter([result], regular_user)
            assert len(filtered) == 0, f"Cross-tenant {visibility} doc should be blocked"

    def test_cross_tenant_blocked_even_if_user_explicitly_allowed(
        self, safety_net, regular_user, other_tenant_id
    ):
        """Cross-tenant access blocked even if user is in allowed_users."""
        result = make_fused_result(
            tenant_id=str(other_tenant_id),
            visibility="private",
            allowed_users=[str(regular_user.user_id)],  # User explicitly allowed
        )

        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 0, "Tenant isolation takes precedence"

    def test_cross_tenant_blocked_even_if_user_owns_document(
        self, safety_net, regular_user, other_tenant_id
    ):
        """Cross-tenant access blocked even if user owns the document."""
        result = make_fused_result(
            tenant_id=str(other_tenant_id),
            visibility="private",
            owner_id=str(regular_user.user_id),  # User owns it
        )

        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 0, "Tenant isolation takes precedence over ownership"

    def test_super_tenant_bypasses_tenant_filter(self, regular_user):
        """Super tenant should bypass tenant isolation in query filter."""
        config = ACLFilterConfig(super_tenant_id=regular_user.tenant_id)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(regular_user)

        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )

        # Super tenant should not have tenant filter
        assert tenant_clause is None


# =============================================================================
# Anonymous Access Tests
# =============================================================================


class TestAnonymousAccess:
    """Test access control for anonymous (unauthenticated) users."""

    def test_anonymous_filter_requires_public_visibility(self, anonymous_user):
        """Anonymous filter should only allow public documents."""
        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anonymous_user)

        must_clauses = filter_dict.get("must", [])

        # Should require public visibility
        visibility_clause = next(
            (c for c in must_clauses if c["key"] == "visibility"),
            None,
        )
        assert visibility_clause is not None
        assert visibility_clause["match"]["value"] == "public"

    def test_anonymous_filter_requires_tenant_id(self, anonymous_user):
        """Anonymous filter should still require tenant_id."""
        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anonymous_user)

        must_clauses = filter_dict.get("must", [])

        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_clause is not None
        assert tenant_clause["match"]["value"] == str(anonymous_user.tenant_id)

    def test_anonymous_filter_has_no_should_clauses(self, anonymous_user):
        """Anonymous filter should not have should clauses (only public allowed)."""
        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anonymous_user)

        # Should not have any "should" clauses - only strict "must" for public
        assert "should" not in filter_dict

    def test_anonymous_filter_requires_active_status(self, anonymous_user):
        """Anonymous filter should require active status."""
        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anonymous_user)

        must_clauses = filter_dict.get("must", [])

        status_clause = next(
            (c for c in must_clauses if c["key"] == "status"),
            None,
        )
        assert status_clause is not None
        assert status_clause["match"]["value"] == "active"

    def test_anonymous_cannot_access_private_docs(self, safety_net, anonymous_user):
        """Anonymous users cannot access private documents."""
        result = make_fused_result(
            tenant_id=str(anonymous_user.tenant_id),
            visibility="private",
        )

        filtered = safety_net.filter([result], anonymous_user)
        # Safety net doesn't have special anonymous handling - it uses visibility rules
        # Private with no owner/allowed_users should be blocked
        assert len(filtered) == 0

    def test_anonymous_cannot_access_group_docs(self, safety_net, anonymous_user):
        """Anonymous users cannot access group documents."""
        result = make_fused_result(
            tenant_id=str(anonymous_user.tenant_id),
            visibility="group",
            allowed_groups=["engineering"],
        )

        filtered = safety_net.filter([result], anonymous_user)
        assert len(filtered) == 0


# =============================================================================
# Consistency Tests (Filter + Safety Net Agreement)
# =============================================================================


class TestFilterSafetyNetConsistency:
    """Test that ACL filter and safety net agree on access decisions."""

    def test_both_allow_public_same_tenant(self, acl_filter, safety_net, regular_user):
        """Both filter and safety net should allow public docs in same tenant."""
        # Filter allows public visibility
        filter_dict = acl_filter.build_filter(regular_user)
        should_clauses = filter_dict.get("should", [])
        public_allowed = any(
            c["key"] == "visibility" and c["match"]["value"] == "public" for c in should_clauses
        )
        assert public_allowed

        # Safety net allows public docs
        result = make_fused_result(
            tenant_id=str(regular_user.tenant_id),
            visibility="public",
        )
        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 1

    def test_both_block_cross_tenant(self, acl_filter, safety_net, regular_user, other_tenant_id):
        """Both filter and safety net should block cross-tenant access."""
        # Filter restricts to user's tenant
        filter_dict = acl_filter.build_filter(regular_user)
        must_clauses = filter_dict.get("must", [])
        tenant_filter = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_filter is not None
        assert tenant_filter["match"]["value"] == str(regular_user.tenant_id)

        # Safety net blocks cross-tenant
        result = make_fused_result(
            tenant_id=str(other_tenant_id),
            visibility="public",
        )
        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 0

    def test_both_handle_owner_access(self, acl_filter, safety_net, regular_user):
        """Both filter and safety net should allow owner access to private docs."""
        # Filter includes owner clause
        filter_dict = acl_filter.build_filter(regular_user)
        should_clauses = filter_dict.get("should", [])
        owner_clause = next(
            (c for c in should_clauses if c["key"] == "owner_id"),
            None,
        )
        assert owner_clause is not None
        assert owner_clause["match"]["value"] == str(regular_user.user_id)

        # Safety net allows owner access
        result = make_fused_result(
            tenant_id=str(regular_user.tenant_id),
            visibility="private",
            owner_id=str(regular_user.user_id),
        )
        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 1

    def test_both_handle_group_access(self, acl_filter, safety_net, regular_user):
        """Both filter and safety net should allow group member access."""
        # Filter includes group clause
        filter_dict = acl_filter.build_filter(regular_user)
        should_clauses = filter_dict.get("should", [])
        group_clause = next(
            (c for c in should_clauses if c["key"] == "allowed_groups"),
            None,
        )
        assert group_clause is not None
        assert "engineering" in group_clause["match"]["any"]

        # Safety net allows group access
        result = make_fused_result(
            tenant_id=str(regular_user.tenant_id),
            visibility="group",
            allowed_groups=["engineering"],
        )
        filtered = safety_net.filter([result], regular_user)
        assert len(filtered) == 1


# =============================================================================
# Mixed Results Tests
# =============================================================================


class TestMixedResults:
    """Test filtering of mixed accessible and inaccessible results."""

    def test_filters_only_inaccessible_results(self, safety_net, regular_user, other_tenant_id):
        """Only inaccessible results should be filtered out."""
        accessible = make_fused_result(
            tenant_id=str(regular_user.tenant_id),
            visibility="public",
        )
        inaccessible = make_fused_result(
            tenant_id=str(other_tenant_id),  # Wrong tenant
            visibility="public",
        )

        filtered = safety_net.filter([accessible, inaccessible], regular_user)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == accessible.chunk_id

    def test_preserves_order_of_accessible_results(self, safety_net, regular_user):
        """Filtered results should maintain original order."""
        results = [
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="public",
            )
            for _ in range(5)
        ]
        # Set distinct scores to verify order
        for i, r in enumerate(results):
            r.fused_score = 1.0 - (i * 0.1)

        filtered = safety_net.filter(results, regular_user)

        assert len(filtered) == 5
        for i, r in enumerate(filtered):
            assert r.fused_score == 1.0 - (i * 0.1)

    def test_empty_input_returns_empty(self, safety_net, regular_user):
        """Empty input should return empty output."""
        filtered = safety_net.filter([], regular_user)
        assert filtered == []

    def test_all_blocked_returns_empty(self, safety_net, regular_user, other_tenant_id):
        """When all results are inaccessible, return empty list."""
        results = [
            make_fused_result(
                tenant_id=str(other_tenant_id),  # All wrong tenant
                visibility="public",
            )
            for _ in range(3)
        ]

        filtered = safety_net.filter(results, regular_user)
        assert len(filtered) == 0

    def test_mixed_visibility_levels(self, safety_net, regular_user):
        """Test filtering with various visibility levels mixed."""
        results = [
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="public",  # Should pass
            ),
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="tenant",  # Should pass
            ),
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=["engineering"],  # Should pass (user in group)
            ),
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="group",
                allowed_groups=["finance"],  # Should fail (user not in group)
            ),
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=str(regular_user.user_id),  # Should pass (owner)
            ),
            make_fused_result(
                tenant_id=str(regular_user.tenant_id),
                visibility="private",
                owner_id=str(uuid4()),  # Should fail (not owner)
            ),
        ]

        filtered = safety_net.filter(results, regular_user)

        # 4 should pass: public, tenant, group(engineering), private(owner)
        assert len(filtered) == 4


# =============================================================================
# Qdrant and OpenSearch Filter Output Tests
# =============================================================================


class TestQdrantFilterOutput:
    """Test Qdrant-specific filter output."""

    def test_qdrant_filter_returns_filter_object(self, acl_filter, regular_user):
        """build_qdrant_filter should return Qdrant Filter object."""
        from qdrant_client.models import Filter

        qdrant_filter = acl_filter.build_qdrant_filter(regular_user)

        assert qdrant_filter is not None
        assert isinstance(qdrant_filter, Filter)

    def test_qdrant_filter_has_must_should_must_not(self, acl_filter, regular_user):
        """Qdrant filter should have all clause types."""
        qdrant_filter = acl_filter.build_qdrant_filter(regular_user)

        assert qdrant_filter.must is not None
        assert qdrant_filter.should is not None
        assert qdrant_filter.must_not is not None

    def test_qdrant_filter_with_additional_filters(self, acl_filter, regular_user):
        """Qdrant filter should include additional metadata filters."""
        additional = {"document_type": "report"}
        qdrant_filter = acl_filter.build_qdrant_filter(regular_user, additional)

        # Check that additional filter is in must conditions
        found = False
        for condition in qdrant_filter.must or []:
            if condition.key == "document_type":
                found = True
                break
        assert found


class TestOpenSearchFilterOutput:
    """Test OpenSearch-specific filter output."""

    def test_opensearch_filter_returns_list(self, acl_filter, regular_user):
        """build_opensearch_filter should return list of clauses."""
        os_filter = acl_filter.build_opensearch_filter(regular_user)

        assert isinstance(os_filter, list)
        assert len(os_filter) > 0

    def test_opensearch_filter_has_tenant_term(self, acl_filter, regular_user):
        """OpenSearch filter should have tenant_id term clause."""
        os_filter = acl_filter.build_opensearch_filter(regular_user)

        tenant_clause = next(
            (c for c in os_filter if "term" in c and "tenant_id" in c.get("term", {})),
            None,
        )
        assert tenant_clause is not None

    def test_opensearch_filter_has_bool_should(self, acl_filter, regular_user):
        """OpenSearch filter should have bool with should clauses."""
        os_filter = acl_filter.build_opensearch_filter(regular_user)

        bool_should = next(
            (c for c in os_filter if "bool" in c and "should" in c.get("bool", {})),
            None,
        )
        assert bool_should is not None
        assert bool_should["bool"]["minimum_should_match"] == 1

    def test_opensearch_filter_has_must_not(self, acl_filter, regular_user):
        """OpenSearch filter should have bool with must_not clauses."""
        os_filter = acl_filter.build_opensearch_filter(regular_user)

        bool_must_not = next(
            (c for c in os_filter if "bool" in c and "must_not" in c.get("bool", {})),
            None,
        )
        assert bool_must_not is not None
