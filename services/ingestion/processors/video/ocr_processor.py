"""OCR batch processor for video keyframe text extraction.

This module provides the OCRBatchProcessor class that orchestrates
batch OCR processing of video keyframes with deduplication.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from processors.video.keyframe_extractor import ExtractedKeyframe
from processors.video.ocr.base import OCREngine, OCRResult
from processors.video.ocr.tesseract import TesseractOCR, TesseractOCRConfig

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class OCRProcessorConfig:
    """Configuration for OCR batch processor.

    Attributes:
        max_concurrent: Maximum concurrent OCR operations.
        confidence_threshold: Minimum confidence for text.
        deduplicate_text: Enable text deduplication across frames.
        similarity_threshold: Threshold for considering text as duplicate.
        skip_repeated_watermarks: Filter likely watermarks/persistent UI.
        watermark_occurrence_threshold: Min occurrences to consider watermark.
    """

    max_concurrent: int = 4
    confidence_threshold: float = 60.0
    deduplicate_text: bool = True
    similarity_threshold: float = 0.9
    skip_repeated_watermarks: bool = True
    watermark_occurrence_threshold: int = 3

    # Tesseract config
    tesseract_config: TesseractOCRConfig = field(default_factory=TesseractOCRConfig)


@dataclass
class KeyframeOCR:
    """OCR result for a keyframe.

    Attributes:
        keyframe: The processed keyframe.
        result: OCR result.
        filtered_text: Text after deduplication/filtering.
    """

    keyframe: ExtractedKeyframe
    result: OCRResult
    filtered_text: str = ""


class OCRBatchProcessor:
    """Batch processor for OCR on video keyframes.

    Handles concurrent OCR processing with text deduplication
    to remove repeated watermarks and persistent UI elements.

    Example:
        processor = OCRBatchProcessor()
        results = await processor.process_keyframes(
            keyframes=extracted_keyframes,
            progress_callback=update_progress,
        )
    """

    def __init__(
        self,
        config: OCRProcessorConfig | None = None,
        ocr_engine: OCREngine | None = None,
    ):
        """Initialize OCR batch processor.

        Args:
            config: Processor configuration.
            ocr_engine: Optional OCR engine (defaults to Tesseract).
        """
        self.config = config or OCRProcessorConfig()
        self._ocr_engine = ocr_engine

    def _get_ocr_engine(self) -> OCREngine:
        """Get or create OCR engine."""
        if self._ocr_engine is None:
            self._ocr_engine = TesseractOCR(self.config.tesseract_config)
        return self._ocr_engine

    async def process_keyframes(
        self,
        keyframes: list[ExtractedKeyframe],
        progress_callback: ProgressCallback | None = None,
    ) -> list[KeyframeOCR]:
        """Process multiple keyframes with OCR.

        Args:
            keyframes: List of extracted keyframes.
            progress_callback: Optional progress callback (current, total, message).

        Returns:
            List of KeyframeOCR results.
        """
        if not keyframes:
            return []

        total = len(keyframes)
        logger.info("Processing %d keyframes with OCR", total)

        ocr_engine = self._get_ocr_engine()
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        results: list[KeyframeOCR] = []
        completed = 0

        async def process_single(keyframe: ExtractedKeyframe) -> KeyframeOCR:
            nonlocal completed

            async with semaphore:
                result = await ocr_engine.extract_text(keyframe.image_path)

                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"OCR frame {completed}/{total}")

                return KeyframeOCR(
                    keyframe=keyframe,
                    result=result,
                    filtered_text=result.full_text,
                )

        # Process all keyframes
        tasks = [process_single(kf) for kf in keyframes]
        results = await asyncio.gather(*tasks)
        results = list(results)

        # Apply deduplication if enabled
        if self.config.deduplicate_text:
            results = self._deduplicate_text(results)

        # Remove watermarks if enabled
        if self.config.skip_repeated_watermarks:
            results = self._remove_watermarks(results)

        # Log summary
        text_count = sum(1 for r in results if r.filtered_text.strip())
        logger.info(
            "OCR complete: %d/%d frames have text",
            text_count,
            total,
        )

        return results

    def _deduplicate_text(
        self,
        results: list[KeyframeOCR],
    ) -> list[KeyframeOCR]:
        """Remove duplicate text across consecutive frames.

        Args:
            results: List of OCR results.

        Returns:
            Results with deduplicated text.
        """
        if len(results) < 2:
            return results

        # Sort by timestamp
        results_sorted = sorted(results, key=lambda r: r.keyframe.timestamp_seconds)

        prev_text = ""
        for result in results_sorted:
            current_text = result.filtered_text.strip()

            # Check similarity to previous frame
            if current_text and prev_text:
                similarity = self._text_similarity(prev_text, current_text)
                if similarity >= self.config.similarity_threshold:
                    # Mark as duplicate by clearing filtered_text
                    result.filtered_text = ""
                    continue

            prev_text = current_text

        return results

    def _remove_watermarks(
        self,
        results: list[KeyframeOCR],
    ) -> list[KeyframeOCR]:
        """Remove likely watermarks that appear in many frames.

        Args:
            results: List of OCR results.

        Returns:
            Results with watermarks removed.
        """
        # Count text occurrences
        text_counts: dict[str, int] = {}
        for result in results:
            if result.result.success:
                for region in result.result.regions:
                    text = region.text.strip().lower()
                    if len(text) > 2:  # Ignore very short text
                        text_counts[text] = text_counts.get(text, 0) + 1

        # Identify watermarks (appear in many frames)
        total_frames = len(results)
        threshold = max(
            self.config.watermark_occurrence_threshold,
            int(total_frames * 0.3),  # Appears in 30%+ of frames
        )
        watermarks = {text for text, count in text_counts.items() if count >= threshold}

        if watermarks:
            logger.info("Identified %d likely watermarks", len(watermarks))

        # Filter watermarks from results
        for result in results:
            if result.filtered_text:
                words = result.filtered_text.split()
                filtered_words = [w for w in words if w.strip().lower() not in watermarks]
                result.filtered_text = " ".join(filtered_words)

        return results

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts.

        Uses simple character-level Jaccard similarity.

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            Similarity score (0-1).
        """
        if not text1 or not text2:
            return 0.0

        # Normalize
        text1 = text1.lower().strip()
        text2 = text2.lower().strip()

        if text1 == text2:
            return 1.0

        # Character trigrams
        def get_trigrams(text: str) -> set[str]:
            return {text[i : i + 3] for i in range(len(text) - 2)}

        trigrams1 = get_trigrams(text1)
        trigrams2 = get_trigrams(text2)

        if not trigrams1 or not trigrams2:
            return 0.0

        intersection = len(trigrams1 & trigrams2)
        union = len(trigrams1 | trigrams2)

        return intersection / union if union > 0 else 0.0

    async def process_for_video(
        self,
        keyframes: list[ExtractedKeyframe],
        video_id: UUID,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[int, str]:
        """Process keyframes and return OCR text by frame index.

        Args:
            keyframes: List of extracted keyframes.
            video_id: Video identifier for logging.
            progress_callback: Optional progress callback.

        Returns:
            Dict mapping frame_index to OCR text.
        """
        results = await self.process_keyframes(
            keyframes=keyframes,
            progress_callback=progress_callback,
        )

        ocr_texts = {}
        for ocr_result in results:
            if ocr_result.filtered_text.strip():
                ocr_texts[ocr_result.keyframe.frame_index] = ocr_result.filtered_text

        logger.info(
            "Extracted OCR text from %d frames for video_id=%s",
            len(ocr_texts),
            video_id,
        )

        return ocr_texts

    def close(self) -> None:
        """Close OCR engine."""
        if self._ocr_engine is not None and hasattr(self._ocr_engine, "close"):
            self._ocr_engine.close()
