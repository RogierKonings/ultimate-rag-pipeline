"""OCR engine implementations for video frame text extraction.

This module provides OCR engines for extracting on-screen text from
video keyframes.
"""

from processors.video.ocr.base import OCREngine, OCRResult, TextRegion
from processors.video.ocr.tesseract import TesseractOCR, TesseractOCRConfig

__all__ = [
    "OCREngine",
    "OCRResult",
    "TextRegion",
    "TesseractOCR",
    "TesseractOCRConfig",
]
