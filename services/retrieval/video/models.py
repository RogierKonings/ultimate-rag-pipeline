"""Video retrieval data models.

This module defines Pydantic models for video search requests,
responses, and internal data structures.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class VideoSearchMode(str, Enum):
    """Search mode selection."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class VideoMatch(BaseModel):
    """A matching segment within a video.

    Represents a time-aligned chunk that matched the search query.
    """

    chunk_id: UUID = Field(description="Chunk UUID")
    chunk_index: int = Field(description="Chunk index within video")
    start_time_ms: int = Field(description="Start time in milliseconds")
    end_time_ms: int = Field(description="End time in milliseconds")
    fused_score: float = Field(description="Final relevance score")
    semantic_score: float | None = Field(
        default=None,
        description="Semantic similarity score",
    )
    keyword_score: float | None = Field(
        default=None,
        description="BM25 keyword score",
    )
    rerank_score: float | None = Field(
        default=None,
        description="Cross-encoder rerank score",
    )
    fused_text_preview: str = Field(
        default="",
        description="Preview of matched content (truncated)",
    )
    transcript_text: str | None = Field(
        default=None,
        description="Transcript text for this segment",
    )
    scene_description: str | None = Field(
        default=None,
        description="Scene description for this segment",
    )
    keyframe_url: str | None = Field(
        default=None,
        description="URL to representative keyframe image",
    )
    clip_url: str | None = Field(
        default=None,
        description="URL to video clip for this segment",
    )
    source_modalities: list[str] = Field(
        default_factory=list,
        description="Content modalities present (speech, visual, ocr)",
    )

    @property
    def duration_seconds(self) -> float:
        """Get match duration in seconds."""
        return (self.end_time_ms - self.start_time_ms) / 1000.0

    @property
    def start_seconds(self) -> float:
        """Get start time in seconds."""
        return self.start_time_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        """Get end time in seconds."""
        return self.end_time_ms / 1000.0


class VideoResult(BaseModel):
    """Search results for a single video.

    Groups all matching segments from one video together.
    """

    video_id: UUID = Field(description="Video UUID")
    tenant_id: UUID = Field(description="Tenant UUID")
    title: str = Field(default="", description="Video title")
    thumbnail_url: str | None = Field(
        default=None,
        description="URL to video thumbnail",
    )
    duration_ms: int | None = Field(
        default=None,
        description="Total video duration in milliseconds",
    )
    max_score: float = Field(description="Highest match score in this video")
    avg_score: float = Field(description="Average match score in this video")
    match_count: int = Field(description="Number of matching segments")
    matches: list[VideoMatch] = Field(
        default_factory=list,
        description="Matching segments sorted by timestamp",
    )
    visibility: str = Field(default="private", description="Video visibility")

    class Config:
        """Pydantic config."""

        from_attributes = True


class VideoSearchMetrics(BaseModel):
    """Performance metrics for video search stages."""

    query_embedding_ms: float = Field(
        default=0,
        description="Time to generate query embedding",
    )
    semantic_search_ms: float = Field(
        default=0,
        description="Time for Qdrant semantic search",
    )
    keyword_search_ms: float = Field(
        default=0,
        description="Time for OpenSearch keyword search",
    )
    fusion_ms: float = Field(
        default=0,
        description="Time for RRF fusion",
    )
    rerank_ms: float = Field(
        default=0,
        description="Time for reranking",
    )
    grouping_ms: float = Field(
        default=0,
        description="Time for result grouping",
    )
    total_ms: float = Field(
        default=0,
        description="Total end-to-end time",
    )
    semantic_count: int = Field(
        default=0,
        description="Results from semantic search",
    )
    keyword_count: int = Field(
        default=0,
        description="Results from keyword search",
    )
    fused_count: int = Field(
        default=0,
        description="Results after fusion",
    )
    final_count: int = Field(
        default=0,
        description="Final results returned",
    )


class VideoTimelineResponse(BaseModel):
    """Response for video timeline search.

    Contains grouped results by video with timing information.
    """

    query: str = Field(description="Original search query")
    mode: VideoSearchMode = Field(description="Search mode used")
    videos: list[VideoResult] = Field(
        default_factory=list,
        description="Videos with matching segments",
    )
    total_videos: int = Field(
        default=0,
        description="Total number of videos with matches",
    )
    total_matches: int = Field(
        default=0,
        description="Total number of matching segments",
    )
    metrics: VideoSearchMetrics = Field(
        default_factory=VideoSearchMetrics,
        description="Search performance metrics",
    )

    class Config:
        """Pydantic config."""

        from_attributes = True
