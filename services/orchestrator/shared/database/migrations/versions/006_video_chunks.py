"""Video chunks table for content fusion.

Revision ID: 006_video_chunks
Revises: 005_video_tables
Create Date: 2024-01-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_video_chunks"
down_revision: str | None = "005_video_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create video_chunks table for multi-modal content fusion."""
    # Create video_chunks table
    op.create_table(
        "video_chunks",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_time_ms", sa.Integer(), nullable=False),
        sa.Column("end_time_ms", sa.Integer(), nullable=False),
        # Content fields
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("scene_description", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("fused_text", sa.Text(), nullable=False),
        # Keyframe reference
        sa.Column("keyframe_path", sa.String(1000), nullable=True),
        sa.Column("keyframe_index", sa.Integer(), nullable=True),
        # Source tracking
        sa.Column(
            "source_modalities",
            sa.ARRAY(sa.String(50)),
            nullable=False,
            server_default="{}",
        ),
        # Embedding reference
        sa.Column("embedding_id", sa.String(100), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["source_videos.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("video_id", "chunk_index", name="uq_video_chunks_video_index"),
    )

    # Create indexes
    op.create_index(
        "idx_video_chunks_video",
        "video_chunks",
        ["video_id"],
    )
    op.create_index(
        "idx_video_chunks_tenant",
        "video_chunks",
        ["tenant_id"],
    )
    op.create_index(
        "idx_video_chunks_time",
        "video_chunks",
        ["video_id", "start_time_ms"],
    )
    op.create_index(
        "idx_video_chunks_embedding",
        "video_chunks",
        ["embedding_id"],
        postgresql_where=sa.text("embedding_id IS NOT NULL"),
    )

    # Full-text search index on fused_text
    op.execute(
        """
        CREATE INDEX idx_video_chunks_fused_text_gin
        ON video_chunks
        USING gin(to_tsvector('english', fused_text))
        """
    )


def downgrade() -> None:
    """Drop video_chunks table."""
    op.drop_index("idx_video_chunks_fused_text_gin", table_name="video_chunks")
    op.drop_index("idx_video_chunks_embedding", table_name="video_chunks")
    op.drop_index("idx_video_chunks_time", table_name="video_chunks")
    op.drop_index("idx_video_chunks_tenant", table_name="video_chunks")
    op.drop_index("idx_video_chunks_video", table_name="video_chunks")
    op.drop_table("video_chunks")
