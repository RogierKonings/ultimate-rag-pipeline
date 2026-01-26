"""Video API schemas.

Pydantic models for video upload, status, and management endpoints.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VideoStatus(str, Enum):
    """Video processing status."""

    PENDING = "pending"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingStage(str, Enum):
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


class VideoVisibility(str, Enum):
    """Video visibility options."""

    PUBLIC = "public"
    PRIVATE = "private"
    GROUP = "group"


class VideoProcessingOptions(BaseModel):
    """Video processing configuration options."""

    whisper_model: str = Field(
        default="base",
        description="Whisper model to use: tiny, base, small, medium, large-v3",
    )
    whisper_language: str | None = Field(
        default=None,
        description="Language code for transcription (None for auto-detection)",
    )
    vision_provider: str = Field(
        default="openai",
        description="Vision LLM provider: openai, anthropic, ollama",
    )
    enable_vision: bool = Field(
        default=True,
        description="Whether to analyze keyframes with vision LLM",
    )
    enable_ocr: bool = Field(
        default=True,
        description="Whether to extract text via OCR",
    )
    scene_detection_threshold: float = Field(
        default=27.0,
        description="Scene detection sensitivity threshold",
    )
    keyframe_interval_seconds: float = Field(
        default=5.0,
        description="Fallback keyframe interval for static videos",
    )
    chunk_duration_seconds: float = Field(
        default=20.0,
        description="Target chunk duration for content fusion",
    )


class VideoUploadRequest(BaseModel):
    """Request body for video upload metadata."""

    title: str | None = Field(
        default=None,
        max_length=500,
        description="Video title (defaults to filename)",
    )
    description: str | None = Field(
        default=None,
        description="Video description",
    )
    visibility: VideoVisibility = Field(
        default=VideoVisibility.PRIVATE,
        description="Video visibility setting",
    )
    allowed_groups: list[UUID] = Field(
        default_factory=list,
        description="Group UUIDs with access (for group visibility)",
    )
    processing_options: VideoProcessingOptions = Field(
        default_factory=VideoProcessingOptions,
        description="Video processing configuration",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization",
    )


class VideoUploadResponse(BaseModel):
    """Response for video upload."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Unique video identifier")
    job_id: UUID = Field(description="Processing job identifier")
    filename: str = Field(description="Original filename")
    status: VideoStatus = Field(description="Current video status")
    storage_path: str = Field(description="Path to video in storage")
    message: str = Field(description="Status message")


class PresignedUploadResponse(BaseModel):
    """Response for presigned upload URL request."""

    video_id: UUID = Field(description="Video ID for the upload")
    upload_url: str = Field(description="Presigned URL for uploading video")
    expires_at: datetime = Field(description="URL expiration time")
    storage_path: str = Field(description="Expected storage path after upload")


class PresignedUploadRequest(BaseModel):
    """Request for presigned upload URL."""

    filename: str = Field(description="Original filename")
    content_type: str = Field(
        default="video/mp4",
        description="MIME type of the video",
    )
    file_size_bytes: int = Field(
        gt=0,
        description="Expected file size in bytes",
    )
    title: str | None = Field(
        default=None,
        max_length=500,
        description="Video title",
    )
    description: str | None = Field(
        default=None,
        description="Video description",
    )
    visibility: VideoVisibility = Field(
        default=VideoVisibility.PRIVATE,
        description="Video visibility setting",
    )
    allowed_groups: list[UUID] = Field(
        default_factory=list,
        description="Group UUIDs with access",
    )
    processing_options: VideoProcessingOptions = Field(
        default_factory=VideoProcessingOptions,
        description="Video processing configuration",
    )


