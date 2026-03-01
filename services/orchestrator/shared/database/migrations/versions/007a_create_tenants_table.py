"""Create tenants table.

Revision ID: 007a_create_tenants
Revises: 007_indexing_status_tracking
Create Date: 2026-01-14

This migration creates the tenants table which provides multi-tenant isolation.
The isolation-specific columns (isolation_mode, qdrant_collection_name, etc.)
are added in the subsequent migration 008_tenant_isolation.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007a_create_tenants"
down_revision: str | None = "007_indexing_status_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "slug",
            sa.String(100),
            nullable=False,
            comment="URL-friendly unique identifier",
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "tenant_type",
            sa.String(50),
            server_default="standard",
            nullable=False,
            comment="Type: standard, enterprise, trial",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "settings",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
            comment="Tenant-specific settings and configuration",
        ),
        sa.Column(
            "features",
            postgresql.ARRAY(sa.String),
            server_default="{}",
            nullable=False,
            comment="Enabled features for this tenant",
        ),
        sa.Column(
            "max_users",
            sa.Integer,
            nullable=True,
            comment="Maximum number of users allowed",
        ),
        sa.Column(
            "max_documents",
            sa.Integer,
            nullable=True,
            comment="Maximum number of documents allowed",
        ),
        sa.Column(
            "max_storage_bytes",
            sa.Integer,
            nullable=True,
            comment="Maximum storage in bytes",
        ),
        sa.Column("contact_email", sa.String(255), nullable=True),
        # SoftDeleteMixin
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # TimestampMixin
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

    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index(
        "ix_tenants_type_active", "tenants", ["tenant_type", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_type_active", table_name="tenants")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_constraint("uq_tenants_slug", "tenants", type_="unique")
    op.drop_table("tenants")
