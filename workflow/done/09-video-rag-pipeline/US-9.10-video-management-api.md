# US-9.10: Video Management API

> **Story ID:** US-9.10
> **Epic:** Video RAG Pipeline
> **Priority:** High
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.1 (Video Upload), US-9.7 (Indexing)

## User Story

**As a** user
**I want** to list, view, and delete my videos
**So that** I can manage my video library

## Context

This story completes the video API by providing CRUD operations for video management. Users can list their uploaded videos, view details including processing status and chunk count, delete videos (cascading to all related data), and access video chunks and keyframes.

## Technical Requirements

### Video Management Routes

```python
# api/routes/video_management.py
from fastapi import APIRouter, HTTPException, Depends, Query
from uuid import UUID
from datetime import datetime
from typing import Optional

from ..schemas.video import (
    VideoResponse,
    VideoListResponse,
    VideoDetailResponse,
    VideoChunkResponse,
    VideoDeleteResponse,
    VideoUpdateRequest
)
from ..dependencies import get_current_user, get_video_service, get_storage_service

router = APIRouter(prefix="/videos", tags=["Video Management"])

# ============ List Videos ============

@router.get("", response_model=VideoListResponse)
async def list_videos(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None, description="Filter by processing status"),
    search: Optional[str] = Query(default=None, description="Search in title, description"),
    sort_by: str = Query(default="created_at", enum=["created_at", "title", "duration"]),
    sort_order: str = Query(default="desc", enum=["asc", "desc"]),
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service)
):
    """
    List videos with pagination and filtering.

    **Filters:**
    - `status`: Filter by processing status (processing, completed, failed)
    - `search`: Search in title and description

    **Sorting:**
    - `sort_by`: Field to sort by (created_at, title, duration)
    - `sort_order`: Sort direction (asc, desc)

    **Pagination:**
    - `page`: Page number (1-indexed)
    - `page_size`: Items per page (max 100)
    """
    tenant_id = UUID(current_user["tenant_id"])

    videos, total = await video_service.list_videos(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order
    )

    return VideoListResponse(
        videos=[_to_video_response(v) for v in videos],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size
    )

# ============ Get Video Details ============

@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    storage = Depends(get_storage_service)
):
    """
    Get video metadata and processing status.

    Returns full video details including:
    - File metadata (duration, resolution, codec)
    - Processing status and progress
    - Chunk count and indexing status
    - Thumbnail and stream URLs
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Get URLs
    thumbnail_url = None
    stream_url = None

    if video.thumbnail_path:
        thumbnail_url = await storage.get_presigned_url(video.thumbnail_path)

    if video.status == "completed":
        stream_url = await storage.get_stream_url(video.storage_path)

    # Get chunk count
    chunk_count = await video_service.get_chunk_count(video_id)

    return VideoDetailResponse(
        id=video.id,
        tenant_id=video.tenant_id,
        filename=video.filename,
        original_filename=video.original_filename,
        title=video.title,
        description=video.description,
        duration_seconds=float(video.duration_seconds) if video.duration_seconds else None,
        width=video.width,
        height=video.height,
        fps=float(video.fps) if video.fps else None,
        codec=video.codec,
        file_size_bytes=video.file_size_bytes,
        status=video.status,
        processing_stage=video.processing_stage,
        processing_progress=float(video.processing_progress) if video.processing_progress else 0,
        error_message=video.error_message,
        chunk_count=chunk_count,
        visibility=video.visibility,
        allowed_groups=video.allowed_groups or [],
        thumbnail_url=thumbnail_url,
        stream_url=stream_url,
        created_at=video.created_at,
        uploaded_at=video.uploaded_at,
        processed_at=video.processed_at
    )

# ============ Update Video ============

@router.patch("/{video_id}", response_model=VideoResponse)
async def update_video(
    video_id: UUID,
    update: VideoUpdateRequest,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service)
):
    """
    Update video metadata.

    Updatable fields:
    - title
    - description
    - visibility
    - allowed_groups
    - tags
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    updated = await video_service.update_video(
        video_id=video_id,
        title=update.title,
        description=update.description,
        visibility=update.visibility,
        allowed_groups=update.allowed_groups,
        tags=update.tags
    )

    return _to_video_response(updated)

# ============ Delete Video ============

@router.delete("/{video_id}", response_model=VideoDeleteResponse)
async def delete_video(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    storage = Depends(get_storage_service),
    qdrant_indexer = Depends(get_qdrant_indexer),
    opensearch_indexer = Depends(get_opensearch_indexer)
):
    """
    Delete video, chunks, keyframes, and cached clips.

    **Cascade Delete Order:**
    1. Delete vectors from Qdrant
    2. Delete entries from OpenSearch
    3. Delete chunk records from PostgreSQL
    4. Delete keyframe records from PostgreSQL
    5. Delete video record from PostgreSQL
    6. Delete files from MinIO (original, keyframes, clips)

    This operation cannot be undone.
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Delete from vector store
    vectors_deleted = await qdrant_indexer.delete_video_chunks(video_id)

    # Delete from keyword store
    keywords_deleted = await opensearch_indexer.delete_video_chunks(video_id)

    # Delete from database (cascades to chunks, keyframes)
    await video_service.delete_video(video_id, tenant_id)

    # Delete from storage
    storage_deleted = await storage.delete_video_files(tenant_id, video_id)

    return VideoDeleteResponse(
        video_id=video_id,
        deleted=True,
        vectors_deleted=vectors_deleted,
        keywords_deleted=keywords_deleted,
        storage_deleted=storage_deleted,
        message="Video and all associated data deleted"
    )

# ============ Get Video Chunks ============

@router.get("/{video_id}/chunks", response_model=list[VideoChunkResponse])
async def get_video_chunks(
    video_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    chunk_service = Depends(get_chunk_service)
):
    """
    List video chunks with timestamps.

    Returns all indexed chunks for the video, including:
    - Timestamps (start_ms, end_ms)
    - Fused text content
    - Source modalities present
    - Keyframe URL
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    chunks = await chunk_service.get_chunks(
        video_id=video_id,
        page=page,
        page_size=page_size
    )

    return [
        VideoChunkResponse(
            chunk_id=c.id,
            chunk_index=c.chunk_index,
            start_time_ms=c.start_time_ms,
            end_time_ms=c.end_time_ms,
            transcript_text=c.transcript_text,
            scene_description=c.scene_description,
            ocr_text=c.ocr_text,
            fused_text=c.fused_text[:500] if c.fused_text else None,  # Truncate for response
            source_modalities=c.source_modalities,
            keyframe_url=c.keyframe_path  # Will be converted to URL by client
        )
        for c in chunks
    ]

# ============ Get Keyframe ============

@router.get("/{video_id}/keyframes/{frame_index}")
async def get_keyframe(
    video_id: UUID,
    frame_index: int,
    thumbnail: bool = Query(default=False, description="Get thumbnail instead of full image"),
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    storage = Depends(get_storage_service)
):
    """
    Get keyframe image by index.

    Returns redirect to presigned URL for the keyframe image.

    **Parameters:**
    - `thumbnail`: If true, returns smaller thumbnail version
    """
    from fastapi.responses import RedirectResponse

    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build storage path
    prefix = "thumbs/" if thumbnail else ""
    keyframe_path = f"videos/{tenant_id}/keyframes/{video_id}/{prefix}{frame_index:05d}.jpg"

    try:
        url = await storage.get_presigned_url(keyframe_path)
        return RedirectResponse(url=url, status_code=302)
    except Exception:
        raise HTTPException(status_code=404, detail="Keyframe not found")

# ============ Reprocess Video ============

@router.post("/{video_id}/reprocess", response_model=VideoResponse)
async def reprocess_video(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service)
):
    """
    Reprocess a failed or completed video.

    Useful when:
    - Processing failed and you want to retry
    - Processing options changed
    - Want to regenerate with different settings

    Clears existing chunks and re-runs the full pipeline.
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video.status == "processing":
        raise HTTPException(status_code=400, detail="Video is already processing")

    # Queue reprocessing
    task = await video_service.reprocess_video(video_id)

    return _to_video_response(video)

# ============ Helper Functions ============

def _to_video_response(video) -> VideoResponse:
    """Convert database model to response."""
    return VideoResponse(
        id=video.id,
        tenant_id=video.tenant_id,
        filename=video.filename,
        title=video.title,
        duration_seconds=float(video.duration_seconds) if video.duration_seconds else None,
        width=video.width,
        height=video.height,
        status=video.status.value if hasattr(video.status, 'value') else video.status,
        processing_progress=float(video.processing_progress) if video.processing_progress else 0,
        visibility=video.visibility,
        created_at=video.created_at,
        processed_at=video.processed_at
    )
```

