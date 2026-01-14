"""
Video processing exceptions.

This module defines custom exceptions for video processing operations
in the Video RAG Pipeline.
"""


class VideoProcessingError(Exception):
    """Base exception for video processing errors."""

    def __init__(self, message: str, video_id: str | None = None, details: dict | None = None):
        self.message = message
        self.video_id = video_id
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.video_id:
            return f"{self.message} (video_id={self.video_id})"
        return self.message


class VideoValidationError(VideoProcessingError):
    """Raised when video validation fails.

    Common causes:
    - Invalid video format/codec
    - Duration outside allowed range
    - File size exceeds limit
    - Corrupted video file
    """


class VideoStorageError(VideoProcessingError):
    """Raised when video storage operations fail.

    Common causes:
    - MinIO upload failure
    - File not found
    - Permission denied
    - Storage quota exceeded
    """


class AudioExtractionError(VideoProcessingError):
    """Raised when audio extraction fails.

    Common causes:
    - No audio track in video
    - FFmpeg execution error
    - Unsupported audio codec
    """


class TranscriptionError(VideoProcessingError):
    """Raised when transcription fails.

    Common causes:
    - Whisper model error
    - Invalid audio format
    - Language detection failure
    """


class SceneDetectionError(VideoProcessingError):
    """Raised when scene detection fails.

    Common causes:
    - PySceneDetect error
    - Video decode error
    - Insufficient video quality
    """


class KeyframeExtractionError(VideoProcessingError):
    """Raised when keyframe extraction fails.

    Common causes:
    - FFmpeg extraction error
    - Invalid timestamp
    - Image encoding error
    """


class VisionAnalysisError(VideoProcessingError):
    """Raised when vision LLM analysis fails.

    Common causes:
    - API rate limit exceeded
    - Invalid image format
    - Provider API error
    """


class OCRExtractionError(VideoProcessingError):
    """Raised when OCR extraction fails.

    Common causes:
    - Tesseract error
    - Invalid image format
    - Image preprocessing error
    """


class ContentFusionError(VideoProcessingError):
    """Raised when content fusion fails.

    Common causes:
    - Invalid chunk boundaries
    - Missing required modalities
    - Database storage error
    """
