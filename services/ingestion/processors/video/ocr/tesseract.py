"""Tesseract OCR engine implementation.

This module provides the TesseractOCR class for extracting on-screen
text from video keyframes using Tesseract OCR.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from processors.video.ocr.base import OCREngine, OCRResult, TextRegion

logger = logging.getLogger(__name__)


@dataclass
class TesseractOCRConfig:
    """Configuration for Tesseract OCR.

    Attributes:
        language: Language code(s) for OCR.
        confidence_threshold: Minimum confidence for text regions.
        psm: Page segmentation mode.
        oem: OCR engine mode.
        preprocessing: Enable image preprocessing.
        dpi: DPI setting for OCR.
        timeout_seconds: Timeout for OCR processing.
    """

    language: str = "eng"
    confidence_threshold: float = 60.0
    psm: int = 3  # Fully automatic page segmentation
    oem: int = 3  # Default, use LSTM neural net
    preprocessing: bool = True
    dpi: int = 300
    timeout_seconds: float = 30.0


class TesseractOCR(OCREngine):
    """Tesseract OCR engine for text extraction.

    Uses pytesseract for OCR with optional image preprocessing
    for improved accuracy.

    Example:
        ocr = TesseractOCR(
            config=TesseractOCRConfig(language="eng")
        )
        result = await ocr.extract_text("/path/to/frame.jpg")
    """

    def __init__(self, config: TesseractOCRConfig | None = None):
        """Initialize Tesseract OCR.

        Args:
            config: OCR configuration.
        """
        self.config = config or TesseractOCRConfig()
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def extract_text(
        self,
        image_path: str | Path,
    ) -> OCRResult:
        """Extract text from an image using Tesseract.

        Args:
            image_path: Path to the image file.

        Returns:
            OCRResult with extracted text.
        """
        image_path = Path(image_path)

        if not image_path.exists():
            return OCRResult(
                success=False,
                error=f"Image not found: {image_path}",
            )

        start_time = time.time()

        try:
            # Run OCR in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    self._process_image,
                    image_path,
                ),
                timeout=self.config.timeout_seconds,
            )

            result.processing_time_ms = (time.time() - start_time) * 1000
            return result

        except TimeoutError:
            return OCRResult(
                success=False,
                error="OCR processing timed out",
                processing_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.warning("OCR failed for %s: %s", image_path.name, e)
            return OCRResult(
                success=False,
                error=str(e),
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    def _process_image(self, image_path: Path) -> OCRResult:
        """Process image with Tesseract (sync).

        Args:
            image_path: Path to image.

        Returns:
            OCRResult.
        """
        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            raise ImportError(
                "pytesseract or Pillow not installed. Install with: pip install pytesseract Pillow"
            ) from e

        # Load image
        image = Image.open(image_path)

        # Preprocess if enabled
        if self.config.preprocessing:
            image = self._preprocess_image(image)

        # Build Tesseract config
        custom_config = (
            f"--psm {self.config.psm} "
            f"--oem {self.config.oem} "
            f"-c tessedit_pageseg_mode={self.config.psm}"
        )

        # Get detailed data with bounding boxes
        data = pytesseract.image_to_data(
            image,
            lang=self.config.language,
            config=custom_config,
            output_type=pytesseract.Output.DICT,
        )

        # Process results
        regions = []
        text_lines = []
        current_line = -1

        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])

            # Skip empty or low-confidence text
            if not text or conf < self.config.confidence_threshold:
                continue

            # Track line numbers
            line_num = data["line_num"][i]
            if line_num != current_line:
                current_line = line_num
                text_lines.append([])

            text_lines[-1].append(text)

            # Create text region
            regions.append(
                TextRegion(
                    text=text,
                    confidence=conf,
                    bbox=(
                        data["left"][i],
                        data["top"][i],
                        data["width"][i],
                        data["height"][i],
                    ),
                    line_num=line_num,
                )
            )

        # Combine text
        full_text = " ".join(" ".join(line) for line in text_lines if line)

        return OCRResult(
            success=True,
            full_text=full_text,
            regions=regions,
            language=self.config.language,
        )

    def _preprocess_image(self, image):
        """Preprocess image for better OCR.

        Args:
            image: PIL Image.

        Returns:
            Preprocessed PIL Image.
        """
        try:
            from PIL import ImageEnhance, ImageFilter
        except ImportError:
            return image

        # Convert to grayscale if not already
        if image.mode != "L":
            image = image.convert("L")

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.5)

        # Sharpen
        image = image.filter(ImageFilter.SHARPEN)

        # Resize if too small (helps OCR accuracy)
        min_width = 1000
        if image.width < min_width:
            ratio = min_width / image.width
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size)

        return image

    @property
    def engine_name(self) -> str:
        """Get the engine name."""
        return "tesseract"

    def close(self) -> None:
        """Shutdown thread pool."""
        self._executor.shutdown(wait=False)
