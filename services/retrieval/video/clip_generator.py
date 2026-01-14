"""Video clip generator service.

This module provides the ClipGenerator class for extracting video
clips from source videos using FFmpeg.
"""

import asyncio
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class ClipConfig:
    """Configuration for clip generation.

    Attributes:
        padding_seconds: Seconds to add before/after clip.
        max_duration_seconds: Maximum clip duration.
        output_format: Output video format.
        video_codec: Video codec for re-encoding.
        audio_codec: Audio codec for re-encoding.
        crf: Constant Rate Factor for quality.
        preset: FFmpeg preset (ultrafast, fast, medium).
        use_stream_copy: Try stream copy first (faster).
        timeout_seconds: Maximum time for clip generation.
    """

    padding_seconds: float = 2.0
    max_duration_seconds: float = 120.0
    output_format: str = "mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 23
    preset: str = "fast"
    use_stream_copy: bool = True
    timeout_seconds: float = 300.0


@dataclass
class ClipResult:
    """Result of clip generation.

    Attributes:
        success: Whether generation succeeded.
        output_path: Path to generated clip.
        start_ms: Actual start time (with padding).
        end_ms: Actual end time (with padding).
        duration_ms: Clip duration.
        file_size_bytes: Size of generated clip.
        method: Generation method used (stream_copy or reencode).
        error: Error message if failed.
    """

    success: bool
    output_path: Path | None = None
    start_ms: int = 0
    end_ms: int = 0
    duration_ms: int = 0
    file_size_bytes: int = 0
    method: str = ""
    error: str | None = None


