"""Add tenant isolation configuration fields.

Revision ID: 008_tenant_isolation
Revises: 007_indexing_status_tracking
Create Date: 2026-01-14

This migration adds fields to support per-tenant index/collection isolation:
- isolation_mode: Whether tenant uses shared or dedicated indices
- qdrant_collection_name: Custom Qdrant collection name
- qdrant_settings: Custom HNSW/optimizer settings for Qdrant
- opensearch_index_name: Custom OpenSearch index name
- opensearch_settings: Custom OpenSearch index settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "008_tenant_isolation"
down_revision: str | None = "007a_create_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add isolation_mode column with default "shared" for backward compatibility
    op.add_column(
        "tenants",
        sa.Column(
            "isolation_mode",
            sa.String(20),
            server_default="shared",
            nullable=False,
            comment="Index isolation mode: shared or dedicated",
        ),
    )

    # Add Qdrant configuration columns
    op.add_column(
        "tenants",
        sa.Column(
            "qdrant_collection_name",
            sa.String(255),
            nullable=True,
            comment="Custom Qdrant collection name (null = use default)",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "qdrant_settings",
            postgresql.JSONB,
            nullable=True,
            comment="Custom HNSW/optimization settings for Qdrant",
        ),
    )

    # Add OpenSearch configuration columns
    op.add_column(
        "tenants",
        sa.Column(
            "opensearch_index_name",
            sa.String(255),
            nullable=True,
            comment="Custom OpenSearch index name (null = use default)",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "opensearch_settings",
            postgresql.JSONB,
            nullable=True,
            comment="Custom OpenSearch index settings",
        ),
    )

    # Create index for isolation mode queries (e.g., finding all dedicated tenants)
    op.create_index(
        "ix_tenants_isolation_mode",
        "tenants",
        ["isolation_mode"],
    )


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_tenants_isolation_mode", table_name="tenants")

    # Drop columns in reverse order
    op.drop_column("tenants", "opensearch_settings")
    op.drop_column("tenants", "opensearch_index_name")
    op.drop_column("tenants", "qdrant_settings")
    op.drop_column("tenants", "qdrant_collection_name")
    op.drop_column("tenants", "isolation_mode")
