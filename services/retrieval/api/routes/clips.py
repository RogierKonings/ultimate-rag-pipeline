"""Video clip endpoints for the Retrieval Service."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from retrieval.video.clip_cache import ClipCacheService
from retrieval.video.clip_generator import ClipGenerator

from api.dependencies import UserContextDep

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/videos/{video_id}/clip")
async def get_video_clip(
    request: Request,
    video_id: str,
    start: int = Query(..., ge=0, description="Start time in milliseconds"),
    end: int = Query(..., ge=0, description="End time in milliseconds"),
    user: UserContextDep = None,
) -> RedirectResponse:
    """
    Get a video clip for a specific time range.

    Returns a 302 redirect to a presigned URL for the clip.
    Clips are cached for 24 hours after generation.

    **Query Parameters:**
    - `start`: Start time in milliseconds
    - `end`: End time in milliseconds

    **Response:**
    - 302: Redirect to presigned clip URL
    - 404: Video not found or inaccessible
    - 400: Invalid time range
    """
    # Validate video_id format
    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid video_id format: {video_id}",
        ) from e

    # Validate time range
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be greater than start time",
        )

    # Get services from app state
    clip_cache: ClipCacheService | None = getattr(
        request.app.state,
        "clip_cache",
        None,
    )
    clip_generator: ClipGenerator | None = getattr(
        request.app.state,
        "clip_generator",
        None,
    )

    if clip_cache is None or clip_generator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clip service not configured",
        )

    tenant_id = user.tenant_id

    # Check cache first
    cached = await clip_cache.get_cached_clip(
        tenant_id=tenant_id,
        video_id=video_uuid,
        start_ms=start,
        end_ms=end,
    )

    if cached.exists and cached.presigned_url:
        logger.info(
            "Serving cached clip: video_id=%s, %d-%dms",
            video_id,
            start,
            end,
        )
        return RedirectResponse(
            url=cached.presigned_url,
            status_code=status.HTTP_302_FOUND,
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Clip-Cache": "HIT",
            },
        )

    # TODO: Implement clip generation workflow:
    # 1. Get source video path from database
    # 2. Download from MinIO to temp location
    # 3. Generate clip using ClipGenerator
    # 4. Store in cache and return presigned URL
    #
    # Expected source path pattern: videos/{tenant_id}/{video_uuid}/original.mp4
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Clip generation requires source video download (not yet implemented)",
    )


@router.get("/videos/{video_id}/stream")
async def get_video_stream(
    request: Request,
    video_id: str,
    user: UserContextDep = None,
) -> RedirectResponse:
    """
    Get a streaming URL for the full video.

    Returns a 302 redirect to a presigned URL for the original video.
    The presigned URL supports range requests for seeking.

    **Response:**
    - 302: Redirect to presigned video URL
    - 404: Video not found or inaccessible
    """
    # Validate video_id format
    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid video_id format: {video_id}",
        ) from e

    # Get clip cache service for presigned URL generation
    clip_cache: ClipCacheService | None = getattr(
        request.app.state,
        "clip_cache",
        None,
    )

    if clip_cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stream service not configured",
        )

    tenant_id = user.tenant_id

    # Construct video path
    video_path = f"videos/{tenant_id}/{video_uuid}/original.mp4"

    # Get presigned URL
    stream_url = await clip_cache.get_video_stream_url(
        tenant_id=tenant_id,
        video_id=video_uuid,
        video_path=video_path,
    )

    if stream_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found or inaccessible",
        )

    return RedirectResponse(
        url=stream_url,
        status_code=status.HTTP_302_FOUND,
        headers={
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/clips/stats")
async def get_clip_cache_stats(
    request: Request,
    user: UserContextDep = None,
) -> dict:
    """
    Get clip cache statistics.

    Returns information about cached clips including count and size.
    """
    clip_cache: ClipCacheService | None = getattr(
        request.app.state,
        "clip_cache",
        None,
    )

    if clip_cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clip cache not configured",
        )

    return clip_cache.get_cache_stats()
