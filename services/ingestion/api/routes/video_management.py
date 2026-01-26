"""Video management API routes.

CRUD operations for video library management including list, get,
update, delete, and chunk/keyframe access.
"""

import json
import logging
import math
from datetime import timedelta
from uuid import UUID

from api.dependencies import get_asyncpg_pool, get_current_user
from api.schemas.video import VideoRegisterRequest, VideoStatus, VideoUploadResponse
from api.schemas.video_management import (
    DeletionCounts,
    PaginationMeta,
    ReprocessResponse,
    VideoBatchDeleteRequest,
    VideoBatchDeleteResponse,
    VideoBatchDeleteResult,
    VideoChunkResponse,
    VideoChunksResponse,
    VideoDeleteResponse,
    VideoDetailResponse,
    VideoListResponse,
    VideoResponse,
    VideoUpdateRequest,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from minio import Minio

from config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


# MinIO client singleton
_minio_client: Minio | None = None


def get_minio_client() -> Minio | None:
    """Get MinIO client singleton."""
    global _minio_client
    if _minio_client is None:
        settings = get_settings()
        if settings.minio_url:
            # Parse endpoint from URL (e.g., http://localhost:9000 -> localhost:9000)
            minio_url = settings.minio_url
            secure = minio_url.startswith("https://")
            endpoint = minio_url.replace("https://", "").replace("http://", "")
            _minio_client = Minio(
                endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=secure,
            )
            logger.info("Created MinIO client for endpoint: %s", endpoint)
    return _minio_client


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=202,
    summary="Register pre-uploaded video",
    description="Register a video that was already uploaded to storage and start processing.",
)
async def register_video(
    body: VideoRegisterRequest,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoUploadResponse:
    """
    Register a video that was already uploaded directly to MinIO/S3.

    Use this endpoint when the client uploads the video file directly to
    object storage (e.g., via presigned URL or direct S3 API) and then
    notifies the backend to start processing.

    The storage_path should be the full key/path where the video was uploaded.

    **Workflow:**
    1. Client uploads video directly to MinIO
    2. Client calls this endpoint with the storage path
    3. Backend validates the file exists and starts processing
    4. Use GET /{video_id}/status to track progress
    """
    from uuid import uuid4

    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    minio_client = get_minio_client()

    # Verify file exists in MinIO
    if minio_client:
        try:
            minio_client.stat_object("rag-documents", body.storage_path)
        except Exception as e:
            logger.warning("File not found in storage: %s - %s", body.storage_path, e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Video file not found at storage path: {body.storage_path}",
            ) from e

    # Generate IDs
    video_id = uuid4()
    job_id = uuid4()

    # Determine title
    title = body.title
    if not title:
        # Remove extension from filename
        title = body.filename.rsplit(".", 1)[0] if "." in body.filename else body.filename

    # Create database record
    insert_query = """
        INSERT INTO source_videos (
            id, tenant_id, filename, title, description,
            storage_path, status, processing_stage, processing_progress,
            visibility, allowed_groups, tags,
            created_at, uploaded_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11, $12,
            NOW(), NOW()
        )
    """

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                insert_query,
                video_id,
                UUID(tenant_id),
                body.filename,
                title,
                body.description,
                body.storage_path,
                VideoStatus.PROCESSING.value,
                "uploaded",
                0,
                body.visibility.value if hasattr(body.visibility, "value") else body.visibility,
                json.dumps([str(g) for g in body.allowed_groups]),
                json.dumps(body.tags),
            )
    except Exception as e:
        logger.exception("Failed to create video record: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create video record",
        ) from e

    # Queue processing task
    try:
        from tasks.video_ingest import process_video

        process_video.delay(
            video_id=str(video_id),
            tenant_id=tenant_id,
            processing_options=body.processing_options.model_dump() if body.processing_options else {},
        )
        logger.info(
            "Queued video processing: video_id=%s, storage_path=%s",
            video_id,
            body.storage_path,
        )
    except Exception as e:
        logger.warning("Failed to queue video task (will retry later): %s", e)
        # Don't fail - the video record is created and can be reprocessed

    return VideoUploadResponse(
        video_id=video_id,
        job_id=job_id,
        filename=body.filename,
        status=VideoStatus.PROCESSING,
        storage_path=body.storage_path,
        message="Video registered successfully. Processing will begin shortly.",
    )


