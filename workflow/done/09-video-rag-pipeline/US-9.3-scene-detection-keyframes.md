# US-9.3: Scene Detection and Keyframe Extraction

> **Story ID:** US-9.3
> **Epic:** Video RAG Pipeline
> **Priority:** High
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.1 (Video Upload)

## User Story

**As a** system
**I want** to detect scene changes and extract keyframes
**So that** visual content can be analyzed

## Context

Scene detection identifies visual boundaries in videos where significant changes occur (cuts, fades, transitions). Keyframes are representative images extracted at these boundaries and at regular intervals. These keyframes serve as input for visual analysis (US-9.4) and OCR (US-9.5), and are stored as thumbnails for the UI timeline.

## Technical Requirements

### Scene Detector

```python
# processors/video/scene_detection.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import logging

logger = logging.getLogger(__name__)

@dataclass
class SceneBoundary:
    """Represents a detected scene change."""
    timestamp_ms: int
    frame_number: int
    scene_index: int
    detection_type: Literal["cut", "fade", "interval"]
    confidence: float = 1.0

@dataclass
class SceneDetectionResult:
    success: bool
    scenes: list[SceneBoundary] = field(default_factory=list)
    total_frames: int = 0
    fps: float = 0.0
    error: str | None = None

@dataclass
class SceneDetectionConfig:
    """Configuration for scene detection."""
    # Content-based detection
    threshold: float = 30.0  # Higher = fewer detections
    min_scene_length_seconds: float = 2.0

    # Interval-based fallback
    interval_seconds: float = 5.0
    use_interval_fallback: bool = True

    # Output
    max_scenes: int = 500

class SceneDetector:
    """Detects scene boundaries using PySceneDetect."""

    def __init__(self, config: SceneDetectionConfig = None):
        self.config = config or SceneDetectionConfig()

    async def detect_scenes(self, video_path: Path) -> SceneDetectionResult:
        """
        Detect scene boundaries in a video.

        Uses content-aware detection (ContentDetector) to find cuts/fades,
        with interval-based fallback for videos with few natural scene changes.
        """
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector, ThresholdDetector

        try:
            video = open_video(str(video_path))
            scene_manager = SceneManager()

            # Add content detector for cuts/fades
            scene_manager.add_detector(ContentDetector(
                threshold=self.config.threshold,
                min_scene_len=int(video.frame_rate * self.config.min_scene_length_seconds)
            ))

            # Detect scenes
            scene_manager.detect_scenes(video)
            scene_list = scene_manager.get_scene_list()

            scenes = []
            for i, (start, end) in enumerate(scene_list):
                scenes.append(SceneBoundary(
                    timestamp_ms=int(start.get_seconds() * 1000),
                    frame_number=start.get_frames(),
                    scene_index=i,
                    detection_type="cut"
                ))

            # Add interval-based keyframes if too few scenes detected
            if self.config.use_interval_fallback:
                duration_seconds = video.duration.get_seconds()
                interval_ms = int(self.config.interval_seconds * 1000)

                existing_timestamps = {s.timestamp_ms for s in scenes}

                current_ms = 0
                interval_index = len(scenes)
                while current_ms < duration_seconds * 1000:
                    # Don't add if too close to existing scene boundary
                    if not any(abs(current_ms - t) < 1000 for t in existing_timestamps):
                        scenes.append(SceneBoundary(
                            timestamp_ms=current_ms,
                            frame_number=int(current_ms / 1000 * video.frame_rate),
                            scene_index=interval_index,
                            detection_type="interval",
                            confidence=0.5
                        ))
                        interval_index += 1
                    current_ms += interval_ms

            # Sort by timestamp and limit
            scenes.sort(key=lambda s: s.timestamp_ms)
            scenes = scenes[:self.config.max_scenes]

            # Re-index
            for i, scene in enumerate(scenes):
                scene.scene_index = i

            logger.info(f"Detected {len(scenes)} scene boundaries")

            return SceneDetectionResult(
                success=True,
                scenes=scenes,
                total_frames=video.duration.get_frames(),
                fps=video.frame_rate
            )

        except Exception as e:
            logger.error(f"Scene detection failed: {e}")
            return SceneDetectionResult(success=False, error=str(e))
```

### Keyframe Extractor

