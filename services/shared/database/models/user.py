"""
User, Role, and Group models for RBAC.

This module defines the database models for user management,
role-based access control, and group membership.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, SoftDeleteMixin, TimestampMixin


class Tenant(Base, TimestampMixin, SoftDeleteMixin):
    """
    Represents a tenant in the multi-tenant system.

    Tenants provide isolation for users, documents, and all resources.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Tenant identification
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        comment="URL-friendly unique identifier",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Tenant type and status
    tenant_type: Mapped[str] = mapped_column(
        String(50),
        default="standard",
        nullable=False,
        comment="Type: standard, enterprise, trial",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Settings and configuration
    settings: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Tenant-specific settings and configuration",
    )

    # Feature flags
    features: Mapped[list] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        comment="Enabled features for this tenant",
    )

    # Quotas and limits
    max_users: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Maximum number of users allowed",
    )
    max_documents: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Maximum number of documents allowed",
    )
    max_storage_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Maximum storage in bytes",
    )

    # Contact information
    contact_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    groups: Mapped[list["Group"]] = relationship(
        "Group",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    roles: Mapped[list["RoleModel"]] = relationship(
        "RoleModel",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_tenants_slug", "slug"),
        Index("ix_tenants_type_active", "tenant_type", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class User(Base, TimestampMixin, SoftDeleteMixin):
    """
    Represents a user in the system.

    Users belong to a tenant and can have roles and group memberships.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Tenant relationship
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="users",
    )

    # User identification
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="External IdP user ID (e.g., Auth0 sub)",
    )

    # User profile
    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Authentication
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Hashed password (null for SSO-only users)",
    )
    is_sso_user: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    user_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional user metadata",
    )

    # Direct permissions (in addition to role-based)
    permissions: Mapped[list] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        comment="Explicit permissions granted to user",
    )

    # Relationships
    role_assignments: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    group_memberships: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint(
            "tenant_id", "username", name="uq_users_tenant_username",
        ),
        Index("ix_users_external_id", "external_id"),
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}')>"


class RoleModel(Base, TimestampMixin, SoftDeleteMixin):
    """
    Represents a role in the RBAC system.

    Roles define a set of permissions that can be assigned to users.
    Can be system-defined or tenant-specific custom roles.
    """

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Tenant relationship (null for system roles)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Null for system-defined roles",
    )
    tenant: Mapped[Optional["Tenant"]] = relationship(
        "Tenant",
        back_populates="roles",
    )

    # Role identification
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Role type
    is_system_role: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="System roles cannot be modified or deleted",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Default role assigned to new users",
    )

    # Permissions
    permissions: Mapped[list] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        comment="List of permission strings",
    )

    # Hierarchy
    parent_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        comment="Parent role for inheritance",
    )

    # Relationships
    user_assignments: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
        Index("ix_roles_system", "is_system_role"),
    )

    def __repr__(self) -> str:
        return f"<RoleModel(id={self.id}, name='{self.name}')>"


class Group(Base, TimestampMixin, SoftDeleteMixin):
    """
    Represents a group for document access control.

    Groups are used for document-level ACL, allowing access to be granted
    to sets of users.
    """

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Tenant relationship
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="groups",
    )

    # Group identification
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Group type
    group_type: Mapped[str] = mapped_column(
        String(50),
        default="custom",
        nullable=False,
        comment="Type: custom, department, project",
    )

    # Metadata
    group_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # Relationships
    user_memberships: Mapped[list["UserGroup"]] = relationship(
        "UserGroup",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_groups_tenant_name"),
        Index("ix_groups_tenant_type", "tenant_id", "group_type"),
    )

    def __repr__(self) -> str:
        return f"<Group(id={self.id}, name='{self.name}')>"


class UserRole(Base, TimestampMixin):
    """
    Association table for user-role relationships.

    Supports role assignment with optional expiration.
    """

    __tablename__ = "user_roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Relationships
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="role_assignments",
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped["RoleModel"] = relationship(
        "RoleModel",
        back_populates="user_assignments",
    )

    # Assignment metadata
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="User ID who assigned this role",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Role assignment expiration",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
        Index("ix_user_roles_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<UserRole(user_id={self.user_id}, role_id={self.role_id})>"


class UserGroup(Base, TimestampMixin):
    """
    Association table for user-group relationships.

    Supports group membership with optional expiration.
    """

    __tablename__ = "user_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Relationships
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="group_memberships",
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group: Mapped["Group"] = relationship(
        "Group",
        back_populates="user_memberships",
    )

    # Membership metadata
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="User ID who added this membership",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Group membership expiration",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_groups"),
        Index("ix_user_groups_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<UserGroup(user_id={self.user_id}, group_id={self.group_id})>"


class ApiKey(Base, TimestampMixin, SoftDeleteMixin):
    """
    API key for programmatic access.

    API keys are associated with a user and inherit their permissions.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # User relationship
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="api_keys",
    )

    # Key identification
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User-friendly name for the key",
    )
    key_prefix: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment="First 8 chars of the key for identification",
    )
    key_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Hashed API key",
    )

    # Key configuration
    scopes: Mapped[list] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
        comment="Permissions scoped to this key",
    )

    # Usage tracking
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Expiration
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_api_keys_prefix", "key_prefix"),
        Index("ix_api_keys_user_active", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, name='{self.name}', prefix='{self.key_prefix}')>"
