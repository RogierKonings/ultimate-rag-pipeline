"""Video upload and management API routes.

NOTE: Video processing has been migrated to the Rust rag-video crate.
These routes are stubs pending integration with the Rust video pipeline.
"""

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", status_code=501)
async def upload_video():
    """
    Upload a video file for processing.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    Video processing has been migrated to the rag-video Rust crate.
    """
    raise HTTPException(
        status_code=501,
        detail="Video upload not implemented. Video processing has been migrated to Rust rag-video crate.",
    )


@router.post("/upload-url", status_code=501)
async def get_presigned_upload_url():
    """
    Get a presigned URL for direct video upload.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    """
    raise HTTPException(
        status_code=501,
        detail="Presigned upload not implemented. Video processing has been migrated to Rust rag-video crate.",
    )


@router.get("/{video_id}/status", status_code=501)
async def get_video_status(video_id: str):
    """
    Get the processing status of a video.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    """
    raise HTTPException(
        status_code=501,
        detail="Video status not implemented. Video processing has been migrated to Rust rag-video crate.",
    )


@router.get("/{video_id}", status_code=501)
async def get_video_details(video_id: str):
    """
    Get full details for a video.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    """
    raise HTTPException(
        status_code=501,
        detail="Video details not implemented. Video processing has been migrated to Rust rag-video crate.",
    )


@router.post("/{video_id}/confirm", status_code=501)
async def confirm_presigned_upload(video_id: str):
    """
    Confirm that a presigned upload is complete.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    """
    raise HTTPException(
        status_code=501,
        detail="Upload confirmation not implemented. Video processing has been migrated to Rust rag-video crate.",
    )


@router.delete("/{video_id}", status_code=501)
async def delete_video(video_id: str):
    """
    Delete a video and all associated data.

    NOTE: This endpoint is not yet integrated with the new Rust video pipeline.
    """
    raise HTTPException(
        status_code=501,
        detail="Video deletion not implemented. Video processing has been migrated to Rust rag-video crate.",
    )
