"""Scene detection service for video processing.

This module provides the SceneDetector class that detects scene boundaries
in videos using PySceneDetect.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from processors.video.exceptions import SceneDetectionError

logger = logging.getLogger(__name__)


@dataclass
class SceneDetectionConfig:
    """Configuration for scene detection.

    Attributes:
        threshold: Content detector threshold (higher = less sensitive).
        min_scene_len_frames: Minimum scene length in frames.
        fallback_interval_seconds: Interval for static video fallback.
        adaptive_threshold: Use adaptive threshold for varying content.
        luma_only: Only use luma channel for detection.
    """

    threshold: float = 27.0
    min_scene_len_frames: int = 15
    fallback_interval_seconds: float = 5.0
    adaptive_threshold: bool = False
    luma_only: bool = False


@dataclass
class SceneBoundary:
    """A detected scene boundary.

    Attributes:
        scene_index: Scene number (0-indexed).
        start_frame: Start frame number.
        end_frame: End frame number.
        start_seconds: Start time in seconds.
        end_seconds: End time in seconds.
        duration_seconds: Scene duration.
        is_detected: True if detected by algorithm, False if fallback.
    """

    scene_index: int
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    is_detected: bool = True

    @property
    def start_ms(self) -> int:
        """Get start time in milliseconds."""
        return int(self.start_seconds * 1000)

    @property
    def end_ms(self) -> int:
        """Get end time in milliseconds."""
        return int(self.end_seconds * 1000)

    @property
    def mid_seconds(self) -> float:
        """Get midpoint time in seconds."""
        return (self.start_seconds + self.end_seconds) / 2

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "scene_index": self.scene_index,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_seconds": self.duration_seconds,
            "is_detected": self.is_detected,
        }


@dataclass
class SceneDetectionResult:
    """Result of scene detection.

    Attributes:
        scenes: List of detected scene boundaries.
        total_frames: Total frames in video.
        fps: Video frame rate.
        duration_seconds: Video duration.
        detection_method: Method used (content, threshold, fallback).
    """

    scenes: list[SceneBoundary]
    total_frames: int
    fps: float
    duration_seconds: float
    detection_method: str = "content"
    metadata: dict = field(default_factory=dict)

    @property
    def scene_count(self) -> int:
        """Get number of scenes detected."""
        return len(self.scenes)

    def get_scene_at_time(self, seconds: float) -> SceneBoundary | None:
        """Get the scene containing a specific timestamp.

        Args:
            seconds: Time in seconds.

        Returns:
            SceneBoundary or None if not found.
        """
        for scene in self.scenes:
            if scene.start_seconds <= seconds <= scene.end_seconds:
                return scene
        return None


class SceneDetector:
    """Detects scene boundaries in videos.

    Uses PySceneDetect's ContentDetector for cut/fade detection with
    fallback to interval-based detection for static videos.

    Example:
        detector = SceneDetector(
            config=SceneDetectionConfig(threshold=27.0)
        )
        result = await detector.detect("/path/to/video.mp4")
        for scene in result.scenes:
            print(f"Scene {scene.scene_index}: {scene.start_seconds:.1f}s - {scene.end_seconds:.1f}s")
    """

    def __init__(self, config: SceneDetectionConfig | None = None):
        """Initialize scene detector.

        Args:
            config: Detection configuration.
        """
        self.config = config or SceneDetectionConfig()

    async def detect(
        self,
        video_path: str | Path,
    ) -> SceneDetectionResult:
        """Detect scene boundaries in a video.

        Args:
            video_path: Path to the video file.

        Returns:
            SceneDetectionResult with detected scenes.

        Raises:
            SceneDetectionError: If detection fails.
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise SceneDetectionError(f"Video file not found: {video_path}")

        logger.info(
            "Detecting scenes: video=%s, threshold=%.1f",
            video_path.name,
            self.config.threshold,
        )

        try:
            # Import PySceneDetect
            from scenedetect import ContentDetector, SceneManager, open_video

            # Open video
            video = open_video(str(video_path))
            fps = video.frame_rate
            total_frames = video.duration.get_frames()
            duration_seconds = video.duration.get_seconds()

            # Create scene manager with content detector
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=self.config.threshold,
                    min_scene_len=self.config.min_scene_len_frames,
                    luma_only=self.config.luma_only,
                )
            )

            # Detect scenes
            scene_manager.detect_scenes(video)
            scene_list = scene_manager.get_scene_list()

            # Convert to our format
            scenes = []
            for i, (start_time, end_time) in enumerate(scene_list):
                scenes.append(
                    SceneBoundary(
                        scene_index=i,
                        start_frame=start_time.get_frames(),
                        end_frame=end_time.get_frames(),
                        start_seconds=start_time.get_seconds(),
                        end_seconds=end_time.get_seconds(),
                        duration_seconds=end_time.get_seconds() - start_time.get_seconds(),
                        is_detected=True,
                    )
                )

            # If no scenes detected or only one scene, use fallback
            if len(scenes) <= 1:
                logger.info(
                    "Few scenes detected (%d), using interval fallback",
                    len(scenes),
                )
                scenes = self._generate_fallback_scenes(
                    duration_seconds=duration_seconds,
                    fps=fps,
                    total_frames=total_frames,
                )
                detection_method = "fallback"
            else:
                detection_method = "content"

            logger.info(
                "Scene detection complete: %d scenes, method=%s",
                len(scenes),
                detection_method,
            )

            return SceneDetectionResult(
                scenes=scenes,
                total_frames=total_frames,
                fps=fps,
                duration_seconds=duration_seconds,
                detection_method=detection_method,
                metadata={
                    "threshold": self.config.threshold,
                    "min_scene_len_frames": self.config.min_scene_len_frames,
                },
            )

        except ImportError as e:
            raise SceneDetectionError(
                "PySceneDetect not installed. Install with: pip install scenedetect[opencv]"
            ) from e
        except Exception as e:
            raise SceneDetectionError(f"Scene detection failed: {e}") from e

    def _generate_fallback_scenes(
        self,
        duration_seconds: float,
        fps: float,
        total_frames: int,
    ) -> list[SceneBoundary]:
        """Generate fallback scenes at regular intervals.

        Args:
            duration_seconds: Video duration.
            fps: Frame rate.
            total_frames: Total frames.

        Returns:
            List of SceneBoundary at regular intervals.
        """
        interval = self.config.fallback_interval_seconds
        scenes = []
        scene_index = 0
        start_seconds = 0.0

        while start_seconds < duration_seconds:
            end_seconds = min(start_seconds + interval, duration_seconds)
            start_frame = int(start_seconds * fps)
            end_frame = min(int(end_seconds * fps), total_frames)

            scenes.append(
                SceneBoundary(
                    scene_index=scene_index,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    duration_seconds=end_seconds - start_seconds,
                    is_detected=False,
                )
            )

            scene_index += 1
            start_seconds = end_seconds

        return scenes

    async def get_keyframe_timestamps(
        self,
        result: SceneDetectionResult,
        max_interval_seconds: float | None = None,
    ) -> list[float]:
        """Get optimal timestamps for keyframe extraction.

        Extracts a keyframe at each scene boundary, plus additional
        keyframes for long scenes.

        Args:
            result: Scene detection result.
            max_interval_seconds: Max interval between keyframes.

        Returns:
            List of timestamps in seconds.
        """
        max_interval = max_interval_seconds or self.config.fallback_interval_seconds
        timestamps = []

        for scene in result.scenes:
            # Add timestamp at start of scene
            timestamps.append(scene.start_seconds)

            # Add additional timestamps for long scenes
            scene_duration = scene.duration_seconds
            if scene_duration > max_interval:
                num_extra = int(scene_duration / max_interval)
                for i in range(1, num_extra):
                    extra_time = scene.start_seconds + (i * max_interval)
                    if extra_time < scene.end_seconds:
                        timestamps.append(extra_time)

        # Remove duplicates and sort
        timestamps = sorted(set(timestamps))

        logger.info(
            "Generated %d keyframe timestamps from %d scenes",
            len(timestamps),
            len(result.scenes),
        )

        return timestamps
