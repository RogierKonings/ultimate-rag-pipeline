"""Base classes for OCR engines.

This module defines the abstract base class and data models for OCR
engine implementations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TextRegion:
    """A detected text region in an image.

    Attributes:
        text: Extracted text content.
        confidence: Confidence score (0-100).
        bbox: Bounding box (x, y, width, height).
        line_num: Line number in detection order.
    """

    text: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, width, height
    line_num: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "line_num": self.line_num,
        }


@dataclass
class OCRResult:
    """Result of OCR processing.

    Attributes:
        success: Whether OCR succeeded.
        full_text: Combined text from all regions.
        regions: List of detected text regions.
        processing_time_ms: Processing time in milliseconds.
        error: Error message if failed.
        language: Detected or specified language.
    """

    success: bool
    full_text: str = ""
    regions: list[TextRegion] = field(default_factory=list)
    processing_time_ms: float = 0.0
    error: str | None = None
    language: str = "eng"

    @property
    def has_text(self) -> bool:
        """Check if any text was detected."""
        return bool(self.full_text.strip())

    @property
    def region_count(self) -> int:
        """Get number of text regions."""
        return len(self.regions)

    @property
    def average_confidence(self) -> float:
        """Get average confidence across regions."""
        if not self.regions:
            return 0.0
        return sum(r.confidence for r in self.regions) / len(self.regions)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "full_text": self.full_text,
            "regions": [r.to_dict() for r in self.regions],
            "processing_time_ms": self.processing_time_ms,
            "error": self.error,
            "language": self.language,
            "region_count": self.region_count,
            "average_confidence": self.average_confidence,
        }


class OCREngine(ABC):
    """Abstract base class for OCR engines.

    Defines the interface for OCR implementations used to extract
    on-screen text from video keyframes.

    Example:
        engine = TesseractOCR()
        result = await engine.extract_text(
            image_path="/path/to/frame.jpg"
        )
    """

    @abstractmethod
    async def extract_text(
        self,
        image_path: str | Path,
    ) -> OCRResult:
        """Extract text from an image.

        Args:
            image_path: Path to the image file.

        Returns:
            OCRResult with extracted text.
        """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Get the engine name."""
