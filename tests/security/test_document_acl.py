"""
Tests for Document ACL module.

This module tests ACL models, service, and filter generation
for document-level access control.
"""

from uuid import uuid4

import pytest

from services.shared.security.acl import (
    AccessDeniedError,
    ACLService,
    ACLUpdateRequest,
    BulkACLUpdateRequest,
    DocumentACL,
    DocumentNotFoundError,
    OpenSearchACLFilter,
    QdrantACLFilter,
    ShareRequest,
    Visibility,
    build_chunk_acl_payload,
)

# Test data
OWNER_ID = uuid4()
USER_ID = uuid4()
OTHER_USER_ID = uuid4()
TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()
DOCUMENT_ID = uuid4()


class TestVisibility:
    """Tests for Visibility enum."""

    def test_visibility_values(self):
        """Test visibility enum values."""
        assert Visibility.PUBLIC.value == "public"
        assert Visibility.PRIVATE.value == "private"
        assert Visibility.GROUP.value == "group"
        assert Visibility.TENANT.value == "tenant"
        assert Visibility.RESTRICTED.value == "restricted"


class TestDocumentACL:
    """Tests for DocumentACL model."""

    @pytest.fixture
    def private_acl(self):
        """Private document ACL."""
        return DocumentACL(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PRIVATE,
        )

    @pytest.fixture
    def public_acl(self):
        """Public document ACL."""
        return DocumentACL(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PUBLIC,
        )

    @pytest.fixture
    def group_acl(self):
        """Group-restricted document ACL."""
        return DocumentACL(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.GROUP,
            allowed_groups=["engineering", "ml-team"],
        )

    def test_owner_always_has_access(self, private_acl):
        """Test that owner can always access their document."""
        assert private_acl.can_access(
            user_id=OWNER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is True

    def test_private_denies_others(self, private_acl):
        """Test that private documents deny non-owners."""
        assert private_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is False

    def test_public_allows_everyone(self, public_acl):
        """Test that public documents allow everyone."""
        assert public_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=OTHER_TENANT_ID,  # Even different tenant
            user_groups=[],
        ) is True

    def test_group_access(self, group_acl):
        """Test group-based access."""
        # User in allowed group
        assert group_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=["engineering"],
        ) is True

        # User not in allowed group
        assert group_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=["finance"],
        ) is False

    def test_tenant_visibility(self):
        """Test tenant-wide visibility."""
        acl = DocumentACL(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.TENANT,
        )

        # Same tenant has access
        assert acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is True

        # Different tenant denied
        assert acl.can_access(
            user_id=USER_ID,
            user_tenant_id=OTHER_TENANT_ID,
            user_groups=[],
        ) is False

    def test_explicit_user_allow(self, private_acl):
        """Test explicitly allowing a user."""
        private_acl.add_user(USER_ID)

        assert private_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is True

    def test_explicit_deny_overrides_allow(self, group_acl):
        """Test that explicit denial overrides group access."""
        group_acl.deny_user(USER_ID)

        # User is in allowed group but explicitly denied
        assert group_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=["engineering"],
        ) is False

    def test_denied_group_overrides_allowed_group(self):
        """Test that denied group overrides allowed group."""
        acl = DocumentACL(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.GROUP,
            allowed_groups=["engineering"],
            denied_groups=["contractors"],
        )

        # User in both groups - denied wins
        assert acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=["engineering", "contractors"],
        ) is False

    def test_admin_bypass(self, private_acl):
        """Test admin bypass."""
        assert private_acl.can_access(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
            is_admin=True,
        ) is True

    def test_to_filter_payload(self, group_acl):
        """Test converting ACL to filter payload."""
        payload = group_acl.to_filter_payload()

        assert payload["tenant_id"] == str(TENANT_ID)
        assert payload["visibility"] == "group"
        assert payload["owner_id"] == str(OWNER_ID)
        assert "engineering" in payload["allowed_groups"]
        assert "ml-team" in payload["allowed_groups"]

    def test_add_and_remove_user(self, private_acl):
        """Test adding and removing users."""
        private_acl.add_user(USER_ID, permission="write", granted_by=OWNER_ID)

        assert USER_ID in private_acl.allowed_users
        assert len(private_acl.entries) == 1
        assert private_acl.entries[0].permission == "write"

        private_acl.remove_user(USER_ID)
        assert USER_ID not in private_acl.allowed_users

    def test_add_and_remove_group(self, private_acl):
        """Test adding and removing groups."""
        private_acl.add_group("new-group", granted_by=OWNER_ID)

        assert "new-group" in private_acl.allowed_groups

        private_acl.remove_group("new-group")
        assert "new-group" not in private_acl.allowed_groups

    def test_can_write(self, private_acl):
        """Test write permission checking."""
        # Owner can write
        assert private_acl.can_write(
            user_id=OWNER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is True

        # Other user cannot write
        assert private_acl.can_write(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is False

        # Add write permission
        private_acl.add_user(USER_ID, permission="write")

        assert private_acl.can_write(
            user_id=USER_ID,
            user_tenant_id=TENANT_ID,
            user_groups=[],
        ) is True

    def test_can_admin(self, private_acl):
        """Test admin permission checking."""
        assert private_acl.can_admin(OWNER_ID) is True
        assert private_acl.can_admin(USER_ID) is False
        assert private_acl.can_admin(USER_ID, is_admin=True) is True


class TestACLService:
    """Tests for ACL service."""

    @pytest.fixture
    def acl_service(self):
        """ACL service instance."""
        return ACLService(admin_bypass=True)

    @pytest.mark.asyncio
    async def test_create_acl(self, acl_service):
        """Test creating an ACL."""
        acl = await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.GROUP,
            allowed_groups=["engineering"],
        )

        assert acl.document_id == DOCUMENT_ID
        assert acl.visibility == Visibility.GROUP
        assert "engineering" in acl.allowed_groups

    @pytest.mark.asyncio
    async def test_get_document_acl(self, acl_service):
        """Test getting an ACL."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )

        acl = await acl_service.get_document_acl(DOCUMENT_ID)
        assert acl is not None
        assert acl.document_id == DOCUMENT_ID

    @pytest.mark.asyncio
    async def test_update_acl(self, acl_service):
        """Test updating an ACL."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PRIVATE,
        )

        updated = await acl_service.update_acl(
            document_id=DOCUMENT_ID,
            requester_id=OWNER_ID,
            update=ACLUpdateRequest(
                visibility=Visibility.PUBLIC,
                allowed_users=[USER_ID],
            ),
        )

        assert updated.visibility == Visibility.PUBLIC
        assert USER_ID in updated.allowed_users

    @pytest.mark.asyncio
    async def test_update_acl_requires_permission(self, acl_service):
        """Test that updating ACL requires admin permission."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )

        with pytest.raises(AccessDeniedError):
            await acl_service.update_acl(
                document_id=DOCUMENT_ID,
                requester_id=USER_ID,  # Not owner
                update=ACLUpdateRequest(visibility=Visibility.PUBLIC),
            )

    @pytest.mark.asyncio
    async def test_update_nonexistent_acl(self, acl_service):
        """Test updating non-existent ACL raises error."""
        with pytest.raises(DocumentNotFoundError):
            await acl_service.update_acl(
                document_id=uuid4(),
                requester_id=OWNER_ID,
                update=ACLUpdateRequest(visibility=Visibility.PUBLIC),
            )

    @pytest.mark.asyncio
    async def test_check_access(self, acl_service):
        """Test access checking."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.GROUP,
            allowed_groups=["engineering"],
        )

        # Owner has access
        assert await acl_service.check_access(
            document_id=DOCUMENT_ID,
            user_id=OWNER_ID,
            tenant_id=TENANT_ID,
            groups=[],
        ) is True

        # User in group has access
        assert await acl_service.check_access(
            document_id=DOCUMENT_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["engineering"],
        ) is True

        # User not in group denied
        assert await acl_service.check_access(
            document_id=DOCUMENT_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["finance"],
        ) is False

    @pytest.mark.asyncio
    async def test_share_document(self, acl_service):
        """Test sharing a document."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )

        await acl_service.share_document(
            document_id=DOCUMENT_ID,
            requester_id=OWNER_ID,
            share_request=ShareRequest(
                user_ids=[USER_ID],
                group_names=["engineering"],
            ),
        )

        # Check access was granted
        assert await acl_service.check_access(
            document_id=DOCUMENT_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=[],
        ) is True

    @pytest.mark.asyncio
    async def test_make_public(self, acl_service):
        """Test making a document public."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PRIVATE,
        )

        acl = await acl_service.make_public(DOCUMENT_ID, OWNER_ID)
        assert acl.visibility == Visibility.PUBLIC

    @pytest.mark.asyncio
    async def test_make_private(self, acl_service):
        """Test making a document private."""
        await acl_service.create_acl(
            document_id=DOCUMENT_ID,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PUBLIC,
            allowed_users=[USER_ID],
        )

        acl = await acl_service.make_private(DOCUMENT_ID, OWNER_ID)
        assert acl.visibility == Visibility.PRIVATE
        assert len(acl.allowed_users) == 0

    @pytest.mark.asyncio
    async def test_filter_accessible_documents(self, acl_service):
        """Test filtering accessible documents."""
        doc1 = uuid4()
        doc2 = uuid4()
        doc3 = uuid4()

        # Create ACLs with different access
        await acl_service.create_acl(
            document_id=doc1,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PUBLIC,
        )
        await acl_service.create_acl(
            document_id=doc2,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.PRIVATE,  # Only owner
        )
        await acl_service.create_acl(
            document_id=doc3,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility=Visibility.GROUP,
            allowed_groups=["engineering"],
        )

        # User can access public and group doc
        accessible = await acl_service.filter_accessible_documents(
            document_ids=[doc1, doc2, doc3],
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["engineering"],
        )

        assert doc1 in accessible  # Public
        assert doc2 not in accessible  # Private, user is not owner
        assert doc3 in accessible  # Group match

    @pytest.mark.asyncio
    async def test_bulk_update_acl(self, acl_service):
        """Test bulk ACL updates."""
        doc1 = uuid4()
        doc2 = uuid4()

        await acl_service.create_acl(
            document_id=doc1,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )
        await acl_service.create_acl(
            document_id=doc2,
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )

        results = await acl_service.bulk_update_acl(
            requester_id=OWNER_ID,
            bulk_request=BulkACLUpdateRequest(
                document_ids=[doc1, doc2],
                visibility=Visibility.PUBLIC,
                add_groups=["engineering"],
            ),
        )

        assert doc1 in results
        assert doc2 in results
        assert results[doc1].visibility == Visibility.PUBLIC
        assert "engineering" in results[doc1].allowed_groups

    @pytest.mark.asyncio
    async def test_get_acl_filter_for_user(self, acl_service):
        """Test getting ACL filter for vector store queries."""
        filter_dict = await acl_service.get_acl_filter_for_user(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["engineering", "ml-team"],
        )

        assert "must" in filter_dict
        assert "should" in filter_dict
        assert "must_not" in filter_dict

        # Check tenant filter is present
        tenant_filter = filter_dict["must"][0]
        assert tenant_filter["key"] == "tenant_id"