### Request/Response Schemas

```python
# api/schemas/video_management.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

class VideoUpdateRequest(BaseModel):
    """Request to update video metadata."""
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, max_length=5000)
    visibility: Optional[str] = Field(None, pattern="^(public|private|group)$")
    allowed_groups: Optional[list[str]] = None
    tags: Optional[list[str]] = None

class VideoResponse(BaseModel):
    """Basic video response."""
    id: UUID
    tenant_id: UUID
    filename: str
    title: Optional[str]
    duration_seconds: Optional[float]
    width: Optional[int]
    height: Optional[int]
    status: str
    processing_progress: float = 0
    visibility: str
    created_at: datetime
    processed_at: Optional[datetime]

class VideoDetailResponse(VideoResponse):
    """Detailed video response."""
    original_filename: str
    description: Optional[str]
    fps: Optional[float]
    codec: Optional[str]
    file_size_bytes: int
    processing_stage: Optional[str]
    error_message: Optional[str]
    chunk_count: int
    allowed_groups: list[str]
    thumbnail_url: Optional[str]
    stream_url: Optional[str]
    uploaded_at: Optional[datetime]

class VideoListResponse(BaseModel):
    """Paginated list of videos."""
    videos: list[VideoResponse]
    total: int
    page: int
    page_size: int
    pages: int

class VideoDeleteResponse(BaseModel):
    """Response after video deletion."""
    video_id: UUID
    deleted: bool
    vectors_deleted: int
    keywords_deleted: int
    storage_deleted: int
    message: str

class VideoChunkResponse(BaseModel):
    """Video chunk details."""
    chunk_id: UUID
    chunk_index: int
    start_time_ms: int
    end_time_ms: int
    transcript_text: Optional[str]
    scene_description: Optional[str]
    ocr_text: Optional[str]
    fused_text: Optional[str]
    source_modalities: list[str]
    keyframe_url: Optional[str]
```

