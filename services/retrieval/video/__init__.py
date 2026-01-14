"""Video retrieval module.

This module provides video-specific search and retrieval functionality
including hybrid search, RRF fusion, timeline-based result grouping,
and clip generation/caching.
"""

from retrieval.video.clip_cache import (
    CachedClip,
    ClipCacheConfig,
    ClipCacheService,
)
from retrieval.video.clip_generator import (
    ClipConfig,
    ClipGenerator,
    ClipResult,
)
from retrieval.video.exceptions import VideoRetrievalError
from retrieval.video.models import (
    VideoMatch,
    VideoResult,
    VideoSearchMetrics,
    VideoSearchMode,
    VideoTimelineResponse,
)
from retrieval.video.retriever import VideoRetriever, VideoRetrieverConfig

__all__ = [
    # Retriever
    "VideoRetriever",
    "VideoRetrieverConfig",
    # Models
    "VideoMatch",
    "VideoResult",
    "VideoTimelineResponse",
    "VideoSearchMetrics",
    "VideoSearchMode",
    # Clip Generation
    "ClipGenerator",
    "ClipConfig",
    "ClipResult",
    # Clip Caching
    "ClipCacheService",
    "ClipCacheConfig",
    "CachedClip",
    # Exceptions
    "VideoRetrievalError",
]
