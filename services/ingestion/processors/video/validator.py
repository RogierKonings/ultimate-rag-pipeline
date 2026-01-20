"""
Video validation service.

This module provides video validation using FFprobe to verify
video format, duration, resolution, and other properties.
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from processors.video.exceptions import VideoValidationError
from processors.video.metadata import ValidationConfig, VideoMetadata

logger = logging.getLogger(__name__)


class VideoValidator:
    """Validates video files using FFprobe.

    This class validates video files by:
    - Checking file existence and readability
    - Extracting metadata using FFprobe
    - Validating duration, resolution, codec, and file size
    - Computing content hash for deduplication

    Example:
        validator = VideoValidator()
        metadata = await validator.validate("/path/to/video.mp4")
    """

    def __init__(
        self,
        config: ValidationConfig | None = None,
        ffprobe_path: str = "ffprobe",
    ):
        """Initialize the VideoValidator.

        Args:
            config: Validation configuration. If None, uses default config.
            ffprobe_path: Path to ffprobe executable.
        """
        self.config = config or ValidationConfig.from_env()
        self.ffprobe_path = ffprobe_path

    async def validate(self, file_path: str | Path) -> VideoMetadata:
        """Validate a video file and extract metadata.

        Args:
            file_path: Path to the video file.

        Returns:
            VideoMetadata with extracted properties.

        Raises:
            VideoValidationError: If validation fails.
        """
        file_path = Path(file_path)

        # Check file exists
        if not file_path.exists():
            raise VideoValidationError(
                f"Video file not found: {file_path}",
                details={"file_path": str(file_path)},
            )

        # Check file is readable
        if not os.access(file_path, os.R_OK):
            raise VideoValidationError(
                f"Video file is not readable: {file_path}",
                details={"file_path": str(file_path)},
            )

        # Get file size
        file_size = file_path.stat().st_size
        if file_size > self.config.max_file_size_bytes:
            raise VideoValidationError(
                f"Video file too large: {file_size / (1024 * 1024):.1f}MB "
                f"(max: {self.config.max_file_size_bytes / (1024 * 1024):.1f}MB)",
                details={
                    "file_size_bytes": file_size,
                    "max_size_bytes": self.config.max_file_size_bytes,
                },
            )

        # Extract metadata using FFprobe
        metadata = await self._extract_metadata(file_path, file_size)

        # Validate metadata
        self._validate_metadata(metadata)

        return metadata

    async def _extract_metadata(self, file_path: Path, file_size: int) -> VideoMetadata:
        """Extract video metadata using FFprobe.

        Args:
            file_path: Path to the video file.
            file_size: Size of the file in bytes.

        Returns:
            VideoMetadata with extracted properties.

        Raises:
            VideoValidationError: If FFprobe fails or video is invalid.
        """
        cmd = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        try:
            # Run FFprobe asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                raise VideoValidationError(
                    f"FFprobe failed: {error_msg}",
                    details={"file_path": str(file_path), "error": error_msg},
                )

            # Parse FFprobe output
            probe_data = json.loads(stdout.decode())

        except TimeoutError:
            raise VideoValidationError(
                "FFprobe timed out",
                details={"file_path": str(file_path)},
            ) from None
        except json.JSONDecodeError as e:
            raise VideoValidationError(
                f"Failed to parse FFprobe output: {e}",
                details={"file_path": str(file_path)},
            ) from None
        except FileNotFoundError:
            raise VideoValidationError(
                f"FFprobe not found at: {self.ffprobe_path}. Please ensure FFmpeg is installed.",
            ) from None

        # Extract video stream info
        video_stream = None
        audio_stream = None

        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream

        if video_stream is None:
            raise VideoValidationError(
                "No video stream found in file",
                details={"file_path": str(file_path)},
            )

        # Parse format info
        format_info = probe_data.get("format", {})

        # Extract duration
        duration = float(format_info.get("duration", 0))
        if duration == 0:
            # Try getting duration from video stream
            duration = float(video_stream.get("duration", 0))

        # Extract FPS
        fps = self._parse_fps(video_stream.get("r_frame_rate", "0/1"))
        if fps == 0:
            fps = self._parse_fps(video_stream.get("avg_frame_rate", "0/1"))

        # Extract creation time
        creation_time = None
        tags = format_info.get("tags", {})
        if "creation_time" in tags:
            try:
                creation_time = datetime.fromisoformat(tags["creation_time"].replace("Z", "+00:00"))
            except ValueError:
                pass

        # Compute content hash (first 100MB + last 100MB for large files)
        content_hash = await self._compute_content_hash(file_path, file_size)

        return VideoMetadata(
            filename=file_path.name,
            file_path=file_path,
            file_size_bytes=file_size,
            content_hash=content_hash,
            duration_seconds=duration,
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            fps=fps,
            codec=video_stream.get("codec_name", "unknown"),
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            has_audio=audio_stream is not None,
            bitrate=int(format_info.get("bit_rate", 0)) or None,
            format_name=format_info.get("format_name", "").split(",")[0],
            creation_time=creation_time,
        )

    def _parse_fps(self, fps_str: str) -> float:
        """Parse FPS from FFprobe format (e.g., '30000/1001')."""
        try:
            if "/" in fps_str:
                num, den = fps_str.split("/")
                if int(den) == 0:
                    return 0.0
                return float(num) / float(den)
            return float(fps_str)
        except (ValueError, ZeroDivisionError):
            return 0.0

    async def _compute_content_hash(self, file_path: Path, file_size: int) -> str:
        """Compute SHA-256 hash of video content.

        For large files, hashes first and last chunks for performance.

        Args:
            file_path: Path to the video file.
            file_size: Size of the file in bytes.

        Returns:
            SHA-256 hash as hex string.
        """
        chunk_size = 100 * 1024 * 1024  # 100MB chunks

        def _compute_hash():
            hasher = hashlib.sha256()

            with file_path.open("rb") as f:
                if file_size <= chunk_size * 2:
                    # Small file: hash entire content
                    while chunk := f.read(8192):
                        hasher.update(chunk)
                else:
                    # Large file: hash first and last chunks + size
                    # First chunk
                    hasher.update(f.read(chunk_size))

                    # Last chunk
                    f.seek(-chunk_size, 2)
                    hasher.update(f.read(chunk_size))

                    # Include file size for uniqueness
                    hasher.update(str(file_size).encode())

            return hasher.hexdigest()

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _compute_hash)

    def _validate_metadata(self, metadata: VideoMetadata) -> None:
        """Validate extracted metadata against configuration.

        Args:
            metadata: Extracted video metadata.

        Raises:
            VideoValidationError: If validation fails.
        """
        errors = []

        # Validate duration
        if metadata.duration_seconds < self.config.min_duration_seconds:
            errors.append(
                f"Video too short: {metadata.duration_seconds:.1f}s "
                f"(min: {self.config.min_duration_seconds}s)"
            )

        if metadata.duration_seconds > self.config.max_duration_seconds:
            errors.append(
                f"Video too long: {metadata.duration_seconds:.1f}s "
                f"(max: {self.config.max_duration_seconds}s)"
            )

        # Validate resolution
        if metadata.width < self.config.min_width:
            errors.append(
                f"Video width too small: {metadata.width}px (min: {self.config.min_width}px)"
            )

        if metadata.height < self.config.min_height:
            errors.append(
                f"Video height too small: {metadata.height}px (min: {self.config.min_height}px)"
            )

        if metadata.width > self.config.max_width:
            errors.append(
                f"Video width too large: {metadata.width}px (max: {self.config.max_width}px)"
            )

        if metadata.height > self.config.max_height:
            errors.append(
                f"Video height too large: {metadata.height}px (max: {self.config.max_height}px)"
            )

        # Validate codec
        codec_lower = metadata.codec.lower()
        if codec_lower not in [c.lower() for c in self.config.allowed_codecs]:
            errors.append(
                f"Unsupported video codec: {metadata.codec}. "
                f"Allowed: {', '.join(self.config.allowed_codecs)}"
            )

        # Validate format
        if metadata.format_name:
            format_lower = metadata.format_name.lower()
            if format_lower not in [f.lower() for f in self.config.allowed_formats]:
                errors.append(
                    f"Unsupported video format: {metadata.format_name}. "
                    f"Allowed: {', '.join(self.config.allowed_formats)}"
                )

        # Validate FPS
        if metadata.fps <= 0:
            errors.append("Invalid frame rate: could not determine FPS")

        if errors:
            raise VideoValidationError(
                "; ".join(errors),
                details={
                    "filename": metadata.filename,
                    "duration": metadata.duration_seconds,
                    "resolution": metadata.resolution,
                    "codec": metadata.codec,
                    "format": metadata.format_name,
                    "fps": metadata.fps,
                },
            )

        logger.info(
            "Video validated successfully: %s (%s, %.1fs, %s, %.1f fps)",
            metadata.filename,
            metadata.resolution,
            metadata.duration_seconds,
            metadata.codec,
            metadata.fps,
        )

    async def quick_validate(self, file_path: str | Path) -> bool:
        """Perform quick validation without computing hash.

        Useful for pre-validation before upload.

        Args:
            file_path: Path to the video file.

        Returns:
            True if validation passes, False otherwise.
        """
        try:
            file_path = Path(file_path)

            # Quick file checks
            if not file_path.exists():
                return False

            file_size = file_path.stat().st_size
            if file_size > self.config.max_file_size_bytes:
                return False

            # Check file extension
            extension = file_path.suffix.lower().lstrip(".")
            return extension in self.config.allowed_formats

        except Exception:
            return False