### Video Service Extensions

```python
# services/video_service.py (additions)

class VideoService:
    # ... existing methods ...

    async def list_videos(
        self,
        tenant_id: UUID,
        page: int,
        page_size: int,
        status: str | None,
        search: str | None,
        sort_by: str,
        sort_order: str
    ) -> tuple[list[SourceVideo], int]:
        """List videos with filtering and sorting."""
        from sqlalchemy import select, func, desc, asc

        query = select(SourceVideo).where(SourceVideo.tenant_id == tenant_id)

        # Apply filters
        if status:
            query = query.where(SourceVideo.status == status)

        if search:
            search_term = f"%{search}%"
            query = query.where(
                SourceVideo.title.ilike(search_term) |
                SourceVideo.description.ilike(search_term) |
                SourceVideo.original_filename.ilike(search_term)
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.session.execute(count_query)).scalar()

        # Apply sorting
        sort_column = getattr(SourceVideo, sort_by, SourceVideo.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # Apply pagination
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(query)
        return list(result.scalars()), total

    async def update_video(
        self,
        video_id: UUID,
        title: str | None = None,
        description: str | None = None,
        visibility: str | None = None,
        allowed_groups: list[str] | None = None,
        tags: list[str] | None = None
    ) -> SourceVideo:
        """Update video metadata."""
        from sqlalchemy import update

        values = {"updated_at": datetime.utcnow()}

        if title is not None:
            values["title"] = title
        if description is not None:
            values["description"] = description
        if visibility is not None:
            values["visibility"] = visibility
        if allowed_groups is not None:
            values["allowed_groups"] = allowed_groups
        if tags is not None:
            values["tags"] = tags

        await self.session.execute(
            update(SourceVideo)
            .where(SourceVideo.id == video_id)
            .values(**values)
        )
        await self.session.commit()

        return await self.get_video_by_id(video_id)

    async def get_chunk_count(self, video_id: UUID) -> int:
        """Get number of chunks for a video."""
        from sqlalchemy import select, func

        result = await self.session.execute(
            select(func.count())
            .select_from(VideoChunkModel)
            .where(VideoChunkModel.video_id == video_id)
        )
        return result.scalar() or 0

    async def reprocess_video(self, video_id: UUID):
        """Clear existing chunks and requeue processing."""
        from tasks.video_ingest import process_video
        from sqlalchemy import delete

        # Clear existing chunks
        await self.session.execute(
            delete(VideoChunkModel).where(VideoChunkModel.video_id == video_id)
        )

        # Clear keyframes
        await self.session.execute(
            delete(VideoKeyframe).where(VideoKeyframe.video_id == video_id)
        )

        # Reset status
        await self.update_status(video_id, status="processing", processing_progress=0)

        await self.session.commit()

        # Get video for processing options
        video = await self.get_video_by_id(video_id)

        # Queue processing
        task = process_video.delay(
            str(video_id),
            str(video.tenant_id),
            video.processing_options or {}
        )

        return task
```

### Storage Service Extensions

```python
# services/storage_service.py (additions)

class StorageService:
    async def delete_video_files(
        self,
        tenant_id: UUID,
        video_id: UUID
    ) -> int:
        """Delete all files associated with a video."""
        prefixes = [
            f"videos/{tenant_id}/originals/{video_id}/",
            f"videos/{tenant_id}/keyframes/{video_id}/",
            f"videos/{tenant_id}/thumbnails/{video_id}/",
            f"videos/{tenant_id}/clips/{video_id}/",
        ]

        deleted = 0
        for prefix in prefixes:
            count = await self.minio.delete_prefix(prefix)
            deleted += count

        return deleted
```

