"""
ACL data models for document access control.

This module defines the data structures for Access Control Lists,
including visibility levels, ACL entries, and request models.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Visibility(str, Enum):
    """Document visibility levels.

    Determines the base access level for a document before
    explicit ACL rules are applied.
    """

    PUBLIC = "public"  # Visible to everyone (including anonymous)
    PRIVATE = "private"  # Visible only to owner
    GROUP = "group"  # Visible to specified groups
    TENANT = "tenant"  # Visible to all users in the tenant
    RESTRICTED = "restricted"  # Visible only to explicitly allowed users


class ACLEntry(BaseModel):
    """Single ACL entry granting or denying access.

    Represents an access rule for a specific principal (user or group).
    """

    principal_type: str = Field(
        ...,
        description="Type of principal: 'user' or 'group'",
    )
    principal_id: str = Field(
        ...,
        description="ID of the user or group",
    )
    permission: str = Field(
        default="read",
        description="Permission level: 'read', 'write', 'admin'",
    )
    granted: bool = Field(
        default=True,
        description="True for allow, False for deny",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time for this entry",
    )
    granted_by: UUID | None = Field(
        default=None,
        description="User who granted this access",
    )
    granted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this access was granted",
    )

    def is_expired(self) -> bool:
        """Check if this ACL entry has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at


