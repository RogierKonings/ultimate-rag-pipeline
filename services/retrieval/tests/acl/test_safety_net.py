"""Tests for ACL safety net filter.

The safety net is a defense-in-depth filter applied AFTER reranking.
If query-level ACL is working correctly, this safety net should NEVER
filter anything. Any filtering indicates a BUG and should be logged as a warning.
"""

from uuid import uuid4

import pytest

from acl.models import UserContext
from acl.safety_net import ACLSafetyNet
from search.fusion import FusedResult


@pytest.fixture
def user_context():
    """Create a regular user context."""
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering", "product"],
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
def safety_net():
    """Create ACL safety net instance."""
    return ACLSafetyNet()


def make_fused_result(
    tenant_id: str,
    visibility: str = "public",
    owner_id: str | None = None,
    allowed_groups: list[str] | None = None,
    allowed_users: list[str] | None = None,
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
            "status": status,
        },
        title="Test Document",
        source="test://source",
    )


class TestACLSafetyNetPublicAccess:
    """Tests for public document access."""

    def test_public_doc_same_tenant_passes(self, safety_net, user_context):
        """Public document in same tenant should be accessible."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="public",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id

    def test_tenant_visible_doc_passes(self, safety_net, user_context):
        """Tenant-visible document should be accessible to tenant members."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="tenant",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id


class TestACLSafetyNetTenantIsolation:
    """Tests for tenant isolation."""

    def test_wrong_tenant_blocked(self, safety_net, user_context):
        """Document from different tenant should be blocked."""
        other_tenant_id = str(uuid4())
        result = make_fused_result(
            tenant_id=other_tenant_id,
            visibility="public",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_wrong_tenant_blocked_even_if_public(self, safety_net, user_context):
        """Public visibility doesn't bypass tenant isolation."""
        other_tenant_id = str(uuid4())
        result = make_fused_result(
            tenant_id=other_tenant_id,
            visibility="public",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0


class TestACLSafetyNetStatusFiltering:
    """Tests for status-based filtering."""

    def test_deleted_doc_blocked(self, safety_net, user_context):
        """Deleted (soft-deleted) document should be blocked."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="public",
            status="deleted",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_active_doc_passes(self, safety_net, user_context):
        """Active document should pass through."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="public",
            status="active",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1


class TestACLSafetyNetGroupAccess:
    """Tests for group-based access."""

    def test_group_doc_to_group_member_passes(self, safety_net, user_context):
        """Group-visible document accessible to group member."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="group",
            allowed_groups=["engineering"],  # user is in this group
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id

    def test_group_doc_to_non_member_blocked(self, safety_net, user_context):
        """Group-visible document not accessible to non-member."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="group",
            allowed_groups=["finance", "hr"],  # user not in these groups
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_group_doc_multiple_groups_any_match(self, safety_net, user_context):
        """Access granted if user is in ANY of the allowed groups."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="group",
            allowed_groups=["finance", "product"],  # user is in product
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1

    def test_group_doc_empty_allowed_groups_blocked(self, safety_net, user_context):
        """Group visibility with no allowed_groups should block access."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="group",
            allowed_groups=[],  # No groups allowed
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0


class TestACLSafetyNetPrivateAccess:
    """Tests for private document access."""

    def test_private_doc_to_owner_passes(self, safety_net, user_context):
        """Private document accessible to its owner."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="private",
            owner_id=str(user_context.user_id),
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id

    def test_private_doc_to_non_owner_blocked(self, safety_net, user_context):
        """Private document not accessible to non-owner."""
        other_user_id = str(uuid4())
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="private",
            owner_id=other_user_id,
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_private_doc_to_allowed_user_passes(self, safety_net, user_context):
        """Private document accessible to explicitly allowed user."""
        other_owner = str(uuid4())
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="private",
            owner_id=other_owner,
            allowed_users=[str(user_context.user_id)],  # User explicitly allowed
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == result.chunk_id

    def test_private_doc_allowed_users_wrong_user_blocked(self, safety_net, user_context):
        """Private document with allowed_users list not containing user should block."""
        other_owner = str(uuid4())
        other_user = str(uuid4())
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="private",
            owner_id=other_owner,
            allowed_users=[other_user],  # Different user allowed
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0


class TestACLSafetyNetMixedResults:
    """Tests for filtering multiple results."""

    def test_filters_only_inaccessible(self, safety_net, user_context):
        """Only inaccessible documents are filtered out."""
        accessible = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="public",
        )
        inaccessible = make_fused_result(
            tenant_id=str(uuid4()),  # Wrong tenant
            visibility="public",
        )

        filtered = safety_net.filter([accessible, inaccessible], user_context)

        assert len(filtered) == 1
        assert filtered[0].chunk_id == accessible.chunk_id

    def test_preserves_order(self, safety_net, user_context):
        """Filtered results maintain original order."""
        results = [
            make_fused_result(
                tenant_id=str(user_context.tenant_id),
                visibility="public",
            )
            for _ in range(5)
        ]
        # Set distinct scores to verify order
        for i, r in enumerate(results):
            r.fused_score = 1.0 - (i * 0.1)

        filtered = safety_net.filter(results, user_context)

        assert len(filtered) == 5
        for i, r in enumerate(filtered):
            assert r.fused_score == 1.0 - (i * 0.1)

    def test_empty_input_returns_empty(self, safety_net, user_context):
        """Empty input returns empty output."""
        filtered = safety_net.filter([], user_context)

        assert filtered == []


class TestACLSafetyNetLogging:
    """Tests for warning logging when filtering occurs."""

    def test_logs_warning_when_filtering(self, safety_net, user_context, caplog):
        """A warning should be logged when safety net filters a result."""
        # This indicates a bug in query-level ACL filtering
        inaccessible = make_fused_result(
            tenant_id=str(uuid4()),  # Wrong tenant
            visibility="public",
        )

        with caplog.at_level("WARNING"):
            safety_net.filter([inaccessible], user_context)

        # Verify warning was logged (indicates potential query-level ACL bug)
        assert any(
            "safety_net_filtered" in record.message or "acl" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_no_warning_when_all_pass(self, safety_net, user_context, caplog):
        """No warning logged when all results pass through."""
        accessible = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="public",
        )

        with caplog.at_level("WARNING"):
            safety_net.filter([accessible], user_context)

        # No warnings should be logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 0


class TestACLSafetyNetEdgeCases:
    """Tests for edge cases and missing metadata."""

    def test_missing_visibility_defaults_to_blocked(self, safety_net, user_context):
        """Documents without visibility metadata should be blocked."""
        result = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            fused_score=0.9,
            metadata={
                "tenant_id": str(user_context.tenant_id),
                # No visibility field
            },
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_missing_tenant_id_blocked(self, safety_net, user_context):
        """Documents without tenant_id should be blocked."""
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

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0

    def test_missing_status_treated_as_active(self, safety_net, user_context):
        """Documents without status field are treated as active."""
        result = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            fused_score=0.9,
            metadata={
                "tenant_id": str(user_context.tenant_id),
                "visibility": "public",
                # No status field - should default to allowing it
            },
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 1

    def test_unknown_visibility_blocked(self, safety_net, user_context):
        """Unknown visibility value should block access."""
        result = make_fused_result(
            tenant_id=str(user_context.tenant_id),
            visibility="unknown_visibility_level",
        )

        filtered = safety_net.filter([result], user_context)

        assert len(filtered) == 0
