"""Audio extraction service for video processing.

This module provides the AudioExtractor class that extracts audio tracks
from video files using FFmpeg.
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from processors.video.exceptions import AudioExtractionError
from processors.video.storage import VideoStorage

logger = logging.getLogger(__name__)


@dataclass
class AudioExtractionConfig:
    """Configuration for audio extraction.

    Attributes:
        sample_rate: Audio sample rate in Hz.
        channels: Number of audio channels (1=mono, 2=stereo).
        format: Output audio format (wav, mp3, flac).
        codec: Audio codec to use.
        bitrate: Audio bitrate for lossy formats.
        ffmpeg_path: Path to ffmpeg executable.
        timeout_seconds: Timeout for ffmpeg command.
    """

    sample_rate: int = 16000  # 16kHz is optimal for Whisper
    channels: int = 1  # Mono for speech recognition
    format: str = "wav"
    codec: str = "pcm_s16le"  # 16-bit PCM for WAV
    bitrate: str | None = None  # Only used for lossy formats
    ffmpeg_path: str = "ffmpeg"
    timeout_seconds: float = 600.0  # 10 minutes


@dataclass
class AudioExtractionResult:
    """Result of audio extraction.

    Attributes:
        audio_path: Path to the extracted audio file.
        duration_seconds: Duration of the audio in seconds.
        sample_rate: Sample rate of the extracted audio.
        channels: Number of channels in the extracted audio.
        file_size_bytes: Size of the audio file.
        has_audio: Whether the video had an audio track.
    """

    audio_path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    file_size_bytes: int
    has_audio: bool = True
    metadata: dict = field(default_factory=dict)


class AudioExtractor:
    """Extracts audio tracks from video files.

    Uses FFmpeg to extract and convert audio from video files to a format
    suitable for speech recognition (16kHz mono WAV by default).

    Example:
        extractor = AudioExtractor()
        result = await extractor.extract(
            video_path="/path/to/video.mp4",
            output_path="/path/to/audio.wav",
        )
    """

    def __init__(
        self,
        config: AudioExtractionConfig | None = None,
        storage: VideoStorage | None = None,
    ):
        """Initialize the audio extractor.

        Args:
            config: Audio extraction configuration.
            storage: Video storage service for uploading extracted audio.
        """
        self.config = config or AudioExtractionConfig()
        self.storage = storage

    async def extract(
        self,
        video_path: str | Path,
        output_path: str | Path | None = None,
    ) -> AudioExtractionResult:
        """Extract audio from a video file.

        Args:
            video_path: Path to the video file.
            output_path: Optional path for the output audio file.
                        If not provided, creates a temp file.

        Returns:
            AudioExtractionResult with extraction details.

        Raises:
            AudioExtractionError: If audio extraction fails.
        """
        video_path = Path(video_path)

        if not video_path.exists():
            raise AudioExtractionError(f"Video file not found: {video_path}")

        # Check if video has audio stream
        has_audio = await self._has_audio_stream(video_path)
        if not has_audio:
            logger.warning("Video has no audio stream: %s", video_path)
            raise AudioExtractionError("Video has no audio stream")

        # Determine output path
        if output_path is None:
            temp_dir = tempfile.mkdtemp(prefix="audio_")
            output_path = Path(temp_dir) / f"audio.{self.config.format}"
        else:
            output_path = Path(output_path)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build FFmpeg command
        cmd = self._build_extraction_command(video_path, output_path)

        logger.info(
            "Extracting audio: video=%s, output=%s",
            video_path.name,
            output_path.name,
        )

        try:
            # Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError as e:
                process.kill()
                await process.wait()
                raise AudioExtractionError(
                    f"Audio extraction timed out after {self.config.timeout_seconds}s"
                ) from e

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                raise AudioExtractionError(f"FFmpeg failed: {error_msg}")

            # Verify output exists and get metadata
            if not output_path.exists():
                raise AudioExtractionError("Output audio file was not created")

            # Get audio metadata
            metadata = await self._get_audio_metadata(output_path)

            logger.info(
                "Audio extracted successfully: duration=%.1fs, size=%d bytes",
                metadata.get("duration_seconds", 0),
                output_path.stat().st_size,
            )

            return AudioExtractionResult(
                audio_path=output_path,
                duration_seconds=metadata.get("duration_seconds", 0.0),
                sample_rate=metadata.get("sample_rate", self.config.sample_rate),
                channels=metadata.get("channels", self.config.channels),
                file_size_bytes=output_path.stat().st_size,
                has_audio=True,
                metadata=metadata,
            )

        except AudioExtractionError:
            raise
        except Exception as e:
            raise AudioExtractionError(f"Audio extraction failed: {e}") from e

    async def extract_and_upload(
        self,
        video_path: str | Path,
        tenant_id: UUID,
        video_id: UUID,
    ) -> AudioExtractionResult:
        """Extract audio and upload to storage.

        Args:
            video_path: Path to the video file.
            tenant_id: Tenant identifier.
            video_id: Video identifier.

        Returns:
            AudioExtractionResult with storage path.

        Raises:
            AudioExtractionError: If extraction or upload fails.
        """
        if self.storage is None:
            raise AudioExtractionError("Storage service not configured")

        # Extract to temp file
        result = await self.extract(video_path)

        try:
            # Upload to storage
            storage_path = await self.storage.upload_audio(
                file_path=result.audio_path,
                tenant_id=tenant_id,
                video_id=video_id,
            )

            # Update result with storage info
            result.metadata["storage_path"] = storage_path

            logger.info(
                "Audio uploaded: video_id=%s, path=%s",
                video_id,
                storage_path,
            )

            return result

        finally:
            # Clean up temp file
            if result.audio_path.exists():
                result.audio_path.unlink()
                # Remove temp directory if empty
                temp_dir = result.audio_path.parent
                if temp_dir.exists() and not any(temp_dir.iterdir()):
                    temp_dir.rmdir()

    def _build_extraction_command(
        self,
        video_path: Path,
        output_path: Path,
    ) -> list[str]:
        """Build FFmpeg command for audio extraction.

        Args:
            video_path: Path to input video.
            output_path: Path for output audio.

        Returns:
            FFmpeg command as list of strings.
        """
        cmd = [
            self.config.ffmpeg_path,
            "-i",
            str(video_path),
            "-vn",  # No video
            "-acodec",
            self.config.codec,
            "-ar",
            str(self.config.sample_rate),
            "-ac",
            str(self.config.channels),
        ]

        # Add bitrate for lossy formats
        if self.config.bitrate and self.config.format in ("mp3", "aac", "opus"):
            cmd.extend(["-b:a", self.config.bitrate])

        # Overwrite output without asking
        cmd.extend(["-y", str(output_path)])

        return cmd

    async def _has_audio_stream(self, video_path: Path) -> bool:
        """Check if video has an audio stream.

        Args:
            video_path: Path to the video file.

        Returns:
            True if video has audio stream, False otherwise.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(video_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return bool(stdout.strip())
        except Exception:
            logger.warning("Could not check for audio stream, assuming present")
            return True

    async def _get_audio_metadata(self, audio_path: Path) -> dict:
        """Get metadata from extracted audio file.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Dict with audio metadata.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels,duration",
            "-of",
            "json",
            str(audio_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode == 0:
                import json

                data = json.loads(stdout.decode("utf-8"))
                streams = data.get("streams", [])
                if streams:
                    stream = streams[0]
                    return {
                        "sample_rate": int(stream.get("sample_rate", self.config.sample_rate)),
                        "channels": int(stream.get("channels", self.config.channels)),
                        "duration_seconds": float(stream.get("duration", 0.0)),
                    }
        except Exception as e:
            logger.warning("Could not get audio metadata: %s", e)

        return {}