class DocumentACL(BaseModel):
    """Complete ACL for a document.

    Contains all access control information for a single document,
    including visibility, owner, and explicit access rules.
    """

    document_id: UUID = Field(
        ...,
        description="ID of the document this ACL applies to",
    )
    tenant_id: UUID = Field(
        ...,
        description="Tenant that owns the document",
    )
    visibility: Visibility = Field(
        default=Visibility.PRIVATE,
        description="Base visibility level",
    )
    owner_id: UUID = Field(
        ...,
        description="User ID of the document owner",
    )

    # Explicit access lists
    allowed_users: list[UUID] = Field(
        default_factory=list,
        description="Users explicitly granted access",
    )
    allowed_groups: list[str] = Field(
        default_factory=list,
        description="Groups explicitly granted access",
    )
    denied_users: list[UUID] = Field(
        default_factory=list,
        description="Users explicitly denied access (overrides allowed)",
    )
    denied_groups: list[str] = Field(
        default_factory=list,
        description="Groups explicitly denied access (overrides allowed)",
    )

    # Detailed ACL entries (for more granular control)
    entries: list[ACLEntry] = Field(
        default_factory=list,
        description="Detailed ACL entries with permissions",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    updated_by: UUID | None = None

    def can_access(
        self,
        user_id: UUID,
        user_tenant_id: UUID,
        user_groups: list[str],
        is_admin: bool = False,
    ) -> bool:
        """
        Check if a user can access this document.

        Access logic (evaluated in order):
        1. Admin users have full access (if is_admin=True)
        2. User explicitly denied -> denied
        3. User in denied group -> denied
        4. Owner always has access
        5. Public visibility -> allowed
        6. Tenant visibility + same tenant -> allowed
        7. User explicitly allowed -> allowed
        8. User in allowed group (with group visibility) -> allowed
        9. Default -> denied

        Args:
            user_id: ID of the user requesting access.
            user_tenant_id: Tenant ID of the user.
            user_groups: Groups the user belongs to.
            is_admin: Whether the user has admin privileges.

        Returns:
            True if user can access the document.
        """
        # Admin bypass
        if is_admin:
            return True

        # Check explicit denials first (deny always wins)
        if user_id in self.denied_users:
            return False

        if any(group in self.denied_groups for group in user_groups):
            return False

        # Owner always has access
        if user_id == self.owner_id:
            return True

        # Public visibility
        if self.visibility == Visibility.PUBLIC:
            return True

        # Tenant visibility requires same tenant
        if self.visibility == Visibility.TENANT:
            return user_tenant_id == self.tenant_id

        # Check explicit allowances
        if user_id in self.allowed_users:
            return True

        # Group visibility requires matching group
        if self.visibility == Visibility.GROUP:
            if any(group in self.allowed_groups for group in user_groups):
                return True

        # Restricted visibility requires explicit allow (already checked above)
        # Private visibility only allows owner (already checked above)

        return False

    def can_write(
        self,
        user_id: UUID,
        user_tenant_id: UUID,
        user_groups: list[str],
        is_admin: bool = False,
    ) -> bool:
        """Check if user can modify the document."""
        # Admin or owner can always write
        if is_admin or user_id == self.owner_id:
            return True

        # Check ACL entries for write permission
        for entry in self.entries:
            if entry.is_expired():
                continue

            if entry.permission in ("write", "admin") and entry.granted:
                if entry.principal_type == "user" and entry.principal_id == str(user_id):
                    return True
                if entry.principal_type == "group" and entry.principal_id in user_groups:
                    return True

        return False

    def can_admin(self, user_id: UUID, is_admin: bool = False) -> bool:
        """Check if user can modify ACL settings."""
        return is_admin or user_id == self.owner_id

    def to_filter_payload(self) -> dict[str, Any]:
        """
        Convert ACL to payload format for vector store indexing.

        Returns a dict suitable for storing in Qdrant/OpenSearch.
        """
        return {
            "tenant_id": str(self.tenant_id),
            "visibility": self.visibility.value,
            "owner_id": str(self.owner_id),
            "allowed_users": [str(u) for u in self.allowed_users],
            "allowed_groups": self.allowed_groups,
            "denied_users": [str(u) for u in self.denied_users],
            "denied_groups": self.denied_groups,
        }

    def add_user(
        self,
        user_id: UUID,
        permission: str = "read",
        granted_by: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Add a user to the allowed list."""
        if user_id not in self.allowed_users:
            self.allowed_users.append(user_id)

        # Add detailed entry
        self.entries.append(
            ACLEntry(
                principal_type="user",
                principal_id=str(user_id),
                permission=permission,
                granted=True,
                granted_by=granted_by,
                expires_at=expires_at,
            ),
        )
        self.updated_at = datetime.now(UTC)
        self.updated_by = granted_by

    def remove_user(self, user_id: UUID) -> None:
        """Remove a user from the allowed list."""
        self.allowed_users = [u for u in self.allowed_users if u != user_id]
        self.entries = [
            e for e in self.entries
            if not (e.principal_type == "user" and e.principal_id == str(user_id))
        ]
        self.updated_at = datetime.now(UTC)

    def add_group(
        self,
        group_name: str,
        permission: str = "read",
        granted_by: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Add a group to the allowed list."""
        if group_name not in self.allowed_groups:
            self.allowed_groups.append(group_name)

        self.entries.append(
            ACLEntry(
                principal_type="group",
                principal_id=group_name,
                permission=permission,
                granted=True,
                granted_by=granted_by,
                expires_at=expires_at,
            ),
        )
        self.updated_at = datetime.now(UTC)
        self.updated_by = granted_by

    def remove_group(self, group_name: str) -> None:
        """Remove a group from the allowed list."""
        self.allowed_groups = [g for g in self.allowed_groups if g != group_name]
        self.entries = [
            e for e in self.entries
            if not (e.principal_type == "group" and e.principal_id == group_name)
        ]
        self.updated_at = datetime.now(UTC)

    def deny_user(self, user_id: UUID, denied_by: UUID | None = None) -> None:
        """Explicitly deny access to a user."""
        if user_id not in self.denied_users:
            self.denied_users.append(user_id)

        self.entries.append(
            ACLEntry(
                principal_type="user",
                principal_id=str(user_id),
                permission="read",
                granted=False,
                granted_by=denied_by,
            ),
        )
        self.updated_at = datetime.now(UTC)
        self.updated_by = denied_by

    def deny_group(self, group_name: str, denied_by: UUID | None = None) -> None:
        """Explicitly deny access to a group."""
        if group_name not in self.denied_groups:
            self.denied_groups.append(group_name)

        self.entries.append(
            ACLEntry(
                principal_type="group",
                principal_id=group_name,
                permission="read",
                granted=False,
                granted_by=denied_by,
            ),
        )
        self.updated_at = datetime.now(UTC)
        self.updated_by = denied_by


class ACLUpdateRequest(BaseModel):
    """Request model for updating document ACL."""

    visibility: Visibility | None = None
    allowed_users: list[UUID] | None = None
    allowed_groups: list[str] | None = None
    denied_users: list[UUID] | None = None
    denied_groups: list[str] | None = None


class ShareRequest(BaseModel):
    """Request model for sharing a document."""

    user_ids: list[UUID] = Field(
        default_factory=list,
        description="Users to share with",
    )
    group_names: list[str] = Field(
        default_factory=list,
        description="Groups to share with",
    )
    permission: str = Field(
        default="read",
        description="Permission level to grant",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration for the share",
    )
    notify: bool = Field(
        default=False,
        description="Whether to notify recipients",
    )


class BulkACLUpdateRequest(BaseModel):
    """Request model for bulk ACL updates."""

    document_ids: list[UUID] = Field(
        ...,
        description="Documents to update",
    )
    visibility: Visibility | None = None
    add_users: list[UUID] = Field(default_factory=list)
    remove_users: list[UUID] = Field(default_factory=list)
    add_groups: list[str] = Field(default_factory=list)
    remove_groups: list[str] = Field(default_factory=list)
