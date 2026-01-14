"""Video retrieval endpoints for the Retrieval Service."""

import time

from fastapi import APIRouter, HTTPException, Request, status
from query.preprocessor import QueryPreprocessor
from retrieval.video.models import VideoSearchMode
from retrieval.video.retriever import VideoRetriever

from api.dependencies import UserContextDep
from api.schemas.video_retrieve import (
    VideoMatchResponse,
    VideoResultResponse,
    VideoRetrieveRequest,
    VideoRetrieveResponse,
    VideoSearchMetricsResponse,
    VideoSearchModeAPI,
)

router = APIRouter()


def _map_search_mode(mode: VideoSearchModeAPI) -> VideoSearchMode:
    """Convert API search mode to internal enum."""
    return VideoSearchMode(mode.value)


def _convert_match(match) -> VideoMatchResponse:
    """Convert internal VideoMatch to API response model."""
    return VideoMatchResponse(
        chunk_id=match.chunk_id,
        chunk_index=match.chunk_index,
        start_time_ms=match.start_time_ms,
        end_time_ms=match.end_time_ms,
        start_seconds=match.start_seconds,
        end_seconds=match.end_seconds,
        duration_seconds=match.duration_seconds,
        fused_score=match.fused_score,
        semantic_score=match.semantic_score,
        keyword_score=match.keyword_score,
        rerank_score=match.rerank_score,
        fused_text_preview=match.fused_text_preview,
        transcript_text=match.transcript_text,
        scene_description=match.scene_description,
        keyframe_url=match.keyframe_url,
        clip_url=match.clip_url,
        source_modalities=match.source_modalities,
    )


def _convert_video_result(video) -> VideoResultResponse:
    """Convert internal VideoResult to API response model."""
    return VideoResultResponse(
        video_id=video.video_id,
        tenant_id=video.tenant_id,
        title=video.title,
        thumbnail_url=video.thumbnail_url,
        duration_ms=video.duration_ms,
        max_score=video.max_score,
        avg_score=video.avg_score,
        match_count=video.match_count,
        matches=[_convert_match(m) for m in video.matches],
    )


def _convert_metrics(metrics) -> VideoSearchMetricsResponse:
    """Convert internal VideoSearchMetrics to API response model."""
    return VideoSearchMetricsResponse(
        query_embedding_ms=metrics.query_embedding_ms,
        semantic_search_ms=metrics.semantic_search_ms,
        keyword_search_ms=metrics.keyword_search_ms,
        fusion_ms=metrics.fusion_ms,
        rerank_ms=metrics.rerank_ms,
        grouping_ms=metrics.grouping_ms,
        total_ms=metrics.total_ms,
        semantic_count=metrics.semantic_count,
        keyword_count=metrics.keyword_count,
        fused_count=metrics.fused_count,
        final_count=metrics.final_count,
    )


@router.post("/retrieve/video", response_model=VideoRetrieveResponse)
async def retrieve_video(
    request: Request,
    body: VideoRetrieveRequest,
    user: UserContextDep,
) -> VideoRetrieveResponse:
    """
    Retrieve relevant video segments for a query.

    Performs hybrid search (semantic + keyword) on video chunks with
    ACL filtering, RRF fusion, optional reranking, and timeline grouping.

    **Search Modes:**
    - `hybrid`: Combines semantic and keyword search (default)
    - `semantic`: Vector similarity search only
    - `keyword`: BM25 keyword search only

    **Response Format:**
    Results are grouped by video, with matches sorted by timestamp
    within each video. Each match includes time offsets for seeking
    to the relevant segment.

    **Reranking:**
    When enabled, top results are reranked using a cross-encoder
    model for improved relevance ordering.

    **Timeline URLs:**
    If configured, responses include URLs for keyframe images and
    video clips for direct playback of relevant segments.
    """
    start_time = time.time()

    # Get components from app state
    preprocessor: QueryPreprocessor = request.app.state.preprocessor

    # Check if video retriever is available
    video_retriever: VideoRetriever | None = getattr(
        request.app.state,
        "video_retriever",
        None,
    )

    if video_retriever is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video retrieval service not configured",
        )

    # Generate query embedding
    embed_start = time.time()
    processed = await preprocessor.process(body.query)
    embed_time = (time.time() - embed_start) * 1000

    # Execute video search
    try:
        internal_mode = _map_search_mode(body.mode)

        result = await video_retriever.search(
            query=body.query,
            query_embedding=processed.embedding,
            tenant_id=user.tenant_id,
            mode=internal_mode,
            top_k=body.top_k,
            video_id=body.video_id,
            allowed_groups=user.groups,
            semantic_weight=body.semantic_weight,
            keyword_weight=body.keyword_weight,
            enable_reranking=body.rerank,
        )

        # Update embedding time in metrics
        result.metrics.query_embedding_ms = embed_time
        result.metrics.total_ms = (time.time() - start_time) * 1000

        # Convert to API response format
        return VideoRetrieveResponse(
            query=result.query,
            mode=VideoSearchModeAPI(result.mode.value),
            videos=[_convert_video_result(v) for v in result.videos],
            total_videos=result.total_videos,
            total_matches=result.total_matches,
            metrics=_convert_metrics(result.metrics),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video search failed: {e!s}",
        ) from e


@router.get("/retrieve/video/{video_id}", response_model=VideoRetrieveResponse)
async def retrieve_video_by_id(
    request: Request,
    video_id: str,
    query: str,
    user: UserContextDep,
    top_k: int = 10,
    mode: VideoSearchModeAPI = VideoSearchModeAPI.HYBRID,
) -> VideoRetrieveResponse:
    """
    Search within a specific video.

    This is a convenience endpoint for searching within a single video
    by its ID. Uses the same search capabilities as the main endpoint
    but filters to one video.

    **Path Parameters:**
    - `video_id`: UUID of the video to search within

    **Query Parameters:**
    - `query`: Search query text
    - `top_k`: Maximum number of matches to return
    - `mode`: Search mode (hybrid, semantic, keyword)
    """
    from uuid import UUID

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid video_id format: {video_id}",
        ) from e

    # Reuse the main endpoint logic
    body = VideoRetrieveRequest(
        query=query,
        mode=mode,
        top_k=1,  # Single video
        video_id=video_uuid,
        max_matches_per_video=top_k,
    )

    return await retrieve_video(request, body, user)