class TestQdrantACLFilter:
    """Tests for Qdrant ACL filter builder."""

    @pytest.fixture
    def filter_builder(self):
        """Qdrant filter builder."""
        return QdrantACLFilter()

    def test_build_access_filter(self, filter_builder):
        """Test building Qdrant access filter."""
        qdrant_filter = filter_builder.build_access_filter(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["engineering"],
        )

        assert qdrant_filter is not None
        assert qdrant_filter.must is not None
        assert qdrant_filter.should is not None
        assert qdrant_filter.must_not is not None

    def test_admin_filter(self, filter_builder):
        """Test admin sees only tenant filter."""
        qdrant_filter = filter_builder.build_access_filter(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=[],
            is_admin=True,
        )

        # Admin only gets tenant filter, no should/must_not
        assert qdrant_filter.must is not None
        assert len(qdrant_filter.must) == 1

    def test_build_tenant_filter(self, filter_builder):
        """Test building tenant-only filter."""
        qdrant_filter = filter_builder.build_tenant_filter(TENANT_ID)

        assert qdrant_filter.must is not None
        assert len(qdrant_filter.must) == 1


class TestOpenSearchACLFilter:
    """Tests for OpenSearch ACL filter builder."""

    @pytest.fixture
    def filter_builder(self):
        """OpenSearch filter builder."""
        return OpenSearchACLFilter()

    def test_build_access_filter(self, filter_builder):
        """Test building OpenSearch access filter."""
        filters = filter_builder.build_access_filter(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=["engineering"],
        )

        assert isinstance(filters, list)
        assert len(filters) > 0

        # Should have tenant term filter
        has_tenant_filter = any(
            "term" in f and "tenant_id" in f.get("term", {})
            for f in filters
        )
        assert has_tenant_filter

    def test_admin_filter(self, filter_builder):
        """Test admin filter is simpler."""
        filters = filter_builder.build_access_filter(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            groups=[],
            is_admin=True,
        )

        # Admin only gets tenant filter
        assert len(filters) == 1
        assert "term" in filters[0]

    def test_build_tenant_filter(self, filter_builder):
        """Test building tenant-only filter."""
        filters = filter_builder.build_tenant_filter(TENANT_ID)

        assert len(filters) == 1
        assert filters[0]["term"]["tenant_id"] == str(TENANT_ID)


class TestBuildChunkACLPayload:
    """Tests for chunk ACL payload builder."""

    def test_basic_payload(self):
        """Test building basic ACL payload."""
        payload = build_chunk_acl_payload(
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
        )

        assert payload["tenant_id"] == str(TENANT_ID)
        assert payload["owner_id"] == str(OWNER_ID)
        assert payload["visibility"] == "private"
        assert payload["allowed_users"] == []
        assert payload["allowed_groups"] == []

    def test_full_payload(self):
        """Test building full ACL payload."""
        payload = build_chunk_acl_payload(
            tenant_id=TENANT_ID,
            owner_id=OWNER_ID,
            visibility="group",
            allowed_users=[USER_ID],
            allowed_groups=["engineering"],
            denied_users=[OTHER_USER_ID],
            denied_groups=["contractors"],
        )

        assert payload["visibility"] == "group"
        assert str(USER_ID) in payload["allowed_users"]
        assert "engineering" in payload["allowed_groups"]
        assert str(OTHER_USER_ID) in payload["denied_users"]
        assert "contractors" in payload["denied_groups"]