```python
# processors/video/keyframe_extractor.py
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class KeyframeConfig:
    output_format: str = "jpg"
    quality: int = 85  # JPEG quality
    max_width: int = 1280  # Resize for storage efficiency
    max_height: int = 720
    thumbnail_width: int = 320
    thumbnail_height: int = 180

@dataclass
class ExtractedKeyframe:
    timestamp_ms: int
    frame_index: int
    image_path: Path
    thumbnail_path: Path | None = None
    width: int = 0
    height: int = 0

@dataclass
class KeyframeExtractionResult:
    success: bool
    keyframes: list[ExtractedKeyframe] = field(default_factory=list)
    error: str | None = None

class KeyframeExtractor:
    """Extracts keyframe images from video at specified timestamps."""

    def __init__(self, config: KeyframeConfig = None):
        self.config = config or KeyframeConfig()

    async def extract_keyframes(
        self,
        video_path: Path,
        timestamps_ms: list[int],
        output_dir: Path,
        generate_thumbnails: bool = True
    ) -> KeyframeExtractionResult:
        """
        Extract keyframes at specified timestamps.

        Args:
            video_path: Source video file
            timestamps_ms: List of timestamps in milliseconds
            output_dir: Directory for output images
            generate_thumbnails: Also create smaller thumbnails

        Returns:
            KeyframeExtractionResult with paths to extracted images
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir = output_dir / "thumbnails" if generate_thumbnails else None
        if thumb_dir:
            thumb_dir.mkdir(exist_ok=True)

        keyframes = []
        errors = []

        # Extract in batches for efficiency
        batch_size = 50
        for i in range(0, len(timestamps_ms), batch_size):
            batch = timestamps_ms[i:i + batch_size]
            batch_results = await asyncio.gather(*[
                self._extract_single(
                    video_path,
                    ts,
                    idx,
                    output_dir,
                    thumb_dir
                )
                for idx, ts in enumerate(batch, start=i)
            ], return_exceptions=True)

            for result in batch_results:
                if isinstance(result, Exception):
                    errors.append(str(result))
                elif result:
                    keyframes.append(result)

        if errors:
            logger.warning(f"Keyframe extraction had {len(errors)} errors")

        return KeyframeExtractionResult(
            success=len(keyframes) > 0,
            keyframes=keyframes,
            error="; ".join(errors[:5]) if errors else None
        )

    async def _extract_single(
        self,
        video_path: Path,
        timestamp_ms: int,
        frame_index: int,
        output_dir: Path,
        thumb_dir: Path | None
    ) -> ExtractedKeyframe | None:
        """Extract a single keyframe."""
        timestamp_sec = timestamp_ms / 1000
        output_path = output_dir / f"{frame_index:05d}.{self.config.output_format}"

        # FFmpeg command to extract single frame with scaling
        cmd = [
            "ffmpeg",
            "-ss", str(timestamp_sec),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", f"scale='min({self.config.max_width},iw)':min'({self.config.max_height},ih)':force_original_aspect_ratio=decrease",
            "-q:v", str(int((100 - self.config.quality) / 100 * 31)),  # FFmpeg quality scale
            "-y",
            str(output_path)
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0 or not output_path.exists():
                logger.warning(f"Failed to extract frame at {timestamp_ms}ms")
                return None

            # Generate thumbnail
            thumb_path = None
            if thumb_dir:
                thumb_path = thumb_dir / f"{frame_index:05d}.{self.config.output_format}"
                await self._create_thumbnail(output_path, thumb_path)

            # Get dimensions
            from PIL import Image
            with Image.open(output_path) as img:
                width, height = img.size

            return ExtractedKeyframe(
                timestamp_ms=timestamp_ms,
                frame_index=frame_index,
                image_path=output_path,
                thumbnail_path=thumb_path,
                width=width,
                height=height
            )

        except Exception as e:
            logger.error(f"Error extracting frame at {timestamp_ms}ms: {e}")
            return None

    async def _create_thumbnail(self, source: Path, dest: Path):
        """Create thumbnail from extracted keyframe."""
        from PIL import Image

        with Image.open(source) as img:
            img.thumbnail((self.config.thumbnail_width, self.config.thumbnail_height))
            img.save(dest, quality=self.config.quality)

    async def extract_video_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        timestamp_ms: int = 0
    ) -> bool:
        """Extract a single thumbnail for video preview."""
        cmd = [
            "ffmpeg",
            "-ss", str(timestamp_ms / 1000),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", f"scale={self.config.thumbnail_width}:{self.config.thumbnail_height}:force_original_aspect_ratio=decrease",
            "-y",
            str(output_path)
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        return proc.returncode == 0 and output_path.exists()
```

