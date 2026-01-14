"""
Video metadata dataclass.

This module defines the VideoMetadata dataclass for storing
extracted video properties.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class VideoMetadata:
    """Video metadata extracted from a video file.

    Contains all technical information about a video file
    extracted using FFprobe.

    Attributes:
        filename: Original filename of the video.
        file_path: Local path to the video file.
        file_size_bytes: Size of the video file in bytes.
        content_hash: SHA-256 hash of the video content.
        duration_seconds: Duration of the video in seconds.
        width: Video width in pixels.
        height: Video height in pixels.
        fps: Frames per second.
        codec: Video codec (e.g., h264, hevc).
        audio_codec: Audio codec (e.g., aac, mp3) or None if no audio.
        has_audio: Whether the video has an audio track.
        bitrate: Video bitrate in bits per second.
        format_name: Container format name (e.g., mp4, mkv).
        creation_time: Original creation time from metadata.
        extracted_at: Timestamp when metadata was extracted.
    """

    filename: str
    file_path: Path
    file_size_bytes: int
    content_hash: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: str | None = None
    has_audio: bool = False
    bitrate: int | None = None
    format_name: str | None = None
    creation_time: datetime | None = None
    extracted_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def resolution(self) -> str:
        """Return resolution as a string (e.g., '1920x1080')."""
        return f"{self.width}x{self.height}"

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio (width/height)."""
        if self.height == 0:
            return 0.0
        return self.width / self.height

    @property
    def is_portrait(self) -> bool:
        """Check if video is in portrait orientation."""
        return self.height > self.width

    @property
    def is_landscape(self) -> bool:
        """Check if video is in landscape orientation."""
        return self.width > self.height

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        return int(self.duration_seconds * 1000)

    @property
    def file_size_mb(self) -> float:
        """Return file size in megabytes."""
        return self.file_size_bytes / (1024 * 1024)

    def to_dict(self) -> dict:
        """Convert metadata to a dictionary for serialization."""
        return {
            "filename": self.filename,
            "file_path": str(self.file_path),
            "file_size_bytes": self.file_size_bytes,
            "file_size_mb": round(self.file_size_mb, 2),
            "content_hash": self.content_hash,
            "duration_seconds": self.duration_seconds,
            "duration_ms": self.duration_ms,
            "width": self.width,
            "height": self.height,
            "resolution": self.resolution,
            "fps": self.fps,
            "codec": self.codec,
            "audio_codec": self.audio_codec,
            "has_audio": self.has_audio,
            "bitrate": self.bitrate,
            "format_name": self.format_name,
            "creation_time": self.creation_time.isoformat() if self.creation_time else None,
            "extracted_at": self.extracted_at.isoformat(),
        }


@dataclass
class ValidationConfig:
    """Configuration for video validation.

    Attributes:
        min_duration_seconds: Minimum allowed video duration.
        max_duration_seconds: Maximum allowed video duration.
        max_file_size_bytes: Maximum allowed file size.
        allowed_codecs: List of allowed video codecs.
        allowed_formats: List of allowed container formats.
        min_width: Minimum allowed video width.
        min_height: Minimum allowed video height.
        max_width: Maximum allowed video width.
        max_height: Maximum allowed video height.
    """

    min_duration_seconds: float = 10.0
    max_duration_seconds: float = 3600.0  # 1 hour
    max_file_size_bytes: int = 5 * 1024 * 1024 * 1024  # 5 GB
    allowed_codecs: list[str] = field(
        default_factory=lambda: [
            "h264",
            "hevc",
            "h265",
            "vp8",
            "vp9",
            "av1",
            "mpeg4",
            "mpeg2video",
            "prores",
        ]
    )
    allowed_formats: list[str] = field(
        default_factory=lambda: [
            "mp4",
            "mov",
            "avi",
            "mkv",
            "webm",
            "m4v",
            "mts",
            "m2ts",
        ]
    )
    min_width: int = 320
    min_height: int = 180
    max_width: int = 7680  # 8K
    max_height: int = 4320  # 8K

    @classmethod
    def from_env(cls) -> "ValidationConfig":
        """Create ValidationConfig from environment variables."""
        import os

        return cls(
            min_duration_seconds=float(os.getenv("VIDEO_MIN_DURATION_SECONDS", "10")),
            max_duration_seconds=float(os.getenv("VIDEO_MAX_DURATION_SECONDS", "3600")),
            max_file_size_bytes=int(os.getenv("VIDEO_MAX_FILE_SIZE_MB", "5000")) * 1024 * 1024,
        )
