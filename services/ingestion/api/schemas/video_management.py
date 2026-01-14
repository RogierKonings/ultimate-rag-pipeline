"""Video management API schemas.

Pydantic models for video CRUD operations, pagination, and deletion.
"""

from datetime import datetime
from uuid import UUID

from api.schemas.video import VideoStatus, VideoVisibility
from pydantic import BaseModel, ConfigDict, Field


class VideoUpdateRequest(BaseModel):
    """Request body for video update."""

    title: str | None = Field(
        default=None,
        max_length=500,
        description="New video title",
    )
    description: str | None = Field(
        default=None,
        description="New video description",
    )
    visibility: VideoVisibility | None = Field(
        default=None,
        description="New visibility setting",
    )
    allowed_groups: list[UUID] | None = Field(
        default=None,
        description="Updated group UUIDs with access",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Updated tags",
    )


class VideoResponse(BaseModel):
    """Standard video response after update."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Video identifier")
    tenant_id: UUID = Field(description="Tenant identifier")
    title: str | None = Field(description="Video title")
    description: str | None = Field(description="Video description")
    status: VideoStatus = Field(description="Current status")
    visibility: str = Field(description="Visibility setting")
    allowed_groups: list[UUID] = Field(
        default_factory=list,
        description="Groups with access",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags",
    )
    updated_at: datetime = Field(description="Last update timestamp")


class VideoDetailResponse(BaseModel):
    """Full video detail response."""

    model_config = ConfigDict(from_attributes=True)

    video_id: UUID = Field(description="Video identifier")
    tenant_id: UUID = Field(description="Tenant identifier")
    filename: str = Field(description="Original filename")
    title: str | None = Field(description="Video title")
    description: str | None = Field(description="Video description")

    # Video properties
    duration_ms: int | None = Field(description="Video duration in milliseconds")
    duration_seconds: float | None = Field(description="Video duration in seconds")
    width: int | None = Field(description="Video width in pixels")
    height: int | None = Field(description="Video height in pixels")
    fps: float | None = Field(description="Frames per second")
    codec: str | None = Field(description="Video codec")
    file_size_bytes: int | None = Field(description="File size in bytes")

    # Processing status
    status: VideoStatus = Field(description="Current status")
    processing_stage: str | None = Field(description="Processing stage")
    processing_progress: int = Field(description="Progress percentage")
    error_message: str | None = Field(description="Error message if failed")

    # Content info
    detected_language: str | None = Field(description="Detected audio language")
    keyframe_count: int = Field(default=0, description="Number of keyframes")
    chunk_count: int = Field(default=0, description="Number of chunks")

    # Access control
    visibility: str = Field(description="Visibility setting")
    allowed_groups: list[UUID] = Field(
        default_factory=list,
        description="Groups with access",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags",
    )

    # URLs (presigned)
    thumbnail_url: str | None = Field(description="Thumbnail URL")
    stream_url: str | None = Field(description="Video streaming URL")
    storage_path: str | None = Field(description="Storage path in MinIO")

    # Timestamps
    created_at: datetime = Field(description="Creation timestamp")
    uploaded_at: datetime | None = Field(description="Upload timestamp")
    processed_at: datetime | None = Field(description="Processing timestamp")
    updated_at: datetime | None = Field(description="Last update timestamp")


class VideoListRequest(BaseModel):
    """Query parameters for video list."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Items per page",
    )
    status: VideoStatus | None = Field(
        default=None,
        description="Filter by status",
    )
    search: str | None = Field(
        default=None,
        max_length=200,
        description="Search in title and description",
    )
    sort_by: str = Field(
        default="created_at",
        description="Sort field: created_at, title, duration",
    )
    sort_order: str = Field(
        default="desc",
        description="Sort order: asc, desc",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter by tags (any match)",
    )


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    total: int = Field(description="Total items matching filters")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether next page exists")
    has_prev: bool = Field(description="Whether previous page exists")


class VideoListResponse(BaseModel):
    """Response for video list endpoint."""

    videos: list[VideoDetailResponse] = Field(description="List of videos")
    pagination: PaginationMeta = Field(description="Pagination metadata")


class DeletionCounts(BaseModel):
    """Counts of deleted items."""

    qdrant_vectors: int = Field(
        default=0,
        description="Vectors deleted from Qdrant",
    )
    opensearch_documents: int = Field(
        default=0,
        description="Documents deleted from OpenSearch",
    )
    postgres_chunks: int = Field(
        default=0,
        description="Chunks deleted from PostgreSQL",
    )
    minio_files: int = Field(
        default=0,
        description="Files deleted from MinIO",
    )


class VideoDeleteResponse(BaseModel):
    """Response for video deletion."""

    video_id: UUID = Field(description="Deleted video ID")
    success: bool = Field(description="Whether deletion succeeded")
    message: str = Field(description="Status message")
    deletion_counts: DeletionCounts = Field(
        default_factory=DeletionCounts,
        description="Counts of deleted items",
    )


class VideoChunkResponse(BaseModel):
    """Response for a single video chunk."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID = Field(description="Chunk identifier")
    chunk_index: int = Field(description="Index within video")
    start_time_ms: int = Field(description="Start time in milliseconds")
    end_time_ms: int = Field(description="End time in milliseconds")
    start_seconds: float = Field(description="Start time in seconds")
    end_seconds: float = Field(description="End time in seconds")
    duration_seconds: float = Field(description="Duration in seconds")
    fused_text_preview: str = Field(description="Preview of fused text (500 chars)")
    transcript_text: str | None = Field(description="Transcript text")
    scene_description: str | None = Field(description="Scene description")
    ocr_text: str | None = Field(description="OCR text")
    source_modalities: list[str] = Field(
        default_factory=list,
        description="Content modalities present",
    )
    keyframe_url: str | None = Field(description="Keyframe URL")
    embedding_id: str | None = Field(description="Embedding ID in vector store")


class VideoChunksResponse(BaseModel):
    """Response for video chunks list."""

    video_id: UUID = Field(description="Video identifier")
    chunks: list[VideoChunkResponse] = Field(description="List of chunks")
    total_chunks: int = Field(description="Total chunk count")
    pagination: PaginationMeta = Field(description="Pagination metadata")


class KeyframeResponse(BaseModel):
    """Response for keyframe redirect."""

    keyframe_url: str = Field(description="Presigned URL to keyframe")
    frame_index: int = Field(description="Frame index")
    timestamp_ms: int = Field(description="Frame timestamp")


class ReprocessResponse(BaseModel):
    """Response for video reprocess request."""

    video_id: UUID = Field(description="Video identifier")
    job_id: UUID = Field(description="New processing job ID")
    status: VideoStatus = Field(description="New status")
    message: str = Field(description="Status message")
