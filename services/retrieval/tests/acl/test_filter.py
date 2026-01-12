"""Tests for ACL filter building."""

from uuid import uuid4

import pytest
from acl.filter import ACLFilter, AnonymousAccessFilter
from acl.models import ACLFilterConfig, UserContext
from qdrant_client.models import Filter


@pytest.fixture
def user_context():
    """Create a regular user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering", "ml-team"],
        roles=["user"],
        permissions=["read:documents"],
    )


@pytest.fixture
def admin_context():
    """Create an admin user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["admins"],
        roles=["admin"],
        permissions=["read:documents", "write:documents"],
    )


@pytest.fixture
def user_no_groups():
    """Create a user context without groups."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=[],
        roles=["user"],
        permissions=["read:documents"],
    )


@pytest.fixture
def acl_filter():
    """Create default ACL filter."""
    return ACLFilter()


class TestACLFilterBuildFilter:
    """Tests for ACLFilter.build_filter()."""

    def test_tenant_isolation(self, acl_filter, user_context):
        """Test that tenant_id is always required in filter."""
        filter_dict = acl_filter.build_filter(user_context)

        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )

        assert tenant_clause is not None
        assert tenant_clause["match"]["value"] == str(user_context.tenant_id)

    def test_visibility_options_included(self, acl_filter, user_context):
        """Test that visibility options are in should clauses."""
        filter_dict = acl_filter.build_filter(user_context)

        should_clauses = filter_dict.get("should", [])

        # Should include public visibility
        public_clause = next(
            (
                c
                for c in should_clauses
                if c["key"] == "visibility" and c["match"]["value"] == "public"
            ),
            None,
        )
        assert public_clause is not None

        # Should include tenant visibility
        tenant_clause = next(
            (
                c
                for c in should_clauses
                if c["key"] == "visibility" and c["match"]["value"] == "tenant"
            ),
            None,
        )
        assert tenant_clause is not None

    def test_group_access_included(self, acl_filter, user_context):
        """Test that user's groups are included in filter."""
        filter_dict = acl_filter.build_filter(user_context)

        should_clauses = filter_dict.get("should", [])

        group_clause = next(
            (c for c in should_clauses if c["key"] == "allowed_groups"),
            None,
        )

        assert group_clause is not None
        assert set(group_clause["match"]["any"]) == {"engineering", "ml-team"}

    def test_no_group_clause_when_no_groups(self, acl_filter, user_no_groups):
        """Test that no group clause when user has no groups."""
        filter_dict = acl_filter.build_filter(user_no_groups)

        should_clauses = filter_dict.get("should", [])

        group_clause = next(
            (c for c in should_clauses if c["key"] == "allowed_groups"),
            None,
        )

        assert group_clause is None

    def test_user_access_included(self, acl_filter, user_context):
        """Test that user ID is included in allowed_users clause."""
        filter_dict = acl_filter.build_filter(user_context)

        should_clauses = filter_dict.get("should", [])

        user_clause = next(
            (c for c in should_clauses if c["key"] == "allowed_users"),
            None,
        )

        assert user_clause is not None
        assert str(user_context.user_id) in user_clause["match"]["any"]

    def test_owner_access_included(self, acl_filter, user_context):
        """Test that owner_id clause is included."""
        filter_dict = acl_filter.build_filter(user_context)

        should_clauses = filter_dict.get("should", [])

        owner_clause = next(
            (c for c in should_clauses if c["key"] == "owner_id"),
            None,
        )

        assert owner_clause is not None
        assert owner_clause["match"]["value"] == str(user_context.user_id)

    def test_denied_access_enforced(self, acl_filter, user_context):
        """Test that denied access clauses are included."""
        filter_dict = acl_filter.build_filter(user_context)

        must_not_clauses = filter_dict.get("must_not", [])

        # Should block denied groups (only when user has groups)
        denied_groups = next(
            (c for c in must_not_clauses if c["key"] == "denied_groups"),
            None,
        )
        assert denied_groups is not None

        # Should block denied users
        denied_users = next(
            (c for c in must_not_clauses if c["key"] == "denied_users"),
            None,
        )
        assert denied_users is not None
        assert str(user_context.user_id) in denied_users["match"]["any"]

    def test_no_denied_groups_when_no_groups(self, acl_filter, user_no_groups):
        """Test no denied_groups clause when user has no groups."""
        filter_dict = acl_filter.build_filter(user_no_groups)

        must_not_clauses = filter_dict.get("must_not", [])

        denied_groups = next(
            (c for c in must_not_clauses if c["key"] == "denied_groups"),
            None,
        )

        assert denied_groups is None

    def test_admin_bypass_enabled(self, admin_context):
        """Test that admins bypass ACL when configured."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(admin_context)

        # Should be empty (no restrictions)
        assert filter_dict == {}

    def test_admin_no_bypass_when_disabled(self, admin_context):
        """Test that admins don't bypass when disabled."""
        config = ACLFilterConfig(admin_bypass=False)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(admin_context)

        # Should have normal ACL filters
        assert "must" in filter_dict or "should" in filter_dict

    def test_acl_disabled(self, user_context):
        """Test that ACL can be disabled entirely."""
        config = ACLFilterConfig(enabled=False)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(user_context)

        assert filter_dict == {}

    def test_super_tenant_bypasses_tenant_filter(self, user_context):
        """Test that super tenant bypasses tenant isolation."""
        config = ACLFilterConfig(super_tenant_id=user_context.tenant_id)
        acl = ACLFilter(config)

        filter_dict = acl.build_filter(user_context)

        must_clauses = filter_dict.get("must", [])
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )

        # Super tenant should not have tenant filter
        assert tenant_clause is None

    def test_merge_additional_filters(self, acl_filter, user_context):
        """Test merging ACL with additional filters."""
        additional = {"source_type": "pdf"}

        filter_dict = acl_filter.build_filter(user_context, additional)

        must_clauses = filter_dict.get("must", [])

        # Should include additional filter
        source_clause = next(
            (c for c in must_clauses if c["key"] == "source_type"),
            None,
        )
        assert source_clause is not None
        assert source_clause["match"]["value"] == "pdf"

    def test_merge_complex_additional_filters(self, acl_filter, user_context):
        """Test merging complex additional filters."""
        additional = {
            "must": [{"key": "category", "match": {"value": "tech"}}],
            "should": [{"key": "tags", "match": {"any": ["python", "ml"]}}],
        }

        filter_dict = acl_filter.build_filter(user_context, additional)

        # Must clauses should include both ACL and additional
        must_clauses = filter_dict.get("must", [])
        category_clause = next(
            (c for c in must_clauses if c["key"] == "category"),
            None,
        )
        assert category_clause is not None

        # Should clauses should include both
        should_clauses = filter_dict.get("should", [])
        tags_clause = next(
            (c for c in should_clauses if c["key"] == "tags"),
            None,
        )
        assert tags_clause is not None


