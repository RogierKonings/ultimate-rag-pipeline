"""Add indexing status tracking fields to documents.

Revision ID: 007_indexing_status_tracking
Revises: 006_video_chunks
Create Date: 2026-01-14 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "007_indexing_status_tracking"
down_revision: str | None = "006_video_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create index_status enum type
    index_status_enum = postgresql.ENUM(
        "pending",
        "ok",
        "error",
        "stale",
        name="index_status",
        create_type=True,
    )
    index_status_enum.create(op.get_bind(), checkfirst=True)

    # Add indexing status columns to documents table
    op.add_column(
        "documents",
        sa.Column(
            "qdrant_status",
            index_status_enum,
            server_default="pending",
            nullable=False,
            comment="Qdrant vector store indexing status",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "opensearch_status",
            index_status_enum,
            server_default="pending",
            nullable=False,
            comment="OpenSearch keyword index status",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_indexed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of last successful indexing to any store",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_index_error",
            sa.Text,
            nullable=True,
            comment="Last indexing error message for debugging",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "index_attempts",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment="Number of indexing attempts (for exponential backoff)",
        ),
    )

    # Create indexes for efficient status queries
    op.create_index(
        "ix_documents_qdrant_status",
        "documents",
        ["qdrant_status"],
    )
    op.create_index(
        "ix_documents_opensearch_status",
        "documents",
        ["opensearch_status"],
    )
    op.create_index(
        "ix_documents_sync_status",
        "documents",
        ["tenant_id", "qdrant_status", "opensearch_status"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_documents_sync_status")
    op.drop_index("ix_documents_opensearch_status")
    op.drop_index("ix_documents_qdrant_status")

    # Drop columns
    op.drop_column("documents", "index_attempts")
    op.drop_column("documents", "last_index_error")
    op.drop_column("documents", "last_indexed_at")
    op.drop_column("documents", "opensearch_status")
    op.drop_column("documents", "qdrant_status")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS index_status")
