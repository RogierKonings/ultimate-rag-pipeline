"""Add user management tables (users, roles, groups, api_keys).

Revision ID: 012_user_management
Revises: 011_token_usage_tracking
Create Date: 2026-01-20

This migration adds user management tables:
- users: User accounts with tenant relationship
- roles: RBAC roles with permissions
- groups: Document access control groups
- user_roles: Association table for user-role relationships
- user_groups: Association table for user-group memberships
- api_keys: API keys for programmatic access
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "012_user_management"
down_revision: str | None = "011_token_usage_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column(
            "external_id",
            sa.String(255),
            nullable=True,
            comment="External IdP user ID (e.g., Auth0 sub)",
        ),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=True,
            comment="Hashed password (null for SSO-only users)",
        ),
        sa.Column("is_sso_user", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("is_verified", sa.Boolean, server_default="false", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_metadata",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
            comment="Additional user metadata",
        ),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String),
            server_default="{}",
            nullable=False,
            comment="Explicit permissions granted to user",
        ),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Users indexes and constraints
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_external_id", "users", ["external_id"])
    op.create_index("ix_users_tenant_active", "users", ["tenant_id", "is_active"])
    op.create_unique_constraint("uq_users_tenant_email", "users", ["tenant_id", "email"])
    op.create_unique_constraint(
        "uq_users_tenant_username", "users", ["tenant_id", "username"]
    )

    # Create roles table
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
            comment="Null for system-defined roles",
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "is_system_role",
            sa.Boolean,
            server_default="false",
            nullable=False,
            comment="System roles cannot be modified or deleted",
        ),
        sa.Column(
            "is_default",
            sa.Boolean,
            server_default="false",
            nullable=False,
            comment="Default role assigned to new users",
        ),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String),
            server_default="{}",
            nullable=False,
            comment="List of permission strings",
        ),
        sa.Column(
            "parent_role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="SET NULL"),
            nullable=True,
            comment="Parent role for inheritance",
        ),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Roles indexes and constraints
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])
    op.create_index("ix_roles_system", "roles", ["is_system_role"])
    op.create_unique_constraint("uq_roles_tenant_name", "roles", ["tenant_id", "name"])

    # Create groups table
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "group_type",
            sa.String(50),
            server_default="custom",
            nullable=False,
            comment="Type: custom, department, project",
        ),
        sa.Column(
            "group_metadata",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Groups indexes and constraints
    op.create_index("ix_groups_tenant_id", "groups", ["tenant_id"])
    op.create_index("ix_groups_tenant_type", "groups", ["tenant_id", "group_type"])
    op.create_unique_constraint("uq_groups_tenant_name", "groups", ["tenant_id", "name"])

    # Create user_roles association table
    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User ID who assigned this role",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Role assignment expiration",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # User_roles indexes and constraints
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_index("ix_user_roles_expires", "user_roles", ["expires_at"])
    op.create_unique_constraint("uq_user_roles", "user_roles", ["user_id", "role_id"])

    # Create user_groups association table
    op.create_table(
        "user_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User ID who added this membership",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Group membership expiration",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # User_groups indexes and constraints
    op.create_index("ix_user_groups_user_id", "user_groups", ["user_id"])
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])
    op.create_index("ix_user_groups_expires", "user_groups", ["expires_at"])
    op.create_unique_constraint("uq_user_groups", "user_groups", ["user_id", "group_id"])

    # Create api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="User-friendly name for the key",
        ),
        sa.Column(
            "key_prefix",
            sa.String(8),
            nullable=False,
            comment="First 8 chars of the key for identification",
        ),
        sa.Column(
            "key_hash",
            sa.String(255),
            nullable=False,
            comment="Hashed API key",
        ),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String),
            server_default="{}",
            nullable=False,
            comment="Permissions scoped to this key",
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Api_keys indexes
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_user_active", "api_keys", ["user_id", "status"])


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table("api_keys")
    op.drop_table("user_groups")
    op.drop_table("user_roles")
    op.drop_table("groups")
    op.drop_table("roles")
    op.drop_table("users")