@router.get("", response_model=VideoListResponse)
async def list_videos(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: VideoStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by status",
    ),
    search: str | None = Query(default=None, description="Search in title/description"),
    sort_by: str = Query(default="created_at", description="Sort field"),
    sort_order: str = Query(default="desc", description="Sort order: asc, desc"),
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoListResponse:
    """
    List videos with pagination, filtering, and sorting.

    **Filters:**
    - `status`: Filter by processing status
    - `search`: Full-text search in title and description

    **Sorting:**
    - `sort_by`: Field to sort by (created_at, title, duration)
    - `sort_order`: asc or desc
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    # Build query
    base_query = """
        SELECT
            id as video_id, tenant_id, filename, title, description,
            (duration_seconds * 1000)::bigint as duration_ms,
            width, height, fps, codec, file_size_bytes,
            status, processing_stage, processing_progress, error_message,
            detected_language, keyframe_count, chunk_count,
            visibility, allowed_groups, tags,
            thumbnail_path, storage_path,
            created_at, uploaded_at, processed_at
        FROM source_videos
        WHERE tenant_id = $1
    """
    params = [UUID(tenant_id)]
    param_count = 1

    # Add status filter
    if status_filter:
        param_count += 1
        base_query += f" AND status = ${param_count}"
        params.append(status_filter.value)

    # Add search filter
    if search:
        param_count += 1
        base_query += f"""
            AND (
                title ILIKE ${param_count}
                OR description ILIKE ${param_count}
            )
        """
        params.append(f"%{search}%")

    # Get total count
    count_query = f"SELECT COUNT(*) FROM ({base_query}) sub"

    # Add sorting
    valid_sort_fields = {"created_at", "title", "duration_seconds", "status"}
    if sort_by not in valid_sort_fields:
        sort_by = "created_at"
    sort_direction = "DESC" if sort_order.lower() == "desc" else "ASC"
    base_query += f" ORDER BY {sort_by} {sort_direction} NULLS LAST"

    # Add pagination
    offset = (page - 1) * page_size
    base_query += f" LIMIT {page_size} OFFSET {offset}"

    async with pool.acquire() as conn:
        # Get total count
        total = await conn.fetchval(count_query, *params)

        # Get paginated results
        rows = await conn.fetch(base_query, *params)

    # Convert to response models
    videos = []
    minio_client = get_minio_client()

    for row in rows:
        video = _row_to_detail_response(row, minio_client)
        videos.append(video)

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return VideoListResponse(
        videos=videos,
        pagination=PaginationMeta(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        ),
    )


@router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: str,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoDetailResponse:
    """
    Get detailed information about a video.

    Includes full metadata, processing status, chunk count, and presigned URLs.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    query = """
        SELECT
            id as video_id, tenant_id, filename, title, description,
            (duration_seconds * 1000)::bigint as duration_ms,
            width, height, fps, codec, file_size_bytes,
            status, processing_stage, processing_progress, error_message,
            detected_language, keyframe_count, chunk_count,
            visibility, allowed_groups, tags,
            thumbnail_path, storage_path,
            created_at, uploaded_at, processed_at
        FROM source_videos
        WHERE id = $1 AND tenant_id = $2
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, video_uuid, UUID(tenant_id))

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    minio_client = get_minio_client()
    return _row_to_detail_response(row, minio_client)


@router.patch("/{video_id}", response_model=VideoResponse)
async def update_video(
    video_id: str,
    body: VideoUpdateRequest,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoResponse:
    """
    Update video metadata.

    **Updatable fields:**
    - title
    - description
    - visibility
    - allowed_groups
    - tags
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    # Build update query dynamically
    updates = []
    params = []
    param_count = 0

    if body.title is not None:
        param_count += 1
        updates.append(f"title = ${param_count}")
        params.append(body.title)

    if body.description is not None:
        param_count += 1
        updates.append(f"description = ${param_count}")
        params.append(body.description)

    if body.visibility is not None:
        param_count += 1
        updates.append(f"visibility = ${param_count}")
        params.append(body.visibility.value)

    if body.allowed_groups is not None:
        param_count += 1
        updates.append(f"allowed_groups = ${param_count}")
        params.append([str(g) for g in body.allowed_groups])

    if body.tags is not None:
        param_count += 1
        updates.append(f"tags = ${param_count}")
        params.append(body.tags)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    # Add WHERE clause params
    param_count += 1
    params.append(video_uuid)
    param_count += 1
    params.append(UUID(tenant_id))

    query = f"""
        UPDATE source_videos
        SET {", ".join(updates)}
        WHERE id = ${param_count - 1} AND tenant_id = ${param_count}
        RETURNING
            id as video_id, tenant_id, title, description,
            status, visibility, allowed_groups, tags
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    return VideoResponse(
        video_id=row["video_id"],
        tenant_id=row["tenant_id"],
        title=row["title"],
        description=row["description"],
        status=VideoStatus(row["status"]),
        visibility=row["visibility"],
        allowed_groups=[
            UUID(g) for g in (
                json.loads(row["allowed_groups"])
                if isinstance(row.get("allowed_groups"), str)
                else (row.get("allowed_groups") or [])
            )
        ],
        tags=(
            json.loads(row["tags"])
            if isinstance(row.get("tags"), str)
            else (row.get("tags") or [])
        ),
        updated_at=None,
    )


@router.delete("/{video_id}", response_model=VideoDeleteResponse)
async def delete_video(
    video_id: str,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoDeleteResponse:
    """
    Delete a video and all associated data.

    **Cascade deletion order:**
    1. Vectors from Qdrant (video_chunks collection)
    2. Documents from OpenSearch (video_chunks index)
    3. Chunk records from PostgreSQL (CASCADE)
    4. Video record from PostgreSQL
    5. Files from MinIO (original, keyframes, clips)
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    counts = DeletionCounts()

    # Check video exists
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM source_videos WHERE id = $1 AND tenant_id = $2",
            video_uuid,
            UUID(tenant_id),
        )

    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    # 1. Delete from Qdrant
    try:
        import os

        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        qdrant.delete(
            collection_name="video_chunks",
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="video_id",
                        match=MatchValue(value=str(video_uuid)),
                    ),
                ],
            ),
        )
        # Estimate deleted count
        counts.qdrant_vectors = 1  # Placeholder, actual count requires pre-query
        logger.info("Deleted vectors from Qdrant for video_id=%s", video_id)
    except Exception as e:
        logger.warning("Failed to delete from Qdrant: %s", e)

    # 2. Delete from OpenSearch
    try:
        import os

        from opensearchpy import OpenSearch

        opensearch = OpenSearch(
            hosts=[os.getenv("OPENSEARCH_URL", "http://localhost:9200")],
        )
        response = opensearch.delete_by_query(
            index="video_chunks",
            body={"query": {"term": {"video_id": str(video_uuid)}}},
        )
        counts.opensearch_documents = response.get("deleted", 0)
        logger.info(
            "Deleted %d documents from OpenSearch for video_id=%s",
            counts.opensearch_documents,
            video_id,
        )
    except Exception as e:
        logger.warning("Failed to delete from OpenSearch: %s", e)

    # 3 & 4. Delete from PostgreSQL (chunks cascade from video)
    async with pool.acquire() as conn:
        # Get chunk count before deletion
        chunk_count = await conn.fetchval(
            "SELECT COUNT(*) FROM video_chunks WHERE video_id = $1",
            video_uuid,
        )
        counts.postgres_chunks = chunk_count or 0

        # Delete video (cascades to chunks)
        await conn.execute(
            "DELETE FROM source_videos WHERE id = $1 AND tenant_id = $2",
            video_uuid,
            UUID(tenant_id),
        )

    logger.info(
        "Deleted %d chunks from PostgreSQL for video_id=%s",
        counts.postgres_chunks,
        video_id,
    )

    # 5. Delete from MinIO
    minio_client = get_minio_client()
    if minio_client:
        try:
            prefix = f"videos/{tenant_id}/{video_uuid}/"
            bucket = "rag-pipeline"

            objects = minio_client.list_objects(bucket, prefix=prefix, recursive=True)
            for obj in objects:
                minio_client.remove_object(bucket, obj.object_name)
                counts.minio_files += 1

            logger.info(
                "Deleted %d files from MinIO for video_id=%s",
                counts.minio_files,
                video_id,
            )
        except Exception as e:
            logger.warning("Failed to delete from MinIO: %s", e)

    return VideoDeleteResponse(
        video_id=video_uuid,
        success=True,
        message="Video and all associated data deleted",
        deletion_counts=counts,
    )


