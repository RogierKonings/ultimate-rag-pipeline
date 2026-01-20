"""Video upload and management API routes."""

import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from api.dependencies import get_current_user
from api.schemas.video import (
    PresignedUploadRequest,
    PresignedUploadResponse,
    VideoMetadataResponse,
    VideoStatus,
    VideoStatusResponse,
    VideoUploadResponse,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from processors.video import VideoStorage, VideoStorageConfig, VideoValidator

logger = logging.getLogger(__name__)

router = APIRouter()


# Initialize services (will be replaced with dependency injection)
def get_video_storage() -> VideoStorage:
    """Get video storage service."""
    return VideoStorage(VideoStorageConfig())


def get_video_validator() -> VideoValidator:
    """Get video validator service."""
    return VideoValidator()


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=202,
    summary="Upload video file",
    description="Upload a video file for processing via multipart form data.",
)
async def upload_video(
    file: UploadFile = File(..., description="Video file to upload"),
    title: str | None = Form(default=None, description="Video title"),
    description: str | None = Form(default=None, description="Video description"),
    visibility: str = Form(default="private", description="Visibility: public, private, group"),
    current_user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_video_storage),
    validator: VideoValidator = Depends(get_video_validator),
) -> VideoUploadResponse:
    """
    Upload a video file for processing.

    The video will be validated, stored in MinIO, and a processing job
    will be queued. Use the returned job_id to track processing progress.

    **Supported formats:** MP4, MOV, AVI, MKV, WebM
    **Max duration:** 1 hour (3600 seconds)
    **Max file size:** 5 GB
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    extension = Path(file.filename).suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {extension}. Allowed: {', '.join(allowed_extensions)}",
        )

    # Generate video ID
    video_id = uuid4()

    try:
        # Save to temp file for validation
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            # Read file in chunks to handle large files
            while chunk := await file.read(8192):
                temp_file.write(chunk)

        # Validate video
        try:
            metadata = await validator.validate(temp_path)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Video validation failed: {e}",
            ) from e

        # Upload to MinIO
        await storage.ensure_bucket_exists()

        with temp_path.open("rb") as f:
            storage_path = await storage.upload_video(
                file_data=f,
                tenant_id=tenant_id,
                video_id=video_id,
                filename=file.filename,
                content_type=file.content_type or "video/mp4",
            )

        # Create database record (placeholder - will be implemented with proper DB session)
        # For now, we'll just return the response
        # TODO: Create SourceVideo record in database
        # TODO: Queue Celery task for processing

        job_id = uuid4()  # Placeholder until Celery task is created

        logger.info(
            "Video uploaded successfully: video_id=%s, filename=%s, size=%d bytes",
            video_id,
            file.filename,
            metadata.file_size_bytes,
        )

        return VideoUploadResponse(
            video_id=video_id,
            job_id=job_id,
            filename=file.filename,
            status=VideoStatus.UPLOADED,
            storage_path=storage_path,
            message="Video uploaded successfully. Processing will begin shortly.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to upload video: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload video: {e}",
        ) from e
    finally:
        # Clean up temp file
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink()


@router.post(
    "/upload-url",
    response_model=PresignedUploadResponse,
    summary="Get presigned upload URL",
    description="Get a presigned URL for direct upload to storage.",
)
async def get_presigned_upload_url(
    request: PresignedUploadRequest,
    current_user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_video_storage),
) -> PresignedUploadResponse:
    """
    Get a presigned URL for direct video upload.

    This allows clients to upload directly to MinIO, bypassing the API
    server. Useful for large files or client-side uploads.

    After upload completes, call POST /api/v1/videos/{video_id}/confirm
    to start processing.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # Validate file size
    max_size = 5 * 1024 * 1024 * 1024  # 5 GB
    if request.file_size_bytes > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {request.file_size_bytes / (1024 * 1024):.1f}MB (max: 5000MB)",
        )

    # Validate extension
    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    extension = Path(request.filename).suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {extension}. Allowed: {', '.join(allowed_extensions)}",
        )

    # Generate video ID and presigned URL
    video_id = uuid4()

    try:
        await storage.ensure_bucket_exists()
        upload_url = storage.get_presigned_upload_url(
            tenant_id=tenant_id,
            video_id=video_id,
            extension=extension,
            expires_hours=1,
        )

        # Calculate storage path
        storage_path = f"{tenant_id}/originals/{video_id}{extension}"
        expires_at = datetime.now(tz=UTC) + timedelta(hours=1)

        # TODO: Create pending SourceVideo record in database

        logger.info(
            "Generated presigned upload URL: video_id=%s, filename=%s",
            video_id,
            request.filename,
        )

        return PresignedUploadResponse(
            video_id=video_id,
            upload_url=upload_url,
            expires_at=expires_at,
            storage_path=storage_path,
        )

    except Exception as e:
        logger.exception("Failed to generate presigned URL: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate upload URL: {e}",
        ) from e