### Keyframe Storage

```python
# processors/video/keyframe_storage.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

@dataclass
class KeyframeRecord:
    video_id: UUID
    frame_index: int
    timestamp_ms: int
    storage_path: str
    thumbnail_path: str | None
    width: int
    height: int
    detection_type: str

class KeyframeStorage:
    """Manages keyframe storage in MinIO and database."""

    def __init__(self, minio_client, session):
        self.minio = minio_client
        self.session = session

    async def store_keyframes(
        self,
        tenant_id: UUID,
        video_id: UUID,
        keyframes: list["ExtractedKeyframe"],
        scene_boundaries: list["SceneBoundary"]
    ) -> int:
        """Upload keyframes to MinIO and record in database."""
        # Create timestamp to detection_type mapping
        detection_types = {
            sb.timestamp_ms: sb.detection_type
            for sb in scene_boundaries
        }

        stored_count = 0
        for kf in keyframes:
            # Upload main image
            storage_path = f"videos/{tenant_id}/keyframes/{video_id}/{kf.frame_index:05d}.jpg"
            await self.minio.upload_file(kf.image_path, storage_path)

            # Upload thumbnail
            thumb_storage_path = None
            if kf.thumbnail_path:
                thumb_storage_path = f"videos/{tenant_id}/keyframes/{video_id}/thumbs/{kf.frame_index:05d}.jpg"
                await self.minio.upload_file(kf.thumbnail_path, thumb_storage_path)

            # Record in database
            record = KeyframeRecord(
                video_id=video_id,
                frame_index=kf.frame_index,
                timestamp_ms=kf.timestamp_ms,
                storage_path=storage_path,
                thumbnail_path=thumb_storage_path,
                width=kf.width,
                height=kf.height,
                detection_type=detection_types.get(kf.timestamp_ms, "interval")
            )
            await self._insert_record(record)
            stored_count += 1

        await self.session.commit()
        logger.info(f"Stored {stored_count} keyframes for video {video_id}")
        return stored_count

    async def _insert_record(self, record: KeyframeRecord):
        """Insert keyframe record into database."""
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(VideoKeyframe).values(
            video_id=record.video_id,
            frame_index=record.frame_index,
            timestamp_ms=record.timestamp_ms,
            storage_path=record.storage_path,
            thumbnail_path=record.thumbnail_path,
            width=record.width,
            height=record.height,
            detection_type=record.detection_type
        ).on_conflict_do_update(
            index_elements=["video_id", "frame_index"],
            set_={"storage_path": record.storage_path}
        )
        await self.session.execute(stmt)

    async def get_keyframe_url(
        self,
        tenant_id: UUID,
        video_id: UUID,
        frame_index: int,
        thumbnail: bool = False
    ) -> str | None:
        """Get presigned URL for a keyframe."""
        prefix = "thumbs/" if thumbnail else ""
        path = f"videos/{tenant_id}/keyframes/{video_id}/{prefix}{frame_index:05d}.jpg"
        return await self.minio.presign_get(path, expiry_hours=24)
```

### Database Schema

```sql
CREATE TABLE video_keyframes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id UUID NOT NULL REFERENCES source_videos(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    storage_path VARCHAR(1000) NOT NULL,
    thumbnail_path VARCHAR(1000),
    width INTEGER,
    height INTEGER,
    detection_type VARCHAR(50) NOT NULL,  -- 'cut', 'fade', 'interval'
    scene_description TEXT,  -- Populated by US-9.4
    ocr_text TEXT,  -- Populated by US-9.5
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(video_id, frame_index)
);

CREATE INDEX idx_video_keyframes_video ON video_keyframes(video_id);
CREATE INDEX idx_video_keyframes_timestamp ON video_keyframes(video_id, timestamp_ms);
```

### Pipeline Integration