class ClipGenerator:
    """Generates video clips using FFmpeg.

    Supports two modes:
    - Stream copy: Fast, uses original encoding (may have keyframe issues)
    - Re-encode: Slower but precise cuts

    Example:
        generator = ClipGenerator()
        result = await generator.generate_clip(
            source_path="/path/to/video.mp4",
            start_ms=30000,
            end_ms=60000,
        )
    """

    def __init__(self, config: ClipConfig | None = None):
        """Initialize clip generator.

        Args:
            config: Clip generation configuration.
        """
        self.config = config or ClipConfig()
        self._verify_ffmpeg()

    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg is installed."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],  # noqa: S603, S607
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("FFmpeg not available: %s", e)

    async def generate_clip(
        self,
        source_path: str | Path,
        start_ms: int,
        end_ms: int,
        output_path: str | Path | None = None,
        video_id: UUID | None = None,
    ) -> ClipResult:
        """Generate a video clip.

        Args:
            source_path: Path to source video file.
            start_ms: Start time in milliseconds.
            end_ms: End time in milliseconds.
            output_path: Optional output path (temp file if not provided).
            video_id: Optional video ID for logging.

        Returns:
            ClipResult with generation details.
        """
        source_path = Path(source_path)

        if not source_path.exists():
            return ClipResult(
                success=False,
                error=f"Source video not found: {source_path}",
            )

        # Apply padding
        padded_start = max(0, start_ms - int(self.config.padding_seconds * 1000))
        padded_end = end_ms + int(self.config.padding_seconds * 1000)

        # Enforce max duration
        duration_ms = padded_end - padded_start
        max_duration_ms = int(self.config.max_duration_seconds * 1000)
        if duration_ms > max_duration_ms:
            padded_end = padded_start + max_duration_ms
            duration_ms = max_duration_ms
            logger.info(
                "Clip duration capped to %ds for video_id=%s",
                self.config.max_duration_seconds,
                video_id,
            )

        # Create output path if not provided
        if output_path is None:
            # Use NamedTemporaryFile to create a secure temp file
            temp_dir = tempfile.gettempdir()
            temp_name = f"clip_{video_id}_{padded_start}_{padded_end}.{self.config.output_format}"
            output_path = Path(temp_dir) / temp_name
        else:
            output_path = Path(output_path)

        logger.info(
            "Generating clip: video_id=%s, %dms-%dms (duration=%dms)",
            video_id,
            padded_start,
            padded_end,
            duration_ms,
        )

        # Try stream copy first if enabled
        if self.config.use_stream_copy:
            result = await self._generate_stream_copy(
                source_path=source_path,
                start_ms=padded_start,
                end_ms=padded_end,
                output_path=output_path,
            )
            if result.success:
                return result
            logger.info("Stream copy failed, falling back to re-encode")

        # Fall back to re-encode
        return await self._generate_reencode(
            source_path=source_path,
            start_ms=padded_start,
            end_ms=padded_end,
            output_path=output_path,
        )

    async def _generate_stream_copy(
        self,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Path,
    ) -> ClipResult:
        """Generate clip using stream copy (fast, no re-encoding).

        Args:
            source_path: Source video path.
            start_ms: Start time in ms.
            end_ms: End time in ms.
            output_path: Output path.

        Returns:
            ClipResult.
        """
        start_seconds = start_ms / 1000.0
        duration_seconds = (end_ms - start_ms) / 1000.0

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_seconds),
            "-i", str(source_path),
            "-t", str(duration_seconds),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]

        return await self._run_ffmpeg(
            cmd=cmd,
            output_path=output_path,
            start_ms=start_ms,
            end_ms=end_ms,
            method="stream_copy",
        )

    async def _generate_reencode(
        self,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Path,
    ) -> ClipResult:
        """Generate clip with re-encoding (precise cuts).

        Args:
            source_path: Source video path.
            start_ms: Start time in ms.
            end_ms: End time in ms.
            output_path: Output path.

        Returns:
            ClipResult.
        """
        start_seconds = start_ms / 1000.0
        duration_seconds = (end_ms - start_ms) / 1000.0

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_seconds),
            "-i", str(source_path),
            "-t", str(duration_seconds),
            "-c:v", self.config.video_codec,
            "-crf", str(self.config.crf),
            "-preset", self.config.preset,
            "-c:a", self.config.audio_codec,
            "-movflags", "+faststart",
            str(output_path),
        ]

        return await self._run_ffmpeg(
            cmd=cmd,
            output_path=output_path,
            start_ms=start_ms,
            end_ms=end_ms,
            method="reencode",
        )

    async def _run_ffmpeg(
        self,
        cmd: list[str],
        output_path: Path,
        start_ms: int,
        end_ms: int,
        method: str,
    ) -> ClipResult:
        """Run FFmpeg command asynchronously.

        Args:
            cmd: FFmpeg command arguments.
            output_path: Expected output path.
            start_ms: Clip start time.
            end_ms: Clip end time.
            method: Generation method name.

        Returns:
            ClipResult.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.timeout_seconds,
            )

            if process.returncode != 0:
                error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
                return ClipResult(
                    success=False,
                    error=f"FFmpeg failed ({method}): {error_msg}",
                    method=method,
                )

            # Verify output exists
            if not output_path.exists():
                return ClipResult(
                    success=False,
                    error="Output file not created",
                    method=method,
                )

            file_size = output_path.stat().st_size
            if file_size == 0:
                return ClipResult(
                    success=False,
                    error="Output file is empty",
                    method=method,
                )

            return ClipResult(
                success=True,
                output_path=output_path,
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=end_ms - start_ms,
                file_size_bytes=file_size,
                method=method,
            )

        except TimeoutError:
            return ClipResult(
                success=False,
                error=f"Clip generation timed out after {self.config.timeout_seconds}s",
                method=method,
            )
        except Exception as e:
            return ClipResult(
                success=False,
                error=f"Clip generation failed: {e}",
                method=method,
            )

    def cleanup_temp_file(self, path: Path | None) -> None:
        """Remove temporary clip file.

        Args:
            path: Path to remove.
        """
        if path and path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning("Failed to cleanup temp file %s: %s", path, e)
