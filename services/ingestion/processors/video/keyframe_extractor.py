"""Keyframe extraction service for video processing.

This module provides the KeyframeExtractor class that extracts keyframes
from videos at specified timestamps using FFmpeg.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from processors.video.exceptions import KeyframeExtractionError
from processors.video.storage import VideoStorage

logger = logging.getLogger(__name__)


@dataclass
class KeyframeExtractionConfig:
    """Configuration for keyframe extraction.

    Attributes:
        output_width: Maximum output width (preserves aspect ratio).
        output_height: Maximum output height (preserves aspect ratio).
        thumbnail_width: Thumbnail width.
        thumbnail_height: Thumbnail height.
        quality: JPEG quality (1-100).
        ffmpeg_path: Path to ffmpeg executable.
        concurrent_extractions: Max concurrent FFmpeg processes.
        timeout_seconds: Timeout per extraction.
    """

    output_width: int = 1280
    output_height: int = 720
    thumbnail_width: int = 320
    thumbnail_height: int = 180
    quality: int = 85
    ffmpeg_path: str = "ffmpeg"
    concurrent_extractions: int = 4
    timeout_seconds: float = 30.0


@dataclass
class ExtractedKeyframe:
    """An extracted keyframe.

    Attributes:
        frame_index: Frame index in extraction order.
        timestamp_seconds: Timestamp in video.
        image_path: Path to extracted image file.
        thumbnail_path: Path to thumbnail image.
        width: Image width.
        height: Image height.
        file_size_bytes: Image file size.
        is_scene_boundary: Whether this is at a scene boundary.
        scene_index: Associated scene index.
    """

    frame_index: int
    timestamp_seconds: float
    image_path: Path
    thumbnail_path: Path | None = None
    width: int = 0
    height: int = 0
    file_size_bytes: int = 0
    is_scene_boundary: bool = True
    scene_index: int | None = None
    storage_path: str | None = None
    thumbnail_storage_path: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def timestamp_ms(self) -> int:
        """Get timestamp in milliseconds."""
        return int(self.timestamp_seconds * 1000)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "frame_index": self.frame_index,
            "timestamp_seconds": self.timestamp_seconds,
            "timestamp_ms": self.timestamp_ms,
            "image_path": str(self.image_path) if self.image_path else None,
            "thumbnail_path": str(self.thumbnail_path) if self.thumbnail_path else None,
            "storage_path": self.storage_path,
            "thumbnail_storage_path": self.thumbnail_storage_path,
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "is_scene_boundary": self.is_scene_boundary,
            "scene_index": self.scene_index,
        }


@dataclass
class KeyframeExtractionResult:
    """Result of keyframe extraction.

    Attributes:
        keyframes: List of extracted keyframes.
        total_extracted: Number of keyframes extracted.
        failed_count: Number of failed extractions.
        temp_dir: Temporary directory containing images.
    """

    keyframes: list[ExtractedKeyframe]
    total_extracted: int
    failed_count: int = 0
    temp_dir: Path | None = None
    metadata: dict = field(default_factory=dict)

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self.temp_dir and self.temp_dir.exists():
            import shutil

            shutil.rmtree(self.temp_dir)
            self.temp_dir = None


class KeyframeExtractor:
    """Extracts keyframes from videos at specified timestamps.

    Uses FFmpeg to extract frames at precise timestamps with
    optional thumbnail generation.

    Example:
        extractor = KeyframeExtractor()
        result = await extractor.extract(
            video_path="/path/to/video.mp4",
            timestamps=[0.0, 5.0, 10.0, 15.0],
        )
        for keyframe in result.keyframes:
            print(f"Frame {keyframe.frame_index}: {keyframe.timestamp_seconds}s")
    """

    def __init__(
        self,
        config: KeyframeExtractionConfig | None = None,
        storage: VideoStorage | None = None,
    ):
        """Initialize keyframe extractor.

        Args:
            config: Extraction configuration.
            storage: Video storage service for uploading.
        """
        self.config = config or KeyframeExtractionConfig()
        self.storage = storage

    async def extract(
        self,
        video_path: str | Path,
        timestamps: list[float],
        scene_boundaries: list[float] | None = None,
        generate_thumbnails: bool = True,
    ) -> KeyframeExtractionResult:
        """Extract keyframes at specified timestamps.

        Args:
            video_path: Path to the video file.
            timestamps: List of timestamps in seconds.
            scene_boundaries: List of timestamps that are scene boundaries.
            generate_thumbnails: Whether to generate thumbnails.

        Returns:
            KeyframeExtractionResult with extracted frames.

        Raises:
            KeyframeExtractionError: If extraction fails.
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise KeyframeExtractionError(f"Video file not found: {video_path}")

        if not timestamps:
            raise KeyframeExtractionError("No timestamps provided for extraction")

        scene_boundaries = scene_boundaries or timestamps
        scene_boundary_set = set(scene_boundaries)

        logger.info(
            "Extracting %d keyframes from video: %s",
            len(timestamps),
            video_path.name,
        )

        # Create temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix="keyframes_"))

        try:
            # Extract frames with concurrency limit
            semaphore = asyncio.Semaphore(self.config.concurrent_extractions)
            tasks = []

            for i, timestamp in enumerate(sorted(timestamps)):
                is_boundary = timestamp in scene_boundary_set
                task = self._extract_single_frame(
                    video_path=video_path,
                    timestamp=timestamp,
                    frame_index=i,
                    output_dir=temp_dir,
                    generate_thumbnail=generate_thumbnails,
                    is_scene_boundary=is_boundary,
                    semaphore=semaphore,
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            keyframes = []
            failed_count = 0

            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Keyframe extraction failed: %s", result)
                    failed_count += 1
                elif result is not None:
                    keyframes.append(result)

            # Sort by timestamp
            keyframes.sort(key=lambda k: k.timestamp_seconds)

            # Re-index after sorting
            for i, keyframe in enumerate(keyframes):
                keyframe.frame_index = i

            logger.info(
                "Extracted %d keyframes (%d failed)",
                len(keyframes),
                failed_count,
            )

            return KeyframeExtractionResult(
                keyframes=keyframes,
                total_extracted=len(keyframes),
                failed_count=failed_count,
                temp_dir=temp_dir,
                metadata={
                    "video_path": str(video_path),
                    "timestamps_requested": len(timestamps),
                },
            )

        except Exception as e:
            # Clean up on failure
            import shutil

            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise KeyframeExtractionError(f"Keyframe extraction failed: {e}") from e

    async def _extract_single_frame(
        self,
        video_path: Path,
        timestamp: float,
        frame_index: int,
        output_dir: Path,
        generate_thumbnail: bool,
        is_scene_boundary: bool,
        semaphore: asyncio.Semaphore,
    ) -> ExtractedKeyframe | None:
        """Extract a single frame at a timestamp.

        Args:
            video_path: Path to video.
            timestamp: Timestamp in seconds.
            frame_index: Frame index.
            output_dir: Output directory.
            generate_thumbnail: Generate thumbnail.
            is_scene_boundary: Is scene boundary.
            semaphore: Concurrency semaphore.

        Returns:
            ExtractedKeyframe or None on failure.
        """
        async with semaphore:
            # Output paths
            image_path = output_dir / f"{frame_index:05d}.jpg"
            thumbnail_path = (
                output_dir / f"{frame_index:05d}_thumb.jpg" if generate_thumbnail else None
            )

            # Build FFmpeg command for main image
            scale_filter = f"scale='min({self.config.output_width},iw)':min'({self.config.output_height},ih)':force_original_aspect_ratio=decrease"
            cmd = [
                self.config.ffmpeg_path,
                "-ss",
                str(timestamp),
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-vf",
                scale_filter,
                "-q:v",
                str(int((100 - self.config.quality) / 100 * 31)),  # FFmpeg quality scale
                "-y",
                str(image_path),
            ]

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout_seconds,
                )

                if process.returncode != 0 or not image_path.exists():
                    logger.warning(
                        "Failed to extract frame at %.2fs",
                        timestamp,
                    )
                    return None

                # Get image dimensions
                width, height = await self._get_image_dimensions(image_path)

                # Generate thumbnail
                if generate_thumbnail and thumbnail_path:
                    await self._generate_thumbnail(image_path, thumbnail_path)

                return ExtractedKeyframe(
                    frame_index=frame_index,
                    timestamp_seconds=timestamp,
                    image_path=image_path,
                    thumbnail_path=thumbnail_path
                    if thumbnail_path and thumbnail_path.exists()
                    else None,
                    width=width,
                    height=height,
                    file_size_bytes=image_path.stat().st_size,
                    is_scene_boundary=is_scene_boundary,
                )

            except TimeoutError:
                logger.warning("Timeout extracting frame at %.2fs", timestamp)
                return None
            except Exception as e:
                logger.warning("Error extracting frame at %.2fs: %s", timestamp, e)
                return None

    async def _generate_thumbnail(
        self,
        image_path: Path,
        thumbnail_path: Path,
    ) -> bool:
        """Generate thumbnail from extracted image.

        Args:
            image_path: Source image path.
            thumbnail_path: Output thumbnail path.

        Returns:
            True if successful.
        """
        scale_filter = f"scale={self.config.thumbnail_width}:{self.config.thumbnail_height}:force_original_aspect_ratio=decrease"
        cmd = [
            self.config.ffmpeg_path,
            "-i",
            str(image_path),
            "-vf",
            scale_filter,
            "-q:v",
            "5",
            "-y",
            str(thumbnail_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await asyncio.wait_for(
                process.communicate(),
                timeout=10.0,
            )

            return process.returncode == 0 and thumbnail_path.exists()

        except Exception as e:
            logger.warning("Failed to generate thumbnail: %s", e)
            return False

    async def _get_image_dimensions(self, image_path: Path) -> tuple[int, int]:
        """Get image dimensions using ffprobe.

        Args:
            image_path: Path to image.

        Returns:
            Tuple of (width, height).
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(image_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await process.communicate()
            if process.returncode == 0:
                parts = stdout.decode().strip().split(",")
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
        except Exception as e:
            logger.debug("Could not get image dimensions: %s", e)

        return 0, 0

    async def extract_and_upload(
        self,
        video_path: str | Path,
        timestamps: list[float],
        tenant_id: UUID,
        video_id: UUID,
        scene_boundaries: list[float] | None = None,
    ) -> KeyframeExtractionResult:
        """Extract keyframes and upload to storage.

        Args:
            video_path: Path to video.
            timestamps: Extraction timestamps.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            scene_boundaries: Scene boundary timestamps.

        Returns:
            KeyframeExtractionResult with storage paths.

        Raises:
            KeyframeExtractionError: If extraction or upload fails.
        """
        if self.storage is None:
            raise KeyframeExtractionError("Storage service not configured")

        # Extract keyframes
        result = await self.extract(
            video_path=video_path,
            timestamps=timestamps,
            scene_boundaries=scene_boundaries,
            generate_thumbnails=True,
        )

        try:
            # Upload each keyframe
            for keyframe in result.keyframes:
                # Upload main image
                storage_path = await self.storage.upload_keyframe(
                    file_path=keyframe.image_path,
                    tenant_id=tenant_id,
                    video_id=video_id,
                    frame_index=keyframe.frame_index,
                )
                keyframe.storage_path = storage_path

                # Upload thumbnail
                if keyframe.thumbnail_path and keyframe.thumbnail_path.exists():
                    thumb_storage_path = await self.storage.upload_thumbnail(
                        file_path=keyframe.thumbnail_path,
                        tenant_id=tenant_id,
                        video_id=video_id,
                        frame_index=keyframe.frame_index,
                    )
                    keyframe.thumbnail_storage_path = thumb_storage_path

            logger.info(
                "Uploaded %d keyframes for video_id=%s",
                len(result.keyframes),
                video_id,
            )

            return result

        finally:
            # Clean up temp files
            result.cleanup()