class VideoStatusResponse(BaseModel):
    """Response for video processing status."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Video identifier")
    status: VideoStatus = Field(description="Current status")
    processing_stage: ProcessingStage | None = Field(
        default=None,
        description="Current processing stage",
    )
    processing_progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Processing progress percentage",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if processing failed",
    )
    duration_seconds: float | None = Field(
        default=None,
        description="Video duration in seconds",
    )
    keyframe_count: int = Field(
        default=0,
        description="Number of extracted keyframes",
    )
    chunk_count: int = Field(
        default=0,
        description="Number of video chunks created",
    )
    created_at: datetime = Field(description="Upload timestamp")
    processed_at: datetime | None = Field(
        default=None,
        description="Processing completion timestamp",
    )


class VideoMetadataResponse(BaseModel):
    """Full video metadata response."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Video identifier")
    tenant_id: UUID = Field(description="Tenant identifier")
    filename: str = Field(description="Original filename")
    title: str | None = Field(description="Video title")
    description: str | None = Field(description="Video description")

    # Video properties
    duration_seconds: float | None = Field(description="Video duration")
    width: int | None = Field(description="Video width in pixels")
    height: int | None = Field(description="Video height in pixels")
    fps: float | None = Field(description="Frames per second")
    codec: str | None = Field(description="Video codec")
    file_size_bytes: int | None = Field(description="File size in bytes")

    # Processing status
    status: VideoStatus = Field(description="Current status")
    processing_stage: ProcessingStage | None = Field(description="Processing stage")
    processing_progress: int = Field(description="Progress percentage")
    error_message: str | None = Field(description="Error message if failed")

    # Content info
    detected_language: str | None = Field(description="Detected audio language")
    keyframe_count: int = Field(description="Number of keyframes")
    chunk_count: int = Field(description="Number of chunks")

    # Access control
    visibility: str = Field(description="Visibility setting")
    allowed_groups: list[UUID] = Field(description="Groups with access")

    # URLs (presigned)
    thumbnail_url: str | None = Field(description="Thumbnail URL")
    stream_url: str | None = Field(description="Video streaming URL")

    # Timestamps
    created_at: datetime = Field(description="Creation timestamp")
    uploaded_at: datetime | None = Field(description="Upload timestamp")
    processed_at: datetime | None = Field(description="Processing timestamp")


class VideoListItem(BaseModel):
    """Video item in list response."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Video identifier")
    filename: str = Field(description="Original filename")
    title: str | None = Field(description="Video title")
    duration_seconds: float | None = Field(description="Video duration")
    status: VideoStatus = Field(description="Current status")
    thumbnail_url: str | None = Field(description="Thumbnail URL")
    created_at: datetime = Field(description="Creation timestamp")


class VideoListResponse(BaseModel):
    """Response for video list endpoint."""

    videos: list[VideoListItem] = Field(description="List of videos")
    total: int = Field(description="Total count matching filters")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    has_more: bool = Field(description="Whether more pages exist")


class VideoErrorResponse(BaseModel):
    """Error response for video operations."""

    error: str = Field(description="Error message")
    error_code: str = Field(description="Error code for programmatic handling")
    details: dict | None = Field(
        default=None,
        description="Additional error details",
    )


class VideoRegisterRequest(BaseModel):
    """Request to register a video that was already uploaded to storage.

    Use this when the client uploads directly to MinIO/S3 and then
    notifies the API to start processing.
    """

    filename: str = Field(description="Original filename")
    storage_path: str = Field(description="Path to the video in MinIO/S3 storage")
    title: str | None = Field(
        default=None,
        max_length=500,
        description="Video title (defaults to filename without extension)",
    )
    description: str | None = Field(
        default=None,
        description="Video description",
    )
    visibility: VideoVisibility = Field(
        default=VideoVisibility.PRIVATE,
        description="Video visibility setting",
    )
    allowed_groups: list[UUID] = Field(
        default_factory=list,
        description="Group UUIDs with access (for group visibility)",
    )
    processing_options: VideoProcessingOptions = Field(
        default_factory=VideoProcessingOptions,
        description="Video processing configuration",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization",
    )