## API Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/videos` | List videos with pagination |
| GET | `/videos/{id}` | Get video metadata |
| PATCH | `/videos/{id}` | Update video metadata |
| DELETE | `/videos/{id}` | Delete video and all data |
| GET | `/videos/{id}/chunks` | List video chunks |
| GET | `/videos/{id}/keyframes/{idx}` | Get keyframe image |
| POST | `/videos/{id}/reprocess` | Reprocess video |

## Acceptance Criteria

- [ ] `GET /api/v1/videos` - list videos with pagination and filtering
- [ ] `GET /api/v1/videos/{id}` - get video metadata and processing status
- [ ] `DELETE /api/v1/videos/{id}` - delete video, chunks, keyframes, and cached clips
- [ ] `GET /api/v1/videos/{id}/chunks` - list video chunks with timestamps
- [ ] `GET /api/v1/videos/{id}/keyframes/{idx}` - get keyframe image
- [ ] Enforce tenant isolation and ACL

## Testing Requirements

```python
class TestVideoManagement:
    def test_list_videos_pagination(self, client, auth_headers, multiple_videos):
        response = client.get(
            "/api/v1/videos?page=1&page_size=10",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["videos"]) <= 10
        assert "total" in data
        assert "pages" in data

    def test_list_videos_search(self, client, auth_headers, video_with_title):
        response = client.get(
            f"/api/v1/videos?search={video_with_title.title[:5]}",
            headers=auth_headers
        )

        assert response.status_code == 200
        assert len(response.json()["videos"]) > 0

    def test_list_videos_filter_status(self, client, auth_headers, completed_video, processing_video):
        response = client.get(
            "/api/v1/videos?status=completed",
            headers=auth_headers
        )

        data = response.json()
        for video in data["videos"]:
            assert video["status"] == "completed"

    def test_get_video_details(self, client, auth_headers, completed_video):
        response = client.get(
            f"/api/v1/videos/{completed_video.id}",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(completed_video.id)
        assert "duration_seconds" in data
        assert "chunk_count" in data

    def test_get_video_not_found(self, client, auth_headers):
        response = client.get(
            f"/api/v1/videos/{uuid4()}",
            headers=auth_headers
        )

        assert response.status_code == 404

    def test_update_video(self, client, auth_headers, sample_video):
        response = client.patch(
            f"/api/v1/videos/{sample_video.id}",
            json={"title": "Updated Title", "description": "New description"},
            headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"

    def test_delete_video_cascade(self, client, auth_headers, video_with_chunks):
        video_id = video_with_chunks.id

        response = client.delete(
            f"/api/v1/videos/{video_id}",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["vectors_deleted"] > 0
        assert data["storage_deleted"] > 0

        # Verify deleted
        get_response = client.get(
            f"/api/v1/videos/{video_id}",
            headers=auth_headers
        )
        assert get_response.status_code == 404

    def test_get_chunks(self, client, auth_headers, video_with_chunks):
        response = client.get(
            f"/api/v1/videos/{video_with_chunks.id}/chunks",
            headers=auth_headers
        )

        assert response.status_code == 200
        chunks = response.json()
        assert len(chunks) > 0
        assert "start_time_ms" in chunks[0]
        assert "fused_text" in chunks[0]

    def test_get_keyframe(self, client, auth_headers, video_with_keyframes):
        response = client.get(
            f"/api/v1/videos/{video_with_keyframes.id}/keyframes/0",
            headers=auth_headers,
            follow_redirects=False
        )

        assert response.status_code == 302
        assert "Location" in response.headers

    def test_tenant_isolation(self, client, other_tenant_headers, sample_video):
        """Verify users cannot access other tenants' videos."""
        response = client.get(
            f"/api/v1/videos/{sample_video.id}",
            headers=other_tenant_headers
        )

        assert response.status_code == 404

    def test_reprocess_video(self, client, auth_headers, failed_video):
        response = client.post(
            f"/api/v1/videos/{failed_video.id}/reprocess",
            headers=auth_headers
        )

        assert response.status_code == 200

from uuid import uuid4  # Import at module level
```

## Definition of Done

- [ ] List endpoint with pagination, filtering, sorting
- [ ] Detail endpoint with full metadata
- [ ] Update endpoint for editable fields
- [ ] Delete endpoint with cascade to all stores
- [ ] Chunks endpoint with timestamps
- [ ] Keyframe endpoint with presigned URLs
- [ ] Reprocess endpoint for failed videos
- [ ] Tenant isolation enforced on all endpoints
- [ ] ACL checked for group-visibility videos
- [ ] >90% test coverage