class TestACLFilterQdrantConversion:
    """Tests for Qdrant filter conversion."""

    def test_qdrant_filter_conversion(self, acl_filter, user_context):
        """Test conversion to Qdrant Filter object."""
        qdrant_filter = acl_filter.build_qdrant_filter(user_context)

        assert qdrant_filter is not None
        assert isinstance(qdrant_filter, Filter)
        assert qdrant_filter.must is not None
        assert qdrant_filter.should is not None
        assert qdrant_filter.must_not is not None

    def test_qdrant_filter_empty_when_admin(self, admin_context):
        """Test Qdrant filter is None for admin bypass."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        qdrant_filter = acl.build_qdrant_filter(admin_context)

        assert qdrant_filter is None

    def test_qdrant_filter_with_additional(self, acl_filter, user_context):
        """Test Qdrant filter with additional filters."""
        additional = {"document_type": "report"}

        qdrant_filter = acl_filter.build_qdrant_filter(user_context, additional)

        assert qdrant_filter is not None
        # Check that we have the additional filter in must
        document_type_found = False
        for condition in qdrant_filter.must or []:
            if condition.key == "document_type":
                document_type_found = True
        assert document_type_found


class TestACLFilterOpenSearchConversion:
    """Tests for OpenSearch filter conversion."""

    def test_opensearch_filter_conversion(self, acl_filter, user_context):
        """Test conversion to OpenSearch filter clauses."""
        os_filter = acl_filter.build_opensearch_filter(user_context)

        assert isinstance(os_filter, list)
        assert len(os_filter) > 0

    def test_opensearch_filter_has_tenant(self, acl_filter, user_context):
        """Test OpenSearch filter includes tenant clause."""
        os_filter = acl_filter.build_opensearch_filter(user_context)

        # Should have term filter for tenant_id
        tenant_clause = next(
            (c for c in os_filter if "term" in c and "tenant_id" in c.get("term", {})),
            None,
        )
        assert tenant_clause is not None

    def test_opensearch_filter_has_should(self, acl_filter, user_context):
        """Test OpenSearch filter includes bool with should."""
        os_filter = acl_filter.build_opensearch_filter(user_context)

        # Should have bool with should clauses
        bool_should = next(
            (c for c in os_filter if "bool" in c and "should" in c.get("bool", {})),
            None,
        )
        assert bool_should is not None
        assert bool_should["bool"]["minimum_should_match"] == 1

    def test_opensearch_filter_has_must_not(self, acl_filter, user_context):
        """Test OpenSearch filter includes bool with must_not."""
        os_filter = acl_filter.build_opensearch_filter(user_context)

        # Should have bool with must_not clauses
        bool_must_not = next(
            (c for c in os_filter if "bool" in c and "must_not" in c.get("bool", {})),
            None,
        )
        assert bool_must_not is not None

    def test_opensearch_filter_empty_for_admin(self, admin_context):
        """Test OpenSearch filter is empty for admin bypass."""
        config = ACLFilterConfig(admin_bypass=True)
        acl = ACLFilter(config)

        os_filter = acl.build_opensearch_filter(admin_context)

        assert os_filter == []


class TestAnonymousAccessFilter:
    """Tests for AnonymousAccessFilter."""

    def test_anonymous_filter_public_only(self):
        """Test anonymous filter only allows public documents."""
        tenant_id = uuid4()
        anon_context = UserContext(
            user_id=uuid4(),
            tenant_id=tenant_id,
            groups=[],
            roles=["anonymous"],
            permissions=["read:public"],
        )

        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anon_context)

        must_clauses = filter_dict.get("must", [])

        # Should require tenant_id
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_clause is not None

        # Should require public visibility
        visibility_clause = next(
            (c for c in must_clauses if c["key"] == "visibility"),
            None,
        )
        assert visibility_clause is not None
        assert visibility_clause["match"]["value"] == "public"

    def test_anonymous_filter_no_should_clauses(self):
        """Test anonymous filter has no should clauses."""
        anon_context = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=[],
            roles=["anonymous"],
        )

        anon_filter = AnonymousAccessFilter()
        filter_dict = anon_filter.build_filter(anon_context)

        # Should not have any "should" clauses
        assert "should" not in filter_dict
