"""
Video models for the Video RAG Pipeline.

This module defines SQLAlchemy models for storing video metadata,
transcripts, and keyframes.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class VideoStatus(str, enum.Enum):
    """Video processing status."""

    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingStage(str, enum.Enum):
    """Video processing stages."""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    DETECTING_SCENES = "detecting_scenes"
    EXTRACTING_KEYFRAMES = "extracting_keyframes"
    ANALYZING_VISION = "analyzing_vision"
    EXTRACTING_OCR = "extracting_ocr"
    FUSING_CONTENT = "fusing_content"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceVideo(Base):
    """
    Represents a source video in the Video RAG pipeline.

    Stores metadata about uploaded videos including processing status,
    video properties, and access control settings.
    """

    __tablename__ = "source_videos"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Multi-tenancy
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # Video identification
    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Original filename of the uploaded video",
    )
    title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="User-provided or extracted title",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Video description",
    )

    # Video properties
    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Video duration in seconds",
    )
    width: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Video width in pixels",
    )
    height: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Video height in pixels",
    )
    fps: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Frames per second",
    )
    codec: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Video codec",
    )
    file_size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="File size in bytes",
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 hash for deduplication",
    )

    # Storage paths
    storage_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="Path to video file in MinIO",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Path to video thumbnail in MinIO",
    )

    # Processing status
    status: Mapped[str] = mapped_column(
        String(20),
        default=VideoStatus.PENDING.value,
        nullable=False,
        comment="Overall video status",
    )
    processing_stage: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="Current processing stage",
    )
    processing_progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Processing progress percentage (0-100)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if processing failed",
    )

    # Access control
    visibility: Mapped[str] = mapped_column(
        String(20),
        default="private",
        nullable=False,
        comment="Visibility: public, private, group",
    )
    allowed_groups: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
        comment="List of group UUIDs with access",
    )

    # Processing configuration
    processing_options: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Processing options (whisper model, vision provider, etc.)",
    )

    # Extracted metadata
    detected_language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Detected audio language code",
    )
    keyframe_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of extracted keyframes",
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of video chunks created",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when upload completed",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when processing completed",
    )

    # Relationships
    transcripts: Mapped[list["VideoTranscript"]] = relationship(
        "VideoTranscript",
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    keyframes: Mapped[list["VideoKeyframe"]] = relationship(
        "VideoKeyframe",
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<SourceVideo(id={self.id}, title='{self.title}', status={self.status})>"


class VideoTranscript(Base):
    """
    Represents a transcript segment from a video.

    Stores speech-to-text transcription with word-level timestamps.
    """

    __tablename__ = "video_transcripts"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Video relationship
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video: Mapped["SourceVideo"] = relationship(
        "SourceVideo",
        back_populates="transcripts",
    )

    # Segment content
    segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Order of this segment within the video",
    )
    start_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Start time in milliseconds",
    )
    end_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="End time in milliseconds",
    )
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Transcribed text",
    )
    words_json: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
        comment="Word-level timestamps [{word, start, end}]",
    )

    # Metadata
    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Detected language code for this segment",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Transcription confidence score",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<VideoTranscript(id={self.id}, video_id={self.video_id}, segment={self.segment_index})>"


class VideoKeyframe(Base):
    """
    Represents an extracted keyframe from a video.

    Stores keyframe metadata, scene descriptions from vision LLM,
    and OCR-extracted text.
    """

    __tablename__ = "video_keyframes"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Video relationship
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video: Mapped["SourceVideo"] = relationship(
        "SourceVideo",
        back_populates="keyframes",
    )

    # Frame metadata
    frame_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Order of this keyframe within the video",
    )
    timestamp_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Keyframe timestamp in milliseconds",
    )

    # Storage paths
    storage_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="Path to keyframe image in MinIO",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Path to thumbnail in MinIO",
    )

    # Content analysis
    scene_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Vision LLM scene description",
    )
    ocr_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Extracted OCR text from keyframe",
    )

    # Scene detection
    is_scene_boundary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether this keyframe is at a scene boundary",
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Index of the scene this keyframe belongs to",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<VideoKeyframe(id={self.id}, video_id={self.video_id}, frame={self.frame_index})>"
