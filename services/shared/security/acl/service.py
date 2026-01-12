"""
ACL service for document access control.

This module provides the main ACL service for managing document
access permissions across the RAG pipeline.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import UUID

from .models import (
    ACLUpdateRequest,
    BulkACLUpdateRequest,
    DocumentACL,
    ShareRequest,
    Visibility,
)

logger = logging.getLogger(__name__)


class ACLError(Exception):
    """Base exception for ACL errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DocumentNotFoundError(ACLError):
    """Raised when a document is not found."""

    def __init__(self, document_id: UUID, details: Optional[dict] = None):
        super().__init__(f"Document not found: {document_id}", details)
        self.document_id = document_id


class AccessDeniedError(ACLError):
    """Raised when access is denied."""

    def __init__(
        self,
        document_id: UUID,
        user_id: UUID,
        action: str = "access",
        details: Optional[dict] = None,
    ):
        super().__init__(
            f"Access denied: user {user_id} cannot {action} document {document_id}",
            details,
        )
        self.document_id = document_id
        self.user_id = user_id
        self.action = action


class ACLRepository(Protocol):
    """Protocol for ACL data storage."""

    async def get_acl(self, document_id: UUID) -> Optional[DocumentACL]:
        """Get ACL for a document."""
        ...

    async def save_acl(self, acl: DocumentACL) -> None:
        """Save or update an ACL."""
        ...

    async def delete_acl(self, document_id: UUID) -> None:
        """Delete an ACL."""
        ...

    async def get_acls_for_documents(
        self, document_ids: list[UUID]
    ) -> dict[UUID, DocumentACL]:
        """Get ACLs for multiple documents."""
        ...


class VectorStoreUpdater(Protocol):
    """Protocol for updating vector store ACL metadata."""

    async def update_document_acl(
        self, document_id: UUID, acl_payload: dict[str, Any]
    ) -> None:
        """Update ACL payload in vector store."""
        ...

    async def update_documents_acl(
        self, document_acls: dict[UUID, dict[str, Any]]
    ) -> None:
        """Bulk update ACL payloads in vector store."""
        ...


