"""Add video tables: source_videos, video_transcripts, video_keyframes

Revision ID: 005_video_tables
Revises: 004_evaluation_tables
Create Date: 2026-01-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_video_tables"
down_revision: str | None = "004_evaluation_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create video status enum (create_type=False to avoid double creation)
    video_status_enum = postgresql.ENUM(
        "pending",
        "uploaded",
        "processing",
        "completed",
        "failed",
        name="video_status",
        create_type=False,
    )
    video_status_enum.create(op.get_bind(), checkfirst=True)

    # Create processing stage enum (create_type=False to avoid double creation)
    processing_stage_enum = postgresql.ENUM(
        "uploaded",
        "validating",
        "extracting_audio",
        "transcribing",
        "detecting_scenes",
        "extracting_keyframes",
        "analyzing_vision",
        "extracting_ocr",
        "fusing_content",
        "embedding",
        "indexing",
        "completed",
        "failed",
        name="processing_stage",
        create_type=False,
    )
    processing_stage_enum.create(op.get_bind(), checkfirst=True)

    # Create source_videos table
    op.create_table(
        "source_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Tenant ID for multi-tenancy isolation",
        ),
        sa.Column(
            "filename",
            sa.String(500),
            nullable=False,
            comment="Original filename of the uploaded video",
        ),
        sa.Column(
            "title", sa.String(500), nullable=True, comment="User-provided or extracted title"
        ),
        sa.Column("description", sa.Text, nullable=True, comment="Video description"),
        sa.Column(
            "duration_seconds",
            sa.Float,
            nullable=True,
            comment="Video duration in seconds",
        ),
        sa.Column("width", sa.Integer, nullable=True, comment="Video width in pixels"),
        sa.Column("height", sa.Integer, nullable=True, comment="Video height in pixels"),
        sa.Column("fps", sa.Float, nullable=True, comment="Frames per second"),
        sa.Column("codec", sa.String(50), nullable=True, comment="Video codec"),
        sa.Column(
            "file_size_bytes",
            sa.BigInteger,
            nullable=True,
            comment="File size in bytes",
        ),
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=True,
            comment="SHA-256 hash of video content for deduplication",
        ),
        sa.Column(
            "storage_path",
            sa.String(1000),
            nullable=False,
            comment="Path to video file in MinIO",
        ),
        sa.Column(
            "thumbnail_path",
            sa.String(1000),
            nullable=True,
            comment="Path to video thumbnail in MinIO",
        ),
        sa.Column(
            "status",
            video_status_enum,
            server_default="pending",
            nullable=False,
            comment="Overall video status",
        ),
        sa.Column(
            "processing_stage",
            processing_stage_enum,
            nullable=True,
            comment="Current processing stage",
        ),
        sa.Column(
            "processing_progress",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment="Processing progress percentage (0-100)",
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="Error message if processing failed",
        ),
        sa.Column(
            "visibility",
            sa.String(20),
            server_default="private",
            nullable=False,
            comment="Visibility: public, private, group",
        ),
        sa.Column(
            "allowed_groups",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
            comment="List of group UUIDs with access",
        ),
        sa.Column(
            "processing_options",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
            comment="Processing options (whisper model, vision provider, etc.)",
        ),
        sa.Column(
            "detected_language",
            sa.String(10),
            nullable=True,
            comment="Detected audio language code",
        ),
        sa.Column(
            "keyframe_count",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment="Number of extracted keyframes",
        ),
        sa.Column(
            "chunk_count",
            sa.Integer,
            server_default="0",
            nullable=False,
            comment="Number of video chunks created",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when upload completed",
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when processing completed",
        ),
    )

    # Create source_videos indexes
    op.create_index("ix_source_videos_tenant_id", "source_videos", ["tenant_id"])
    op.create_index("ix_source_videos_status", "source_videos", ["status"])
    op.create_index("ix_source_videos_content_hash", "source_videos", ["content_hash"])
    op.create_index(
        "ix_source_videos_tenant_status", "source_videos", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_source_videos_tenant_created", "source_videos", ["tenant_id", "created_at"]
    )

    # Create video_transcripts table
    op.create_table(
        "video_transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "video_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "segment_index",
            sa.Integer,
            nullable=False,
            comment="Order of this segment within the video",
        ),
        sa.Column(
            "start_ms",
            sa.Integer,
            nullable=False,
            comment="Start time in milliseconds",
        ),
        sa.Column(
            "end_ms",
            sa.Integer,
            nullable=False,
            comment="End time in milliseconds",
        ),
        sa.Column("text", sa.Text, nullable=False, comment="Transcribed text"),
        sa.Column(
            "words_json",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
            comment="Word-level timestamps [{word, start, end}]",
        ),
        sa.Column(
            "language",
            sa.String(10),
            nullable=True,
            comment="Detected language code for this segment",
        ),
        sa.Column(
            "confidence",
            sa.Float,
            nullable=True,
            comment="Transcription confidence score",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Create video_transcripts indexes
    op.create_index("ix_video_transcripts_video_id", "video_transcripts", ["video_id"])
    op.create_index(
        "ix_video_transcripts_video_segment",
        "video_transcripts",
        ["video_id", "segment_index"],
        unique=True,
    )
    op.create_index(
        "ix_video_transcripts_video_time",
        "video_transcripts",
        ["video_id", "start_ms"],
    )

    # Create video_keyframes table
    op.create_table(
        "video_keyframes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "video_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "frame_index",
            sa.Integer,
            nullable=False,
            comment="Order of this keyframe within the video",
        ),
        sa.Column(
            "timestamp_ms",
            sa.Integer,
            nullable=False,
            comment="Keyframe timestamp in milliseconds",
        ),
        sa.Column(
            "storage_path",
            sa.String(1000),
            nullable=False,
            comment="Path to keyframe image in MinIO",
        ),
        sa.Column(
            "thumbnail_path",
            sa.String(1000),
            nullable=True,
            comment="Path to thumbnail in MinIO",
        ),
        sa.Column(
            "scene_description",
            sa.Text,
            nullable=True,
            comment="Vision LLM scene description",
        ),
        sa.Column(
            "ocr_text",
            sa.Text,
            nullable=True,
            comment="Extracted OCR text from keyframe",
        ),
        sa.Column(
            "is_scene_boundary",
            sa.Boolean,
            server_default="false",
            nullable=False,
            comment="Whether this keyframe is at a scene boundary",
        ),
        sa.Column(
            "scene_index",
            sa.Integer,
            nullable=True,
            comment="Index of the scene this keyframe belongs to",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Create video_keyframes indexes
    op.create_index("ix_video_keyframes_video_id", "video_keyframes", ["video_id"])
    op.create_index(
        "ix_video_keyframes_video_frame",
        "video_keyframes",
        ["video_id", "frame_index"],
        unique=True,
    )
    op.create_index(
        "ix_video_keyframes_video_time",
        "video_keyframes",
        ["video_id", "timestamp_ms"],
    )
    op.create_index(
        "ix_video_keyframes_scene_boundary",
        "video_keyframes",
        ["video_id", "is_scene_boundary"],
    )


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table("video_keyframes")
    op.drop_table("video_transcripts")
    op.drop_table("source_videos")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS processing_stage")
    op.execute("DROP TYPE IF EXISTS video_status")
