"""
Video processing pipeline orchestrator.

This module provides the VideoProcessingPipeline class that orchestrates
all video processing stages from upload to indexing.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from processors.video.exceptions import VideoProcessingError
from processors.video.metadata import VideoMetadata
from processors.video.storage import VideoStorage
from processors.video.validator import VideoValidator

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    """Video processing pipeline stages."""

    VALIDATING = "validating"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    DETECTING_SCENES = "detecting_scenes"
    EXTRACTING_KEYFRAMES = "extracting_keyframes"
    ANALYZING_VISION = "analyzing_vision"
    EXTRACTING_OCR = "extracting_ocr"
    FUSING_CONTENT = "fusing_content"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineConfig:
    """Configuration for the video processing pipeline.

    Attributes:
        whisper_model: Whisper model for transcription.
        whisper_language: Language code or None for auto-detection.
        vision_provider: Vision LLM provider name.
        enable_ocr: Whether to run OCR extraction.
        scene_threshold: Scene detection threshold.
        keyframe_interval_seconds: Fallback keyframe interval.
        chunk_duration_seconds: Target chunk duration for fusion.
        chunk_overlap_seconds: Overlap between chunks.
        embedding_batch_size: Batch size for embedding generation.
    """

    whisper_model: str = "base"
    whisper_language: str | None = None
    vision_provider: str = "openai"
    enable_ocr: bool = True
    scene_threshold: float = 27.0
    keyframe_interval_seconds: float = 5.0
    chunk_duration_seconds: float = 20.0
    chunk_overlap_seconds: float = 2.0
    embedding_batch_size: int = 32


@dataclass
class PipelineProgress:
    """Progress information for pipeline execution.

    Attributes:
        stage: Current processing stage.
        progress: Progress percentage (0-100).
        message: Human-readable status message.
        started_at: Pipeline start time.
        stage_started_at: Current stage start time.
        stage_times: Timing for completed stages.
    """

    stage: PipelineStage = PipelineStage.VALIDATING
    progress: int = 0
    message: str = "Initializing..."
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    stage_started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    stage_times: dict[str, float] = field(default_factory=dict)

    def update(self, stage: PipelineStage, progress: int, message: str) -> None:
        """Update progress information."""
        now = datetime.now(tz=UTC)

        # Record time for previous stage
        if self.stage != stage:
            elapsed = (now - self.stage_started_at).total_seconds()
            self.stage_times[self.stage.value] = elapsed
            self.stage_started_at = now

        self.stage = stage
        self.progress = progress
        self.message = message


@dataclass
class PipelineResult:
    """Result of pipeline execution.

    Attributes:
        video_id: Processed video ID.
        success: Whether processing succeeded.
        stage: Final stage reached.
        error_message: Error message if failed.
        video_metadata: Extracted video metadata.
        transcript_segments: Number of transcript segments.
        keyframes_extracted: Number of keyframes.
        chunks_created: Number of chunks created.
        vectors_indexed: Number of vectors indexed.
        total_duration_seconds: Total processing time.
        stage_times: Timing breakdown by stage.
    """

    video_id: UUID
    success: bool
    stage: PipelineStage
    error_message: str | None = None
    video_metadata: VideoMetadata | None = None
    transcript_segments: int = 0
    keyframes_extracted: int = 0
    chunks_created: int = 0
    vectors_indexed: int = 0
    total_duration_seconds: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)


# Type alias for progress callback
ProgressCallback = Callable[[PipelineStage, int, str], None]


class VideoProcessingPipeline:
    """Orchestrates video processing through all stages.

    This class coordinates the execution of all video processing stages:
    1. Validation - Verify video format and extract metadata
    2. Audio extraction - Extract audio track for transcription
    3. Transcription - Convert speech to text with timestamps
    4. Scene detection - Detect scene boundaries
    5. Keyframe extraction - Extract representative frames
    6. Vision analysis - Generate scene descriptions
    7. OCR extraction - Extract on-screen text
    8. Content fusion - Combine modalities into chunks
    9. Embedding - Generate vector embeddings
    10. Indexing - Index in Qdrant and OpenSearch

    Example:
        pipeline = VideoProcessingPipeline(config)
        result = await pipeline.process(
            video_id=video_id,
            tenant_id=tenant_id,
            progress_callback=update_progress,
        )
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        storage: VideoStorage | None = None,
        validator: VideoValidator | None = None,
    ):
        """Initialize the pipeline.

        Args:
            config: Pipeline configuration.
            storage: Video storage service.
            validator: Video validator service.
        """
        self.config = config or PipelineConfig()
        self.storage = storage or VideoStorage()
        self.validator = validator or VideoValidator()
        self._progress = PipelineProgress()

    async def process(
        self,
        video_id: UUID,
        tenant_id: UUID,
        progress_callback: ProgressCallback | None = None,
        skip_stages: list[PipelineStage] | None = None,
        storage_path: str | None = None,
    ) -> PipelineResult:
        """Process a video through the full pipeline.

        Args:
            video_id: ID of the video to process.
            tenant_id: Tenant ID for multi-tenancy.
            progress_callback: Optional callback for progress updates.
            skip_stages: Optional list of stages to skip (for reprocessing).
            storage_path: Optional storage path. If provided, uses this path to
                download the video instead of constructing from video_id.

        Returns:
            PipelineResult with processing outcome.
        """
        skip_stages = skip_stages or []
        self._progress = PipelineProgress()
        start_time = datetime.now(tz=UTC)

        def update_progress(stage: PipelineStage, progress: int, message: str) -> None:
            """Update progress and notify callback."""
            self._progress.update(stage, progress, message)
            if progress_callback:
                progress_callback(stage, progress, message)

        try:
            # Download video for processing
            update_progress(PipelineStage.VALIDATING, 5, "Downloading video...")
            if storage_path:
                video_path = await self.storage.download_video_by_path(storage_path)
            else:
                video_path = await self.storage.download_video(tenant_id, video_id)

            try:
                # Stage 1: Validation
                video_metadata = await self._run_validation_stage(video_path, update_progress)

                # Stage 2: Audio extraction
                audio_path = None
                if PipelineStage.EXTRACTING_AUDIO not in skip_stages:
                    audio_path = await self._run_audio_extraction_stage(
                        video_path, tenant_id, video_id, update_progress
                    )

                # Stage 3: Transcription
                transcript_segments = []
                if audio_path and PipelineStage.TRANSCRIBING not in skip_stages:
                    transcript_segments = await self._run_transcription_stage(
                        audio_path, video_id, update_progress
                    )

                # Stage 4 & 5: Scene detection and keyframe extraction
                keyframes = []
                if PipelineStage.DETECTING_SCENES not in skip_stages:
                    keyframes = await self._run_scene_detection_stage(
                        video_path, tenant_id, video_id, update_progress
                    )

                # Stage 6: Vision analysis
                if keyframes and PipelineStage.ANALYZING_VISION not in skip_stages:
                    await self._run_vision_analysis_stage(keyframes, video_id, update_progress)

                # Stage 7: OCR extraction
                if (
                    keyframes
                    and self.config.enable_ocr
                    and PipelineStage.EXTRACTING_OCR not in skip_stages
                ):
                    await self._run_ocr_stage(keyframes, video_id, update_progress)

                # Stage 8: Content fusion
                chunks = []
                if PipelineStage.FUSING_CONTENT not in skip_stages:
                    chunks = await self._run_fusion_stage(
                        video_id,
                        video_metadata.duration_seconds,
                        transcript_segments,
                        keyframes,
                        update_progress,
                    )

                # Stage 9: Embedding
                if chunks and PipelineStage.EMBEDDING not in skip_stages:
                    await self._run_embedding_stage(chunks, video_id, update_progress)

                # Stage 10: Indexing
                vectors_indexed = 0
                if chunks and PipelineStage.INDEXING not in skip_stages:
                    vectors_indexed = await self._run_indexing_stage(
                        chunks, tenant_id, video_id, update_progress
                    )

                # Complete
                update_progress(PipelineStage.COMPLETED, 100, "Processing complete")

                end_time = datetime.now(tz=UTC)
                total_duration = (end_time - start_time).total_seconds()

                return PipelineResult(
                    video_id=video_id,
                    success=True,
                    stage=PipelineStage.COMPLETED,
                    video_metadata=video_metadata,
                    transcript_segments=len(transcript_segments),
                    keyframes_extracted=len(keyframes),
                    chunks_created=len(chunks),
                    vectors_indexed=vectors_indexed,
                    total_duration_seconds=total_duration,
                    stage_times=self._progress.stage_times.copy(),
                )

            finally:
                # Clean up downloaded video
                if video_path.exists():
                    video_path.unlink()

        except VideoProcessingError as e:
            update_progress(PipelineStage.FAILED, 0, str(e))
            end_time = datetime.now(tz=UTC)

            return PipelineResult(
                video_id=video_id,
                success=False,
                stage=self._progress.stage,
                error_message=str(e),
                total_duration_seconds=(end_time - start_time).total_seconds(),
                stage_times=self._progress.stage_times.copy(),
            )
        except Exception as e:
            logger.exception("Unexpected error in pipeline: %s", e)
            update_progress(PipelineStage.FAILED, 0, f"Unexpected error: {e}")
            end_time = datetime.now(tz=UTC)

            return PipelineResult(
                video_id=video_id,
                success=False,
                stage=self._progress.stage,
                error_message=f"Unexpected error: {e}",
                total_duration_seconds=(end_time - start_time).total_seconds(),
                stage_times=self._progress.stage_times.copy(),
            )

    async def _run_validation_stage(
        self,
        video_path: Path,
        update_progress: ProgressCallback,
    ) -> VideoMetadata:
        """Run video validation stage.

        Args:
            video_path: Path to video file.
            update_progress: Progress callback.

        Returns:
            Extracted video metadata.
        """
        update_progress(PipelineStage.VALIDATING, 10, "Validating video...")

        metadata = await self.validator.validate(video_path)

        logger.info(
            "Video validated: %s, duration=%.1fs, resolution=%s",
            metadata.filename,
            metadata.duration_seconds,
            metadata.resolution,
        )

        return metadata

    async def _run_audio_extraction_stage(
        self,
        video_path: Path,
        tenant_id: UUID,
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> Path | None:
        """Run audio extraction stage.

        Args:
            video_path: Path to video file.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            update_progress: Progress callback.

        Returns:
            Path to extracted audio file or None if no audio.
        """
        update_progress(PipelineStage.EXTRACTING_AUDIO, 15, "Extracting audio...")

        # TODO: Implement AudioExtractor service
        # For now, return placeholder
        logger.info("Audio extraction stage: not yet implemented")
        return None

    async def _run_transcription_stage(
        self,
        audio_path: Path,
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> list[dict]:
        """Run transcription stage.

        Args:
            audio_path: Path to audio file.
            video_id: Video identifier.
            update_progress: Progress callback.

        Returns:
            List of transcript segments.
        """
        update_progress(PipelineStage.TRANSCRIBING, 25, "Transcribing audio...")

        # TODO: Implement WhisperTranscriber service
        # For now, return empty list
        logger.info("Transcription stage: not yet implemented")
        return []

    async def _run_scene_detection_stage(
        self,
        video_path: Path,
        tenant_id: UUID,
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> list[dict]:
        """Run scene detection and keyframe extraction stage.

        Args:
            video_path: Path to video file.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            update_progress: Progress callback.

        Returns:
            List of extracted keyframes with metadata.
        """
        update_progress(PipelineStage.DETECTING_SCENES, 35, "Detecting scenes...")

        # TODO: Implement SceneDetector service
        update_progress(PipelineStage.EXTRACTING_KEYFRAMES, 45, "Extracting keyframes...")

        # TODO: Implement KeyframeExtractor service
        # For now, return empty list
        logger.info("Scene detection and keyframe extraction: not yet implemented")
        return []

    async def _run_vision_analysis_stage(
        self,
        keyframes: list[dict],
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> None:
        """Run vision analysis stage.

        Args:
            keyframes: List of keyframes to analyze.
            video_id: Video identifier.
            update_progress: Progress callback.
        """
        update_progress(PipelineStage.ANALYZING_VISION, 55, "Analyzing frames...")

        # TODO: Implement VisionAnalyzer service
        logger.info("Vision analysis stage: not yet implemented")

    async def _run_ocr_stage(
        self,
        keyframes: list[dict],
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> None:
        """Run OCR extraction stage.

        Args:
            keyframes: List of keyframes to process.
            video_id: Video identifier.
            update_progress: Progress callback.
        """
        update_progress(PipelineStage.EXTRACTING_OCR, 65, "Extracting text...")

        # TODO: Implement OCRBatchProcessor service
        logger.info("OCR extraction stage: not yet implemented")

    async def _run_fusion_stage(
        self,
        video_id: UUID,
        duration_seconds: float,
        transcript_segments: list[dict],
        keyframes: list[dict],
        update_progress: ProgressCallback,
    ) -> list[dict]:
        """Run content fusion stage.

        Args:
            video_id: Video identifier.
            duration_seconds: Video duration.
            transcript_segments: Transcript segments.
            keyframes: Keyframes with descriptions.
            update_progress: Progress callback.

        Returns:
            List of fused content chunks.
        """
        update_progress(PipelineStage.FUSING_CONTENT, 75, "Fusing content...")

        # TODO: Implement ContentFusionService
        # For now, return empty list
        logger.info("Content fusion stage: not yet implemented")
        return []

    async def _run_embedding_stage(
        self,
        chunks: list[dict],
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> None:
        """Run embedding generation stage.

        Args:
            chunks: Content chunks to embed.
            video_id: Video identifier.
            update_progress: Progress callback.
        """
        update_progress(PipelineStage.EMBEDDING, 85, "Generating embeddings...")

        # TODO: Implement VideoChunkEmbedder service
        logger.info("Embedding stage: not yet implemented")

    async def _run_indexing_stage(
        self,
        chunks: list[dict],
        tenant_id: UUID,
        video_id: UUID,
        update_progress: ProgressCallback,
    ) -> int:
        """Run indexing stage.

        Args:
            chunks: Chunks with embeddings to index.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            update_progress: Progress callback.

        Returns:
            Number of vectors indexed.
        """
        update_progress(PipelineStage.INDEXING, 95, "Indexing vectors...")

        # TODO: Implement QdrantVideoIndexer and OpenSearchVideoIndexer
        logger.info("Indexing stage: not yet implemented")
        return 0

    @property
    def current_progress(self) -> PipelineProgress:
        """Get current pipeline progress."""
        return self._progress