@router.get(
    "/{video_id}/status",
    response_model=VideoStatusResponse,
    summary="Get video processing status",
    description="Get the current processing status of a video.",
)
async def get_video_status(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
) -> VideoStatusResponse:
    """
    Get the processing status of a video.

    **Status Values:**
    - `pending`: Video record created, waiting for upload
    - `uploaded`: Video uploaded, waiting for processing
    - `processing`: Video is being processed
    - `completed`: Processing finished successfully
    - `failed`: Processing failed (check error_message)
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # TODO: Query database for video status
    # For now, return a placeholder response
    raise HTTPException(
        status_code=404,
        detail=f"Video {video_id} not found",
    )


@router.get(
    "/{video_id}",
    response_model=VideoMetadataResponse,
    summary="Get video details",
    description="Get full metadata and URLs for a video.",
)
async def get_video_details(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_video_storage),
) -> VideoMetadataResponse:
    """
    Get full details for a video.

    Returns video metadata, processing status, and presigned URLs
    for thumbnail and streaming.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # TODO: Query database for video
    # TODO: Generate presigned URLs for thumbnail and streaming
    raise HTTPException(
        status_code=404,
        detail=f"Video {video_id} not found",
    )


@router.post(
    "/{video_id}/confirm",
    response_model=VideoUploadResponse,
    status_code=202,
    summary="Confirm presigned upload",
    description="Confirm that a presigned upload is complete and start processing.",
)
async def confirm_presigned_upload(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_video_storage),
    validator: VideoValidator = Depends(get_video_validator),
) -> VideoUploadResponse:
    """
    Confirm that a presigned upload is complete.

    Call this after uploading via a presigned URL to validate
    the video and start processing.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # Check if video exists in storage
    # TODO: Get extension from database record
    extension = "mp4"
    if not storage.file_exists(tenant_id, video_id, extension):
        raise HTTPException(
            status_code=404,
            detail=f"Video file not found in storage for video_id={video_id}",
        )

    # Download and validate
    try:
        temp_path = await storage.download_video(tenant_id, video_id, extension)

        try:
            await validator.validate(temp_path)
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()

    except Exception as e:
        logger.exception("Video validation failed: %s", e)
        raise HTTPException(
            status_code=400,
            detail=f"Video validation failed: {e}",
        ) from e

    # TODO: Update database record status to "uploaded"
    # TODO: Queue Celery task for processing

    job_id = uuid4()  # Placeholder

    return VideoUploadResponse(
        video_id=video_id,
        job_id=job_id,
        filename=f"{video_id}.{extension}",
        status=VideoStatus.UPLOADED,
        storage_path=f"{tenant_id}/originals/{video_id}.{extension}",
        message="Video confirmed. Processing will begin shortly.",
    )


@router.delete(
    "/{video_id}",
    status_code=204,
    summary="Delete video",
    description="Delete a video and all associated data.",
)
async def delete_video(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_video_storage),
) -> None:
    """
    Delete a video and all associated data.

    This will:
    1. Delete vectors from Qdrant
    2. Delete documents from OpenSearch
    3. Delete records from PostgreSQL
    4. Delete files from MinIO
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in user context")

    # TODO: Verify video exists and belongs to tenant
    # TODO: Delete from Qdrant
    # TODO: Delete from OpenSearch
    # TODO: Delete from PostgreSQL

    # Delete files from MinIO
    try:
        deleted = await storage.delete_video_files(tenant_id, video_id)
        logger.info(
            "Deleted video files: video_id=%s, deleted=%s",
            video_id,
            deleted,
        )
    except Exception as e:
        logger.exception("Failed to delete video files: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete video: {e}",
        ) from e