@router.post(
    "/batch-delete",
    response_model=VideoBatchDeleteResponse,
    summary="Batch delete videos",
    description="Delete multiple videos at once.",
)
async def batch_delete_videos(
    request: VideoBatchDeleteRequest,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoBatchDeleteResponse:
    """
    Delete multiple videos in a single request.

    Processes each video independently - failures for one video
    don't prevent deletion of others.

    **Cascade deletion order for each video:**
    1. Vectors from Qdrant (video_chunks collection)
    2. Documents from OpenSearch (video_chunks index)
    3. Chunk records from PostgreSQL (CASCADE)
    4. Video record from PostgreSQL
    5. Files from MinIO (original, keyframes, clips)

    Returns detailed results for each video.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    results = []
    deleted_count = 0
    failed_count = 0

    minio_client = get_minio_client()

    for video_id in request.video_ids:
        video_uuid = video_id
        counts = DeletionCounts()

        # Check video exists
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM source_videos WHERE id = $1 AND tenant_id = $2",
                video_uuid,
                UUID(tenant_id),
            )

        if not exists:
            results.append(
                VideoBatchDeleteResult(
                    video_id=video_uuid,
                    deleted=False,
                    message="Video not found",
                    deletion_counts=counts,
                )
            )
            failed_count += 1
            continue

        try:
            # 1. Delete from Qdrant
            try:
                import os

                from qdrant_client import QdrantClient
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
                qdrant.delete(
                    collection_name="video_chunks",
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="video_id",
                                match=MatchValue(value=str(video_uuid)),
                            ),
                        ],
                    ),
                )
                counts.qdrant_vectors = 1
                logger.info("Deleted vectors from Qdrant for video_id=%s", video_uuid)
            except Exception as e:
                logger.warning("Failed to delete from Qdrant: %s", e)

            # 2. Delete from OpenSearch
            try:
                import os

                from opensearchpy import OpenSearch

                opensearch = OpenSearch(
                    hosts=[os.getenv("OPENSEARCH_URL", "http://localhost:9200")],
                )
                response = opensearch.delete_by_query(
                    index="video_chunks",
                    body={"query": {"term": {"video_id": str(video_uuid)}}},
                )
                counts.opensearch_documents = response.get("deleted", 0)
                logger.info(
                    "Deleted %d documents from OpenSearch for video_id=%s",
                    counts.opensearch_documents,
                    video_uuid,
                )
            except Exception as e:
                logger.warning("Failed to delete from OpenSearch: %s", e)

            # 3 & 4. Delete from PostgreSQL (chunks cascade from video)
            async with pool.acquire() as conn:
                chunk_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM video_chunks WHERE video_id = $1",
                    video_uuid,
                )
                counts.postgres_chunks = chunk_count or 0

                await conn.execute(
                    "DELETE FROM source_videos WHERE id = $1 AND tenant_id = $2",
                    video_uuid,
                    UUID(tenant_id),
                )

            logger.info(
                "Deleted %d chunks from PostgreSQL for video_id=%s",
                counts.postgres_chunks,
                video_uuid,
            )

            # 5. Delete from MinIO
            if minio_client:
                try:
                    prefix = f"videos/{tenant_id}/{video_uuid}/"
                    bucket = "rag-pipeline"

                    objects = minio_client.list_objects(bucket, prefix=prefix, recursive=True)
                    for obj in objects:
                        minio_client.remove_object(bucket, obj.object_name)
                        counts.minio_files += 1

                    logger.info(
                        "Deleted %d files from MinIO for video_id=%s",
                        counts.minio_files,
                        video_uuid,
                    )
                except Exception as e:
                    logger.warning("Failed to delete from MinIO: %s", e)

            results.append(
                VideoBatchDeleteResult(
                    video_id=video_uuid,
                    deleted=True,
                    message="Video and all associated data deleted",
                    deletion_counts=counts,
                )
            )
            deleted_count += 1

        except Exception as e:
            logger.exception("Failed to delete video %s: %s", video_uuid, e)
            results.append(
                VideoBatchDeleteResult(
                    video_id=video_uuid,
                    deleted=False,
                    message=f"Deletion failed: {e!s}",
                    deletion_counts=counts,
                )
            )
            failed_count += 1

    return VideoBatchDeleteResponse(
        deleted_count=deleted_count,
        failed_count=failed_count,
        results=results,
    )


@router.get("/{video_id}/chunks", response_model=VideoChunksResponse)
async def get_video_chunks(
    video_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> VideoChunksResponse:
    """
    Get video chunks with pagination.

    Returns time-segmented chunks with content previews.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    # Verify video access
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM source_videos WHERE id = $1 AND tenant_id = $2",
            video_uuid,
            UUID(tenant_id),
        )

    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    # Get chunks
    offset = (page - 1) * page_size

    count_query = "SELECT COUNT(*) FROM video_chunks WHERE video_id = $1"
    chunks_query = """
        SELECT
            id as chunk_id, chunk_index, start_time_ms, end_time_ms,
            transcript_text, scene_description, ocr_text, fused_text,
            source_modalities, keyframe_path, embedding_id
        FROM video_chunks
        WHERE video_id = $1
        ORDER BY chunk_index
        LIMIT $2 OFFSET $3
    """

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_query, video_uuid)
        rows = await conn.fetch(chunks_query, video_uuid, page_size, offset)

    minio_client = get_minio_client()
    chunks = []

    for row in rows:
        start_ms = row["start_time_ms"]
        end_ms = row["end_time_ms"]

        keyframe_url = None
        if row["keyframe_path"] and minio_client:
            try:
                keyframe_url = minio_client.presigned_get_object(
                    "rag-pipeline",
                    row["keyframe_path"],
                    expires=timedelta(hours=4),
                )
            except Exception as e:
                logger.debug("Failed to generate presigned URL: %s", e)

        fused_preview = (row["fused_text"] or "")[:500]

        chunks.append(
            VideoChunkResponse(
                chunk_id=row["chunk_id"],
                chunk_index=row["chunk_index"],
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                start_seconds=start_ms / 1000.0,
                end_seconds=end_ms / 1000.0,
                duration_seconds=(end_ms - start_ms) / 1000.0,
                fused_text_preview=fused_preview,
                transcript_text=row["transcript_text"],
                scene_description=row["scene_description"],
                ocr_text=row["ocr_text"],
                source_modalities=row["source_modalities"] or [],
                keyframe_url=keyframe_url,
                embedding_id=row["embedding_id"],
            )
        )

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return VideoChunksResponse(
        video_id=video_uuid,
        chunks=chunks,
        total_chunks=total,
        pagination=PaginationMeta(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        ),
    )