class ACLService:
    """
    Service for managing document Access Control Lists.

    Provides methods for creating, reading, updating, and deleting
    document ACLs, as well as helper methods for common operations
    like sharing and visibility changes.

    Example:
        ```python
        from services.shared.security.acl import ACLService

        acl_service = ACLService(repository, vector_updater)

        # Get document ACL
        acl = await acl_service.get_document_acl(document_id)

        # Share document
        await acl_service.share_document(
            document_id=doc_id,
            requester_id=user_id,
            share_request=ShareRequest(user_ids=[other_user_id])
        )

        # Check access
        can_access = await acl_service.check_access(
            document_id=doc_id,
            user_id=user_id,
            tenant_id=tenant_id,
            groups=user_groups
        )
        ```
    """

    def __init__(
        self,
        repository: Optional[ACLRepository] = None,
        vector_updater: Optional[VectorStoreUpdater] = None,
        admin_bypass: bool = True,
    ):
        """
        Initialize ACL service.

        Args:
            repository: ACL data repository (optional, uses in-memory if None).
            vector_updater: Vector store updater for propagating ACL changes.
            admin_bypass: Whether admin users bypass all ACL checks.
        """
        self._repository = repository
        self._vector_updater = vector_updater
        self._admin_bypass = admin_bypass

        # In-memory fallback storage
        self._acl_cache: dict[UUID, DocumentACL] = {}

    async def get_document_acl(self, document_id: UUID) -> Optional[DocumentACL]:
        """
        Get ACL for a document.

        Args:
            document_id: ID of the document.

        Returns:
            DocumentACL if found, None otherwise.
        """
        if self._repository:
            return await self._repository.get_acl(document_id)
        return self._acl_cache.get(document_id)

    async def create_acl(
        self,
        document_id: UUID,
        tenant_id: UUID,
        owner_id: UUID,
        visibility: Visibility = Visibility.PRIVATE,
        allowed_users: Optional[list[UUID]] = None,
        allowed_groups: Optional[list[str]] = None,
    ) -> DocumentACL:
        """
        Create a new ACL for a document.

        Args:
            document_id: ID of the document.
            tenant_id: Tenant that owns the document.
            owner_id: User ID of the document owner.
            visibility: Initial visibility level.
            allowed_users: Initially allowed users.
            allowed_groups: Initially allowed groups.

        Returns:
            Created DocumentACL.
        """
        acl = DocumentACL(
            document_id=document_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            visibility=visibility,
            allowed_users=allowed_users or [],
            allowed_groups=allowed_groups or [],
        )

        await self._save_acl(acl)
        logger.info(f"Created ACL for document {document_id}")

        return acl

    async def update_acl(
        self,
        document_id: UUID,
        requester_id: UUID,
        update: ACLUpdateRequest,
        is_admin: bool = False,
    ) -> DocumentACL:
        """
        Update ACL for a document.

        Args:
            document_id: ID of the document.
            requester_id: User requesting the update.
            update: Update request with new values.
            is_admin: Whether requester has admin privileges.

        Returns:
            Updated DocumentACL.

        Raises:
            DocumentNotFoundError: If document ACL not found.
            AccessDeniedError: If requester cannot modify ACL.
        """
        acl = await self.get_document_acl(document_id)
        if acl is None:
            raise DocumentNotFoundError(document_id)

        # Check permission to modify ACL
        if not acl.can_admin(requester_id, is_admin):
            raise AccessDeniedError(document_id, requester_id, "modify ACL")

        # Apply updates
        if update.visibility is not None:
            acl.visibility = update.visibility
        if update.allowed_users is not None:
            acl.allowed_users = update.allowed_users
        if update.allowed_groups is not None:
            acl.allowed_groups = update.allowed_groups
        if update.denied_users is not None:
            acl.denied_users = update.denied_users
        if update.denied_groups is not None:
            acl.denied_groups = update.denied_groups

        acl.updated_at = datetime.now(timezone.utc)
        acl.updated_by = requester_id

        await self._save_acl(acl)
        logger.info(f"Updated ACL for document {document_id} by {requester_id}")

        return acl

    async def delete_acl(self, document_id: UUID) -> None:
        """Delete ACL for a document."""
        if self._repository:
            await self._repository.delete_acl(document_id)
        else:
            self._acl_cache.pop(document_id, None)

        logger.info(f"Deleted ACL for document {document_id}")

    async def check_access(
        self,
        document_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
    ) -> bool:
        """
        Check if a user can access a document.

        Args:
            document_id: ID of the document.
            user_id: ID of the user.
            tenant_id: Tenant ID of the user.
            groups: Groups the user belongs to.
            is_admin: Whether user has admin privileges.

        Returns:
            True if user can access the document.
        """
        if self._admin_bypass and is_admin:
            return True

        acl = await self.get_document_acl(document_id)
        if acl is None:
            # No ACL means access is determined by other means
            # Default to tenant-only access
            return False

        return acl.can_access(user_id, tenant_id, groups, is_admin)

    async def filter_accessible_documents(
        self,
        document_ids: list[UUID],
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
    ) -> list[UUID]:
        """
        Filter a list of documents to only those accessible by user.

        Args:
            document_ids: Documents to filter.
            user_id: User requesting access.
            tenant_id: User's tenant.
            groups: User's groups.
            is_admin: Whether user is admin.

        Returns:
            List of accessible document IDs.
        """
        if self._admin_bypass and is_admin:
            return document_ids

        accessible = []
        for doc_id in document_ids:
            if await self.check_access(doc_id, user_id, tenant_id, groups, is_admin):
                accessible.append(doc_id)

        return accessible

    async def share_document(
        self,
        document_id: UUID,
        requester_id: UUID,
        share_request: ShareRequest,
        is_admin: bool = False,
    ) -> DocumentACL:
        """
        Share a document with users and/or groups.

        Args:
            document_id: Document to share.
            requester_id: User requesting the share.
            share_request: Share details.
            is_admin: Whether requester is admin.

        Returns:
            Updated DocumentACL.

        Raises:
            DocumentNotFoundError: If document ACL not found.
            AccessDeniedError: If requester cannot share.
        """
        acl = await self.get_document_acl(document_id)
        if acl is None:
            raise DocumentNotFoundError(document_id)

        # Check permission to share
        if not acl.can_admin(requester_id, is_admin):
            raise AccessDeniedError(document_id, requester_id, "share")

        # Add users
        for user_id in share_request.user_ids:
            acl.add_user(
                user_id,
                permission=share_request.permission,
                granted_by=requester_id,
                expires_at=share_request.expires_at,
            )

        # Add groups
        for group_name in share_request.group_names:
            acl.add_group(
                group_name,
                permission=share_request.permission,
                granted_by=requester_id,
                expires_at=share_request.expires_at,
            )

        # Update visibility if needed
        if acl.visibility == Visibility.PRIVATE and share_request.group_names:
            acl.visibility = Visibility.GROUP

        await self._save_acl(acl)
        logger.info(
            f"Document {document_id} shared by {requester_id} "
            f"with {len(share_request.user_ids)} users "
            f"and {len(share_request.group_names)} groups"
        )

        return acl

    async def make_public(
        self,
        document_id: UUID,
        requester_id: UUID,
        is_admin: bool = False,
    ) -> DocumentACL:
        """
        Make a document public.

        Args:
            document_id: Document to make public.
            requester_id: User requesting the change.
            is_admin: Whether requester is admin.

        Returns:
            Updated DocumentACL.
        """
        return await self.update_acl(
            document_id,
            requester_id,
            ACLUpdateRequest(visibility=Visibility.PUBLIC),
            is_admin,
        )

    async def make_private(
        self,
        document_id: UUID,
        requester_id: UUID,
        is_admin: bool = False,
    ) -> DocumentACL:
        """
        Make a document private (owner-only).

        Args:
            document_id: Document to make private.
            requester_id: User requesting the change.
            is_admin: Whether requester is admin.

        Returns:
            Updated DocumentACL.
        """
        return await self.update_acl(
            document_id,
            requester_id,
            ACLUpdateRequest(
                visibility=Visibility.PRIVATE,
                allowed_users=[],
                allowed_groups=[],
            ),
            is_admin,
        )

    async def make_tenant_visible(
        self,
        document_id: UUID,
        requester_id: UUID,
        is_admin: bool = False,
    ) -> DocumentACL:
        """
        Make a document visible to all users in the tenant.

        Args:
            document_id: Document to update.
            requester_id: User requesting the change.
            is_admin: Whether requester is admin.

        Returns:
            Updated DocumentACL.
        """
        return await self.update_acl(
            document_id,
            requester_id,
            ACLUpdateRequest(visibility=Visibility.TENANT),
            is_admin,
        )

    async def bulk_update_acl(
        self,
        requester_id: UUID,
        bulk_request: BulkACLUpdateRequest,
        is_admin: bool = False,
    ) -> dict[UUID, DocumentACL]:
        """
        Bulk update ACLs for multiple documents.

        Args:
            requester_id: User requesting the updates.
            bulk_request: Bulk update request.
            is_admin: Whether requester is admin.

        Returns:
            Dict mapping document IDs to updated ACLs.

        Note:
            Documents the user cannot modify will be skipped.
        """
        results: dict[UUID, DocumentACL] = {}
        errors: list[str] = []

        for doc_id in bulk_request.document_ids:
            try:
                acl = await self.get_document_acl(doc_id)
                if acl is None:
                    errors.append(f"Document {doc_id} not found")
                    continue

                if not acl.can_admin(requester_id, is_admin):
                    errors.append(f"No permission to modify {doc_id}")
                    continue

                # Apply updates
                if bulk_request.visibility is not None:
                    acl.visibility = bulk_request.visibility

                for user_id in bulk_request.add_users:
                    acl.add_user(user_id, granted_by=requester_id)

                for user_id in bulk_request.remove_users:
                    acl.remove_user(user_id)

                for group in bulk_request.add_groups:
                    acl.add_group(group, granted_by=requester_id)

                for group in bulk_request.remove_groups:
                    acl.remove_group(group)

                acl.updated_at = datetime.now(timezone.utc)
                acl.updated_by = requester_id

                await self._save_acl(acl)
                results[doc_id] = acl

            except Exception as e:
                errors.append(f"Error updating {doc_id}: {str(e)}")

        if errors:
            logger.warning(f"Bulk ACL update had errors: {errors}")

        return results

    async def get_acl_filter_for_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """
        Get ACL filter dict for use in vector store queries.

        This generates a filter that can be used with Qdrant or
        OpenSearch to restrict results to accessible documents.

        Args:
            user_id: User ID.
            tenant_id: User's tenant ID.
            groups: User's groups.
            is_admin: Whether user is admin.

        Returns:
            Filter dict in unified format.
        """
        if self._admin_bypass and is_admin:
            # Admin sees everything in tenant
            return {"must": [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]}

        # Build filter similar to retrieval ACL filter
        must = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]

        should = [
            {"key": "visibility", "match": {"value": "public"}},
            {"key": "visibility", "match": {"value": "tenant"}},
            {"key": "owner_id", "match": {"value": str(user_id)}},
            {"key": "allowed_users", "match": {"any": [str(user_id)]}},
        ]

        if groups:
            should.append({"key": "allowed_groups", "match": {"any": groups}})

        must_not = [
            {"key": "denied_users", "match": {"any": [str(user_id)]}},
        ]

        if groups:
            must_not.append({"key": "denied_groups", "match": {"any": groups}})

        return {
            "must": must,
            "should": should,
            "must_not": must_not,
        }

    async def _save_acl(self, acl: DocumentACL) -> None:
        """Save ACL and propagate to vector store."""
        if self._repository:
            await self._repository.save_acl(acl)
        else:
            self._acl_cache[acl.document_id] = acl

        # Update vector store if configured
        if self._vector_updater:
            await self._vector_updater.update_document_acl(
                acl.document_id,
                acl.to_filter_payload(),
            )