```python
# In VideoProcessingPipeline

async def _run_scene_detection_stage(self) -> tuple[list[SceneBoundary], list[ExtractedKeyframe]]:
    """Detect scenes and extract keyframes."""
    await self._update_progress("extracting_scenes", 0)

    # Detect scene boundaries
    scene_result = await self.scene_detector.detect_scenes(self.video_path)
    if not scene_result.success:
        raise ProcessingError(f"Scene detection failed: {scene_result.error}")

    await self._update_progress("extracting_scenes", 50)

    # Extract keyframes at scene boundaries
    timestamps = [s.timestamp_ms for s in scene_result.scenes]
    keyframe_result = await self.keyframe_extractor.extract_keyframes(
        video_path=self.video_path,
        timestamps_ms=timestamps,
        output_dir=self.temp_dir / "keyframes"
    )

    if not keyframe_result.success:
        raise ProcessingError(f"Keyframe extraction failed: {keyframe_result.error}")

    # Store keyframes
    await self.keyframe_storage.store_keyframes(
        tenant_id=self.tenant_id,
        video_id=self.video_id,
        keyframes=keyframe_result.keyframes,
        scene_boundaries=scene_result.scenes
    )

    # Extract video thumbnail (first keyframe or 10% into video)
    thumb_timestamp = scene_result.scenes[0].timestamp_ms if scene_result.scenes else 0
    thumb_path = self.temp_dir / "thumbnail.jpg"
    if await self.keyframe_extractor.extract_video_thumbnail(
        self.video_path, thumb_path, thumb_timestamp
    ):
        thumb_storage = f"videos/{self.tenant_id}/thumbnails/{self.video_id}/thumb.jpg"
        await self.minio.upload_file(thumb_path, thumb_storage)
        await self.video_service.update_thumbnail(self.video_id, thumb_storage)

    await self._update_progress("extracting_scenes", 100)

    return scene_result.scenes, keyframe_result.keyframes
```

## Configuration

```python
class SceneDetectionConfig(BaseSettings):
    scene_threshold: float = 30.0
    scene_min_length_seconds: float = 2.0
    keyframe_interval_seconds: float = 5.0
    keyframe_max_width: int = 1280
    keyframe_quality: int = 85

    class Config:
        env_prefix = "SCENE_"
```

## Acceptance Criteria

- [ ] Detect scene boundaries using visual similarity thresholds
- [ ] Extract keyframes at scene changes
- [ ] Extract keyframes at fixed intervals (every 5 seconds) as fallback
- [ ] Group keyframes into logical segments (10-30 seconds)
- [ ] Store keyframe images in MinIO
- [ ] Generate thumbnail for each video chunk

## Testing Requirements

```python
class TestSceneDetector:
    @pytest.mark.asyncio
    async def test_detects_scene_cuts(self, video_with_cuts):
        detector = SceneDetector()
        result = await detector.detect_scenes(video_with_cuts)

        assert result.success
        assert len(result.scenes) >= 3  # Known number of cuts

    @pytest.mark.asyncio
    async def test_interval_fallback_for_static_video(self, static_video):
        detector = SceneDetector(SceneDetectionConfig(interval_seconds=5.0))
        result = await detector.detect_scenes(static_video)

        # Should have interval-based keyframes
        interval_scenes = [s for s in result.scenes if s.detection_type == "interval"]
        assert len(interval_scenes) > 0

class TestKeyframeExtractor:
    @pytest.mark.asyncio
    async def test_extracts_keyframes(self, sample_video, tmp_path):
        extractor = KeyframeExtractor()
        result = await extractor.extract_keyframes(
            sample_video,
            timestamps_ms=[0, 5000, 10000],
            output_dir=tmp_path
        )

        assert result.success
        assert len(result.keyframes) == 3
        assert all(kf.image_path.exists() for kf in result.keyframes)

    @pytest.mark.asyncio
    async def test_generates_thumbnails(self, sample_video, tmp_path):
        extractor = KeyframeExtractor()
        result = await extractor.extract_keyframes(
            sample_video,
            timestamps_ms=[0],
            output_dir=tmp_path,
            generate_thumbnails=True
        )

        assert result.keyframes[0].thumbnail_path.exists()
```

## Dependencies

```
scenedetect>=0.6.0
Pillow>=10.0.0
```

## Definition of Done

- [ ] Scene detection finding cuts/fades accurately
- [ ] Interval-based fallback working for static videos
- [ ] Keyframes extracted at all scene boundaries
- [ ] Thumbnails generated for all keyframes
- [ ] Video thumbnail extracted
- [ ] All images stored in MinIO
- [ ] Database records created
- [ ] >90% test coverage
