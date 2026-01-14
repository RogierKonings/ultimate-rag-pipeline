"""Video retrieval API schemas.

Pydantic models for video search requests and responses.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class VideoSearchModeAPI(str, Enum):
    """Search mode selection for API."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class VideoRetrieveRequest(BaseModel):
    """Request body for video retrieval endpoint."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Search query text",
    )
    mode: VideoSearchModeAPI = Field(
        default=VideoSearchModeAPI.HYBRID,
        description="Search mode: hybrid, semantic, or keyword",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of videos to return",
    )
    video_id: UUID | None = Field(
        default=None,
        description="Filter to specific video UUID",
    )
    semantic_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight for semantic search (0-1)",
    )
    keyword_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for keyword search (0-1)",
    )
    rerank: bool = Field(
        default=True,
        description="Enable cross-encoder reranking",
    )
    max_matches_per_video: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum matches per video",
    )
    filters: dict | None = Field(
        default=None,
        description="Additional metadata filters",
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "query": "machine learning neural networks",
                "mode": "hybrid",
                "top_k": 10,
                "semantic_weight": 0.7,
                "keyword_weight": 0.3,
                "rerank": True,
            },
        }


class VideoMatchResponse(BaseModel):
    """A matching segment within a video."""

    chunk_id: UUID = Field(description="Chunk UUID")
    chunk_index: int = Field(description="Chunk index within video")
    start_time_ms: int = Field(description="Start time in milliseconds")
    end_time_ms: int = Field(description="End time in milliseconds")
    start_seconds: float = Field(description="Start time in seconds")
    end_seconds: float = Field(description="End time in seconds")
    duration_seconds: float = Field(description="Duration in seconds")
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
        description="Preview of matched content",
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
        description="Content modalities (speech, visual, ocr)",
    )


class VideoResultResponse(BaseModel):
    """Search results for a single video."""

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
    max_score: float = Field(description="Highest match score")
    avg_score: float = Field(description="Average match score")
    match_count: int = Field(description="Number of matching segments")
    matches: list[VideoMatchResponse] = Field(
        default_factory=list,
        description="Matching segments sorted by timestamp",
    )


class VideoSearchMetricsResponse(BaseModel):
    """Performance metrics for video search."""

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


class VideoRetrieveResponse(BaseModel):
    """Response for video timeline search."""

    query: str = Field(description="Original search query")
    mode: VideoSearchModeAPI = Field(description="Search mode used")
    videos: list[VideoResultResponse] = Field(
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
    metrics: VideoSearchMetricsResponse = Field(
        default_factory=VideoSearchMetricsResponse,
        description="Search performance metrics",
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "query": "machine learning",
                "mode": "hybrid",
                "videos": [
                    {
                        "video_id": "123e4567-e89b-12d3-a456-426614174000",
                        "tenant_id": "456e7890-e12b-34d5-a678-526614174000",
                        "title": "Introduction to Machine Learning",
                        "max_score": 0.95,
                        "avg_score": 0.87,
                        "match_count": 3,
                        "matches": [],
                    },
                ],
                "total_videos": 1,
                "total_matches": 3,
                "metrics": {
                    "total_ms": 150.5,
                },
            },
        }
