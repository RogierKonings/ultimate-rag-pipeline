"""Whisper transcription service for video processing.

This module provides the WhisperTranscriber class that transcribes audio
using OpenAI's Whisper model for speech-to-text.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from processors.video.exceptions import TranscriptionError

logger = logging.getLogger(__name__)

# Whisper model sizes and their approximate VRAM requirements
WHISPER_MODELS = {
    "tiny": {"params": "39M", "vram": "~1GB", "speed": "~32x"},
    "base": {"params": "74M", "vram": "~1GB", "speed": "~16x"},
    "small": {"params": "244M", "vram": "~2GB", "speed": "~6x"},
    "medium": {"params": "769M", "vram": "~5GB", "speed": "~2x"},
    "large": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
    "large-v2": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
    "large-v3": {"params": "1550M", "vram": "~10GB", "speed": "~1x"},
}

WhisperModel = Literal["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]


@dataclass
class TranscriptionConfig:
    """Configuration for Whisper transcription.

    Attributes:
        model: Whisper model to use.
        language: Language code (e.g., 'en', 'es') or None for auto-detection.
        task: 'transcribe' or 'translate' (translate to English).
        device: Device to run on ('cuda', 'cpu', 'auto').
        compute_type: Compute type for inference.
        beam_size: Beam size for decoding.
        word_timestamps: Whether to include word-level timestamps.
        vad_filter: Whether to use voice activity detection.
        vad_parameters: Parameters for VAD filtering.
    """

    model: WhisperModel = "base"
    language: str | None = None
    task: Literal["transcribe", "translate"] = "transcribe"
    device: str = "auto"
    compute_type: str = "default"
    beam_size: int = 5
    word_timestamps: bool = True
    vad_filter: bool = True
    vad_parameters: dict = field(
        default_factory=lambda: {
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 400,
        }
    )


@dataclass
class TranscriptSegment:
    """A segment of transcribed text with timing information.

    Attributes:
        id: Segment index.
        start_seconds: Start time in seconds.
        end_seconds: End time in seconds.
        text: Transcribed text.
        confidence: Confidence score (0-1).
        words: Word-level timing if available.
        speaker: Speaker ID if diarization is enabled.
    """

    id: int
    start_seconds: float
    end_seconds: float
    text: str
    confidence: float = 1.0
    words: list[dict] = field(default_factory=list)
    speaker: str | None = None

    @property
    def duration_seconds(self) -> float:
        """Get segment duration in seconds."""
        return self.end_seconds - self.start_seconds

    @property
    def start_ms(self) -> int:
        """Get start time in milliseconds."""
        return int(self.start_seconds * 1000)

    @property
    def end_ms(self) -> int:
        """Get end time in milliseconds."""
        return int(self.end_seconds * 1000)

    def to_dict(self) -> dict:
        """Convert segment to dictionary."""
        return {
            "id": self.id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_seconds": self.duration_seconds,
            "text": self.text,
            "confidence": self.confidence,
            "words": self.words,
            "speaker": self.speaker,
        }


@dataclass
class TranscriptionResult:
    """Result of audio transcription.

    Attributes:
        segments: List of transcript segments.
        language: Detected or specified language.
        language_probability: Confidence in language detection.
        duration_seconds: Total audio duration.
        text: Full transcript text.
    """

    segments: list[TranscriptSegment]
    language: str
    language_probability: float
    duration_seconds: float
    text: str = ""

    def __post_init__(self):
        """Compute full text if not provided."""
        if not self.text and self.segments:
            self.text = " ".join(s.text.strip() for s in self.segments)

    @property
    def word_count(self) -> int:
        """Get total word count."""
        return len(self.text.split())

    def get_text_at_time(self, seconds: float) -> str | None:
        """Get transcript text at a specific time.

        Args:
            seconds: Time in seconds.

        Returns:
            Text of segment containing the time, or None.
        """
        for segment in self.segments:
            if segment.start_seconds <= seconds <= segment.end_seconds:
                return segment.text
        return None

    def get_segments_in_range(
        self,
        start_seconds: float,
        end_seconds: float,
    ) -> list[TranscriptSegment]:
        """Get segments that overlap with a time range.

        Args:
            start_seconds: Range start time.
            end_seconds: Range end time.

        Returns:
            List of overlapping segments.
        """
        return [
            s
            for s in self.segments
            if s.end_seconds > start_seconds and s.start_seconds < end_seconds
        ]


class WhisperTranscriber:
    """Transcribes audio using OpenAI's Whisper model.

    Uses faster-whisper (CTranslate2) for efficient inference.
    Supports multiple model sizes and automatic language detection.

    Example:
        transcriber = WhisperTranscriber(
            config=TranscriptionConfig(model="base", language="en")
        )
        result = await transcriber.transcribe("/path/to/audio.wav")
        for segment in result.segments:
            print(f"[{segment.start_seconds:.1f}s] {segment.text}")
    """

    def __init__(self, config: TranscriptionConfig | None = None):
        """Initialize the transcriber.

        Args:
            config: Transcription configuration.
        """
        self.config = config or TranscriptionConfig()
        self._model = None

    async def transcribe(
        self,
        audio_path: str | Path,
    ) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.

        Returns:
            TranscriptionResult with segments and metadata.

        Raises:
            TranscriptionError: If transcription fails.
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        logger.info(
            "Transcribing audio: file=%s, model=%s, language=%s",
            audio_path.name,
            self.config.model,
            self.config.language or "auto",
        )

        try:
            # Import faster-whisper
            from faster_whisper import WhisperModel

            # Load model if not already loaded
            if self._model is None:
                device = self._get_device()
                compute_type = self._get_compute_type(device)

                logger.info(
                    "Loading Whisper model: %s (device=%s, compute=%s)",
                    self.config.model,
                    device,
                    compute_type,
                )

                self._model = WhisperModel(
                    self.config.model,
                    device=device,
                    compute_type=compute_type,
                )

            # Run transcription
            segments_generator, info = self._model.transcribe(
                str(audio_path),
                language=self.config.language,
                task=self.config.task,
                beam_size=self.config.beam_size,
                word_timestamps=self.config.word_timestamps,
                vad_filter=self.config.vad_filter,
                vad_parameters=self.config.vad_parameters if self.config.vad_filter else None,
            )

            # Convert segments to our format
            transcript_segments = []
            for i, segment in enumerate(segments_generator):
                words = []
                if self.config.word_timestamps and hasattr(segment, "words") and segment.words:
                    words = [
                        {
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability,
                        }
                        for w in segment.words
                    ]

                transcript_segments.append(
                    TranscriptSegment(
                        id=i,
                        start_seconds=segment.start,
                        end_seconds=segment.end,
                        text=segment.text.strip(),
                        confidence=segment.avg_logprob if hasattr(segment, "avg_logprob") else 1.0,
                        words=words,
                    )
                )

            result = TranscriptionResult(
                segments=transcript_segments,
                language=info.language,
                language_probability=info.language_probability,
                duration_seconds=info.duration,
            )

            logger.info(
                "Transcription complete: segments=%d, duration=%.1fs, language=%s (%.2f)",
                len(transcript_segments),
                info.duration,
                info.language,
                info.language_probability,
            )

            return result

        except ImportError as e:
            raise TranscriptionError(
                "faster-whisper not installed. Install with: pip install faster-whisper"
            ) from e
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {e}") from e

    async def transcribe_for_video(
        self,
        audio_path: str | Path,
        video_id: UUID,
        tenant_id: UUID,
    ) -> list[dict]:
        """Transcribe audio and format for video storage.

        Args:
            audio_path: Path to the audio file.
            video_id: Video identifier.
            tenant_id: Tenant identifier.

        Returns:
            List of segment dictionaries ready for database storage.
        """
        result = await self.transcribe(audio_path)

        # Format for database storage
        segments = []
        for segment in result.segments:
            segments.append(
                {
                    "video_id": str(video_id),
                    "tenant_id": str(tenant_id),
                    "segment_index": segment.id,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": segment.text,
                    "confidence": segment.confidence,
                    "words": segment.words,
                    "speaker": segment.speaker,
                    "language": result.language,
                }
            )

        return segments

    def _get_device(self) -> str:
        """Determine the device to use for inference.

        Returns:
            Device string ('cuda' or 'cpu').
        """
        if self.config.device != "auto":
            return self.config.device

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass

        return "cpu"

    def _get_compute_type(self, device: str) -> str:
        """Determine compute type based on device.

        Args:
            device: Target device.

        Returns:
            Compute type string.
        """
        if self.config.compute_type != "default":
            return self.config.compute_type

        if device == "cuda":
            return "float16"
        return "int8"

    def unload_model(self) -> None:
        """Unload the model to free memory."""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Whisper model unloaded")
