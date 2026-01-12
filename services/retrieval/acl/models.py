"""Pydantic models for ACL (Access Control List) functionality.

This module defines the data models used for access control enforcement
in the retrieval service.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class Visibility(str, Enum):
    """Document visibility levels.

    Determines who can access a document based on their relationship
    to the document and tenant.
    """

    PUBLIC = "public"  # Visible to everyone (including anonymous)
    PRIVATE = "private"  # Visible only to owner
    GROUP = "group"  # Visible to specific groups
    TENANT = "tenant"  # Visible to entire tenant


class UserContext(BaseModel):
    """User context extracted from JWT claims.

    This represents the authenticated user's identity and permissions
    for ACL filtering. Extracted from the Authorization header.
    """

    user_id: UUID = Field(..., description="Unique user identifier")
    tenant_id: UUID = Field(..., description="User's tenant identifier")
    groups: list[str] = Field(
        default_factory=list,
        description="Groups the user belongs to",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Roles assigned to the user",
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Explicit permissions granted",
    )

    # Optional metadata
    email: str | None = Field(default=None, description="User's email address")
    name: str | None = Field(default=None, description="User's display name")

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission.

        Args:
            permission: Permission string to check (e.g., 'read:documents').

        Returns:
            True if user has the permission, False otherwise.
        """
        return permission in self.permissions

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role.

        Args:
            role: Role name to check (e.g., 'admin', 'user').

        Returns:
            True if user has the role, False otherwise.
        """
        return role in self.roles

    def is_admin(self) -> bool:
        """Check if user has admin privileges.

        Returns:
            True if user has 'admin' role, False otherwise.
        """
        return "admin" in self.roles

    def is_member_of(self, group: str) -> bool:
        """Check if user is a member of a specific group.

        Args:
            group: Group name to check.

        Returns:
            True if user is a member of the group, False otherwise.
        """
        return group in self.groups

    @classmethod
    def anonymous(cls) -> "UserContext":
        """Create an anonymous user context with minimal permissions.

        Returns:
            UserContext for anonymous access (public docs only).
        """
        return cls(
            user_id=UUID(int=0),
            tenant_id=UUID(int=0),
            groups=[],
            roles=["anonymous"],
            permissions=["read:public"],
        )


class DocumentACL(BaseModel):
    """ACL metadata stored with each document.

    Documents are indexed with these fields for filtering during search.
    This model represents the access control configuration for a single document.
    """

    tenant_id: UUID = Field(..., description="Tenant that owns the document")
    visibility: Visibility = Field(
        default=Visibility.PRIVATE,
        description="Document visibility level",
    )
    owner_id: UUID | None = Field(
        default=None,
        description="User ID of the document owner",
    )
    allowed_groups: list[str] = Field(
        default_factory=list,
        description="Groups explicitly granted access",
    )
    allowed_users: list[UUID] = Field(
        default_factory=list,
        description="Users explicitly granted access",
    )
    denied_groups: list[str] = Field(
        default_factory=list,
        description="Groups explicitly denied access",
    )
    denied_users: list[UUID] = Field(
        default_factory=list,
        description="Users explicitly denied access",
    )


class ACLFilterConfig(BaseModel):
    """Configuration for ACL filtering behavior.

    Controls how access control is enforced during search operations.
    """

    enabled: bool = Field(default=True, description="Enable/disable ACL enforcement")
    admin_bypass: bool = Field(
        default=True,
        description="Allow admins to see all documents",
    )
    super_tenant_id: UUID | None = Field(
        default=None,
        description="Super tenant that can see all tenants",
    )
    default_visibility: Visibility = Field(
        default=Visibility.PRIVATE,
        description="Default visibility for documents without explicit ACL",
    )