@router.get("/{video_id}/keyframes/{frame_index}")
async def get_keyframe(
    video_id: str,
    frame_index: int,
    thumbnail: bool = Query(default=False, description="Return thumbnail version"),
    current_user: dict = Depends(get_current_user),
) -> RedirectResponse:
    """
    Get a specific keyframe image.

    Returns a 302 redirect to presigned URL for the keyframe.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    minio_client = get_minio_client()
    if not minio_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage not configured",
        )

    # Construct keyframe path
    suffix = "_thumb.jpg" if thumbnail else ".jpg"
    keyframe_path = f"videos/{tenant_id}/{video_uuid}/keyframes/frame_{frame_index:06d}{suffix}"

    try:
        # Verify exists
        minio_client.stat_object("rag-pipeline", keyframe_path)

        # Generate presigned URL
        presigned_url = minio_client.presigned_get_object(
            "rag-pipeline",
            keyframe_path,
            expires=timedelta(hours=4),
        )

        return RedirectResponse(
            url=presigned_url,
            status_code=status.HTTP_302_FOUND,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Keyframe not found: frame_index={frame_index}",
        ) from e


@router.post("/{video_id}/reprocess", response_model=ReprocessResponse)
async def reprocess_video(
    video_id: str,
    current_user: dict = Depends(get_current_user),
    pool=Depends(get_asyncpg_pool),
) -> ReprocessResponse:
    """
    Reprocess a video from scratch.

    Clears existing chunks and keyframes, resets status, and queues
    a new processing job.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    try:
        video_uuid = UUID(video_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video_id format",
        ) from e

    # Verify video exists and get current status
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM source_videos WHERE id = $1 AND tenant_id = $2",
            video_uuid,
            UUID(tenant_id),
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    # Don't allow reprocessing while already processing
    if row["status"] == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video is already being processed",
        )

    # Clear existing chunks (will cascade delete from search indexes)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM video_chunks WHERE video_id = $1",
            video_uuid,
        )

        # Reset video status
        await conn.execute(
            """
            UPDATE source_videos
            SET status = 'processing',
                processing_stage = 'uploaded',
                processing_progress = 0,
                error_message = NULL,
                keyframe_count = 0,
                chunk_count = 0
            WHERE id = $1
            """,
            video_uuid,
        )

    # Queue new processing job
    from uuid import uuid4

    job_id = uuid4()

    try:
        from tasks.video_ingest import process_video

        process_video.delay(
            video_id=str(video_uuid),
            tenant_id=tenant_id,
        )
    except Exception as e:
        logger.error("Failed to queue reprocess job: %s", e)
        # Update status to failed if we can't queue
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE source_videos
                SET status = 'failed', error_message = $2
                WHERE id = $1
                """,
                video_uuid,
                f"Failed to queue job: {e}",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue reprocessing job",
        ) from e

    return ReprocessResponse(
        video_id=video_uuid,
        job_id=job_id,
        status=VideoStatus.PROCESSING,
        message="Video reprocessing started",
    )


def _row_to_detail_response(row, minio_client) -> VideoDetailResponse:
    """Convert database row to VideoDetailResponse."""
    thumbnail_url = None
    stream_url = None

    if minio_client:
        try:
            if row.get("thumbnail_path"):
                thumbnail_url = minio_client.presigned_get_object(
                    "rag-pipeline",
                    row["thumbnail_path"],
                    expires=timedelta(hours=4),
                )
            if row.get("storage_path"):
                stream_url = minio_client.presigned_get_object(
                    "rag-pipeline",
                    row["storage_path"],
                    expires=timedelta(hours=4),
                )
        except Exception as e:
            logger.debug("Failed to generate presigned URLs: %s", e)

    duration_ms = row.get("duration_ms")
    duration_seconds = duration_ms / 1000.0 if duration_ms else None

    return VideoDetailResponse(
        video_id=row["video_id"],
        tenant_id=row["tenant_id"],
        filename=row["filename"],
        title=row.get("title"),
        description=row.get("description"),
        duration_ms=duration_ms,
        duration_seconds=duration_seconds,
        width=row.get("width"),
        height=row.get("height"),
        fps=row.get("fps"),
        codec=row.get("codec"),
        file_size_bytes=row.get("file_size_bytes"),
        status=VideoStatus(row["status"]),
        processing_stage=row.get("processing_stage"),
        processing_progress=row.get("processing_progress", 0),
        error_message=row.get("error_message"),
        detected_language=row.get("detected_language"),
        keyframe_count=row.get("keyframe_count", 0),
        chunk_count=row.get("chunk_count", 0),
        visibility=row.get("visibility", "private"),
        allowed_groups=[
            UUID(g) for g in (
                json.loads(row["allowed_groups"])
                if isinstance(row.get("allowed_groups"), str)
                else (row.get("allowed_groups") or [])
            )
        ],
        tags=(
            json.loads(row["tags"])
            if isinstance(row.get("tags"), str)
            else (row.get("tags") or [])
        ),
        thumbnail_url=thumbnail_url,
        stream_url=stream_url,
        storage_path=row.get("storage_path"),
        created_at=row["created_at"],
        uploaded_at=row.get("uploaded_at"),
        processed_at=row.get("processed_at"),
        updated_at=row.get("updated_at"),
    )
