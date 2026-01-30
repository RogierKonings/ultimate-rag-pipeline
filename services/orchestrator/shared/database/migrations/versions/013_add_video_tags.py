"""Add tags column to source_videos table.

Revision ID: 013_add_video_tags
Revises: 012_user_management_tables
Create Date: 2026-01-20

This migration adds the tags column that was missing from the original
video tables migration but is expected by the VideoRegisterRequest schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "013_add_video_tags"
down_revision: str | None = "012_user_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_videos",
        sa.Column(
            "tags",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
            comment="Tags for categorization",
        ),
    )

    # Create GIN index for efficient tag queries
    op.create_index(
        "ix_source_videos_tags",
        "source_videos",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_source_videos_tags", table_name="source_videos")
    op.drop_column("source_videos", "tags")
