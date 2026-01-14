"""Video ingestion tasks.

This module provides Celery tasks for video processing:
- process_video: Process a single video through the full pipeline

The pipeline stages are:
1. Validate video format and extract metadata
2. Extract audio track
3. Transcribe audio with Whisper
4. Detect scenes and extract keyframes
5. Analyze keyframes with vision LLM
6. Extract OCR from keyframes
7. Fuse content into chunks
8. Generate embeddings
9. Index to stores (Qdrant, OpenSearch, PostgreSQL)
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery.exceptions import Reject, SoftTimeLimitExceeded

from .callbacks import send_to_dlq
from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.video_ingest.process_video",
    max_retries=2,
    default_retry_delay=120,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=900,  # Max 15 min between retries
    acks_late=True,
    time_limit=7200,  # 2 hour max for video processing
    soft_time_limit=6900,  # Soft limit 1h 55min
)
def process_video(
    self,
    video_id: str,
    tenant_id: str,
    processing_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process a video through the full processing pipeline.

    Args:
        video_id: UUID of the video to process.
        tenant_id: UUID of the tenant.
        processing_options: Optional processing configuration.

    Returns:
        Dict with processing results including chunks_created, vectors_indexed, etc.

    Raises:
        Reject: If task times out.
        Exception: On unrecoverable errors after max retries.
    """
    processing_options = processing_options or {}

    try:
        # Update task state to STARTED
        self.update_state(
            state="STARTED",
            meta={
                "stage": "initializing",
                "progress": 0,
                "message": "Starting video processing...",
            },
        )

        # Run async pipeline
        return asyncio.run(
            _process_video_async(
                task=self,
                video_id=UUID(video_id),
                tenant_id=UUID(tenant_id),
                processing_options=processing_options,
            ),
        )

    except SoftTimeLimitExceeded:
        logger.error(f"Task timed out for video: {video_id}")
        self.update_state(
            state="FAILURE",
            meta={"error": "Task timed out", "video_id": video_id},
        )
        raise Reject("Task timed out", requeue=False) from None

    except Exception as e:
        error_info = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "video_id": video_id,
        }

        logger.error(f"Error processing video {video_id}: {e}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e

        # Max retries exceeded, send to DLQ
        send_to_dlq.delay(
            {
                "task_name": "process_video",
                "args": [video_id, tenant_id],
                "kwargs": {"processing_options": processing_options},
                "error": error_info,
                "retries": self.request.retries,
            },
        )
        raise


async def _process_video_async(
    task,
    video_id: UUID,
    tenant_id: UUID,
    processing_options: dict[str, Any],
) -> dict[str, Any]:
    """Async implementation of video processing pipeline.

    Args:
        task: Celery task instance for state updates.
        video_id: UUID of the video to process.
        tenant_id: UUID of the tenant.
        processing_options: Processing configuration options.

    Returns:
        Processing results dict.
    """
    from processors.video import (
        PipelineConfig,
        PipelineStage,
        VideoProcessingPipeline,
        VideoStorage,
        VideoStorageConfig,
        VideoValidator,
    )

    from config import get_settings

    settings = get_settings()

    # Create progress callback that updates Celery task state
    def progress_callback(stage: PipelineStage, progress: int, message: str) -> None:
        """Update Celery task state with pipeline progress."""
        task.update_state(
            state="PROGRESS",
            meta={
                "stage": stage.value,
                "progress": progress,
                "message": message,
            },
        )

    # Build pipeline configuration from options
    pipeline_config = PipelineConfig(
        whisper_model=processing_options.get("whisper_model", "base"),
        whisper_language=processing_options.get("whisper_language"),
        vision_provider=processing_options.get("vision_provider", "openai"),
        enable_ocr=processing_options.get("enable_ocr", True),
        scene_threshold=processing_options.get("scene_threshold", 27.0),
        keyframe_interval_seconds=processing_options.get("keyframe_interval_seconds", 5.0),
        chunk_duration_seconds=processing_options.get("chunk_duration_seconds", 20.0),
        chunk_overlap_seconds=processing_options.get("chunk_overlap_seconds", 2.0),
        embedding_batch_size=processing_options.get("embedding_batch_size", 32),
    )

    # Create storage and validator services
    storage_config = VideoStorageConfig(
        endpoint_url=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket_name=settings.minio_bucket_name,
        secure=settings.minio_secure,
    )
    storage = VideoStorage(storage_config)
    validator = VideoValidator()

    # Create and run pipeline
    pipeline = VideoProcessingPipeline(
        config=pipeline_config,
        storage=storage,
        validator=validator,
    )

    # Determine which stages to skip based on options
    skip_stages = []
    if processing_options.get("skip_transcription"):
        skip_stages.append(PipelineStage.TRANSCRIBING)
    if processing_options.get("skip_vision"):
        skip_stages.append(PipelineStage.ANALYZING_VISION)
    if not pipeline_config.enable_ocr:
        skip_stages.append(PipelineStage.EXTRACTING_OCR)

    # Run the pipeline
    result = await pipeline.process(
        video_id=video_id,
        tenant_id=tenant_id,
        progress_callback=progress_callback,
        skip_stages=skip_stages if skip_stages else None,
    )

    # Update database with result
    await _update_video_status(
        video_id=video_id,
        tenant_id=tenant_id,
        result=result,
        settings=settings,
    )

    end_time = datetime.now(tz=UTC)

    return {
        "video_id": str(video_id),
        "tenant_id": str(tenant_id),
        "success": result.success,
        "stage": result.stage.value,
        "error_message": result.error_message,
        "transcript_segments": result.transcript_segments,
        "keyframes_extracted": result.keyframes_extracted,
        "chunks_created": result.chunks_created,
        "vectors_indexed": result.vectors_indexed,
        "total_duration_seconds": result.total_duration_seconds,
        "stage_times": result.stage_times,
        "completed_at": end_time.isoformat(),
    }


async def _update_video_status(
    video_id: UUID,
    tenant_id: UUID,
    result,
    settings,
) -> None:
    """Update video status in the database.

    Args:
        video_id: UUID of the video.
        tenant_id: UUID of the tenant.
        result: PipelineResult from processing.
        settings: Application settings.
    """
    import asyncpg
    from processors.video import PipelineStage

    # Map pipeline stage to video status
    if result.success:
        status = "completed"
        processing_stage = "completed"
    elif result.stage == PipelineStage.FAILED:
        status = "failed"
        processing_stage = result.stage_times.get("last_stage", "failed")
    else:
        status = "processing"
        processing_stage = result.stage.value

    try:
        pool = await asyncpg.create_pool(settings.database_url)
        try:
            await pool.execute(
                """
                UPDATE source_videos
                SET status = $1,
                    processing_stage = $2,
                    error_message = $3,
                    processing_completed_at = $4,
                    updated_at = NOW()
                WHERE id = $5 AND tenant_id = $6
                """,
                status,
                processing_stage,
                result.error_message,
                datetime.now(tz=UTC) if result.success else None,
                video_id,
                tenant_id,
            )
            logger.info(
                "Updated video status: video_id=%s, status=%s, stage=%s",
                video_id,
                status,
                processing_stage,
            )
        finally:
            await pool.close()
    except Exception as e:
        logger.error(f"Failed to update video status: {e}")
        # Don't fail the task if status update fails
