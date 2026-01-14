# US-9.5: OCR Text Extraction

> **Story ID:** US-9.5
> **Epic:** Video RAG Pipeline
> **Priority:** Medium
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.3 (Keyframe Extraction)

## User Story

**As a** system
**I want** to extract on-screen text from video frames
**So that** overlays, captions, and scoreboards are searchable

## Context

Many videos contain important textual information displayed on screen: presentation slides, scoreboards, news tickers, captions, titles, watermarks, and UI elements. OCR (Optical Character Recognition) extracts this text from keyframes, making it searchable alongside transcript and scene descriptions.

## Technical Requirements

### OCR Service

```python
# processors/video/ocr_extractor.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import logging

logger = logging.getLogger(__name__)

@dataclass
class OCRBoundingBox:
    """Bounding box for detected text."""
    x: int
    y: int
    width: int
    height: int
    confidence: float

@dataclass
class OCRTextBlock:
    """A block of detected text with location."""
    text: str
    confidence: float
    bounding_box: OCRBoundingBox | None = None
    block_type: Literal["line", "word", "paragraph"] = "line"

@dataclass
class OCRResult:
    success: bool
    text_blocks: list[OCRTextBlock] = field(default_factory=list)
    full_text: str = ""
    error: str | None = None

@dataclass
class OCRConfig:
    engine: Literal["tesseract", "easyocr", "paddleocr"] = "tesseract"
    languages: list[str] = field(default_factory=lambda: ["eng"])
    min_confidence: float = 0.5
    preprocessing: bool = True
    psm: int = 3  # Tesseract page segmentation mode

class TesseractOCR:
    """OCR using Tesseract."""

    def __init__(self, config: OCRConfig = None):
        self.config = config or OCRConfig()

    async def extract_text(self, image_path: Path) -> OCRResult:
        """
        Extract text from an image using Tesseract.

        Args:
            image_path: Path to image file

        Returns:
            OCRResult with extracted text blocks
        """
        import pytesseract
        from PIL import Image

        try:
            # Load and preprocess image
            img = Image.open(image_path)
            if self.config.preprocessing:
                img = self._preprocess(img)

            # Get detailed output with bounding boxes
            lang = "+".join(self.config.languages)
            data = pytesseract.image_to_data(
                img,
                lang=lang,
                config=f"--psm {self.config.psm}",
                output_type=pytesseract.Output.DICT
            )

            # Parse results
            text_blocks = []
            current_line = []
            current_line_num = -1

            for i in range(len(data["text"])):
                text = data["text"][i].strip()
                conf = float(data["conf"][i])

                if not text or conf < self.config.min_confidence * 100:
                    continue

                block = OCRTextBlock(
                    text=text,
                    confidence=conf / 100,
                    bounding_box=OCRBoundingBox(
                        x=data["left"][i],
                        y=data["top"][i],
                        width=data["width"][i],
                        height=data["height"][i],
                        confidence=conf / 100
                    ),
                    block_type="word"
                )
                text_blocks.append(block)

            # Combine into full text
            full_text = pytesseract.image_to_string(
                img,
                lang=lang,
                config=f"--psm {self.config.psm}"
            ).strip()

            return OCRResult(
                success=True,
                text_blocks=text_blocks,
                full_text=full_text
            )

        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return OCRResult(success=False, error=str(e))

    def _preprocess(self, img: "Image.Image") -> "Image.Image":
        """Preprocess image for better OCR accuracy."""
        from PIL import ImageEnhance, ImageFilter

        # Convert to grayscale
        img = img.convert("L")

        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        # Sharpen
        img = img.filter(ImageFilter.SHARPEN)

        return img

class EasyOCR:
    """OCR using EasyOCR (deep learning based)."""

    def __init__(self, config: OCRConfig = None):
        self.config = config or OCRConfig()
        self._reader = None

    async def _get_reader(self):
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(
                self.config.languages,
                gpu=True
            )
        return self._reader

    async def extract_text(self, image_path: Path) -> OCRResult:
        """Extract text using EasyOCR."""
        try:
            reader = await self._get_reader()
            results = reader.readtext(str(image_path))

            text_blocks = []
            texts = []

            for bbox, text, conf in results:
                if conf < self.config.min_confidence:
                    continue

                # bbox is [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                x = int(min(p[0] for p in bbox))
                y = int(min(p[1] for p in bbox))
                w = int(max(p[0] for p in bbox)) - x
                h = int(max(p[1] for p in bbox)) - y

                block = OCRTextBlock(
                    text=text,
                    confidence=conf,
                    bounding_box=OCRBoundingBox(x=x, y=y, width=w, height=h, confidence=conf),
                    block_type="line"
                )
                text_blocks.append(block)
                texts.append(text)

            return OCRResult(
                success=True,
                text_blocks=text_blocks,
                full_text=" ".join(texts)
            )

        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            return OCRResult(success=False, error=str(e))
```

### OCR Batch Processor

```python
# processors/video/ocr_batch.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class BatchOCRResult:
    successful: int
    failed: int
    results: dict[int, OCRResult]  # frame_index -> result
    unique_texts: set[str]

class OCRBatchProcessor:
    """Processes multiple keyframes for OCR with deduplication."""

    def __init__(self, ocr_engine: TesseractOCR | EasyOCR):
        self.ocr = ocr_engine

    async def process_keyframes(
        self,
        keyframes: list[tuple[int, Path]],  # (frame_index, image_path)
        progress_callback=None
    ) -> BatchOCRResult:
        """
        Run OCR on multiple keyframes with text deduplication.

        Text that appears across multiple consecutive frames (e.g., persistent
        overlays) is deduplicated to avoid repetition in search results.
        """
        results = {}
        all_texts = []
        completed = 0

        # Process in parallel with limited concurrency
        semaphore = asyncio.Semaphore(4)

        async def process_one(frame_index: int, image_path: Path):
            nonlocal completed
            async with semaphore:
                result = await self.ocr.extract_text(image_path)
                results[frame_index] = result

                completed += 1
                if progress_callback:
                    progress_callback(completed, len(keyframes))

                return result

        await asyncio.gather(*[
            process_one(idx, path) for idx, path in keyframes
        ])

        # Collect all texts for deduplication analysis
        for result in results.values():
            if result.success and result.full_text:
                all_texts.append(result.full_text)

        # Deduplicate - find texts that appear in >50% of frames
        unique_texts = self._deduplicate_texts(all_texts)

        successful = sum(1 for r in results.values() if r.success)
        failed = len(keyframes) - successful

        logger.info(f"OCR complete: {successful} succeeded, {len(unique_texts)} unique texts")

        return BatchOCRResult(
            successful=successful,
            failed=failed,
            results=results,
            unique_texts=unique_texts
        )

    def _deduplicate_texts(self, texts: list[str]) -> set[str]:
        """
        Remove text that appears too frequently (likely persistent UI elements).

        Returns set of unique, meaningful text segments.
        """
        from collections import Counter

        if not texts:
            return set()

        # Count occurrences of each text segment
        all_segments = []
        for text in texts:
            # Split into lines/segments
            segments = [s.strip() for s in text.split("\n") if s.strip()]
            all_segments.extend(segments)

        counts = Counter(all_segments)
        threshold = len(texts) * 0.5  # Appears in >50% of frames

        # Filter out too-common segments
        unique = {
            segment for segment, count in counts.items()
            if count < threshold and len(segment) > 2
        }

        return unique
```

### OCR Storage

```python
# processors/video/ocr_storage.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

class OCRStorage:
    """Stores OCR results in database."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def store_ocr_results(
        self,
        video_id: UUID,
        results: dict[int, "OCRResult"]
    ) -> int:
        """Store OCR text for keyframes."""
        updated = 0

        for frame_index, result in results.items():
            if not result.success or not result.full_text:
                continue

            await self.session.execute(
                update(VideoKeyframe)
                .where(VideoKeyframe.video_id == video_id)
                .where(VideoKeyframe.frame_index == frame_index)
                .values(ocr_text=result.full_text)
            )
            updated += 1

        await self.session.commit()
        return updated

    async def get_ocr_text(self, video_id: UUID) -> list[dict]:
        """Get all OCR text for a video."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(VideoKeyframe.frame_index, VideoKeyframe.timestamp_ms, VideoKeyframe.ocr_text)
            .where(VideoKeyframe.video_id == video_id)
            .where(VideoKeyframe.ocr_text.isnot(None))
            .order_by(VideoKeyframe.frame_index)
        )

        return [
            {"frame_index": r[0], "timestamp_ms": r[1], "text": r[2]}
            for r in result
        ]
```

### Pipeline Integration

```python
# In VideoProcessingPipeline

async def _run_ocr_stage(
    self,
    keyframes: list["ExtractedKeyframe"]
) -> dict[int, OCRResult]:
    """Extract text from keyframes using OCR."""
    if not self.options.get("extract_ocr", True):
        logger.info("OCR disabled, skipping")
        return {}

    await self._update_progress("extracting_ocr", 0)

    # Create OCR engine
    ocr_config = OCRConfig(
        engine=self.config.ocr_engine,
        languages=self.config.ocr_languages
    )

    if ocr_config.engine == "tesseract":
        ocr = TesseractOCR(ocr_config)
    else:
        ocr = EasyOCR(ocr_config)

    processor = OCRBatchProcessor(ocr)

    # Process keyframes
    keyframe_inputs = [(kf.frame_index, kf.image_path) for kf in keyframes]

    result = await processor.process_keyframes(
        keyframe_inputs,
        progress_callback=lambda done, total: self._update_progress(
            "extracting_ocr",
            int(done / total * 100)
        )
    )

    # Store results
    await self.ocr_storage.store_ocr_results(self.video_id, result.results)

    await self._update_progress("extracting_ocr", 100)

    return result.results
```

## Configuration

```python
class OCRConfig(BaseSettings):
    ocr_engine: str = "tesseract"
    ocr_languages: list[str] = ["eng"]
    ocr_min_confidence: float = 0.5
    ocr_preprocessing: bool = True

    class Config:
        env_prefix = "OCR_"
```

## System Requirements

```dockerfile
# Tesseract
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# For additional languages:
# tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa etc.
```

## OCR Engine Comparison

| Engine | Speed | Accuracy | Languages | GPU Support |
|--------|-------|----------|-----------|-------------|
| Tesseract | Fast | Good | 100+ | No |
| EasyOCR | Medium | Better | 80+ | Yes |
| PaddleOCR | Medium | Best | 80+ | Yes |

## Acceptance Criteria

- [ ] Run OCR on keyframes using Tesseract
- [ ] Extract text from scoreboards, titles, captions, overlays
- [ ] Associate OCR text with timestamps
- [ ] Deduplicate repeated text across frames
- [ ] Handle frames with no text gracefully

## Testing Requirements

```python
class TestTesseractOCR:
    @pytest.mark.asyncio
    async def test_extracts_text_from_image(self, image_with_text):
        ocr = TesseractOCR()
        result = await ocr.extract_text(image_with_text)

        assert result.success
        assert "Hello World" in result.full_text

    @pytest.mark.asyncio
    async def test_returns_bounding_boxes(self, image_with_text):
        ocr = TesseractOCR()
        result = await ocr.extract_text(image_with_text)

        assert result.text_blocks
        assert result.text_blocks[0].bounding_box is not None

    @pytest.mark.asyncio
    async def test_handles_image_without_text(self, blank_image):
        ocr = TesseractOCR()
        result = await ocr.extract_text(blank_image)

        assert result.success
        assert result.full_text == ""

    @pytest.mark.asyncio
    async def test_filters_low_confidence(self, noisy_image):
        ocr = TesseractOCR(OCRConfig(min_confidence=0.8))
        result = await ocr.extract_text(noisy_image)

        for block in result.text_blocks:
            assert block.confidence >= 0.8

class TestOCRBatchProcessor:
    @pytest.mark.asyncio
    async def test_deduplicates_repeated_text(self, keyframes_with_watermark):
        """Watermark text appearing in all frames should be deduplicated."""
        ocr = TesseractOCR()
        processor = OCRBatchProcessor(ocr)

        result = await processor.process_keyframes(keyframes_with_watermark)

        # Watermark should not be in unique_texts
        assert "© Company Name" not in result.unique_texts

    @pytest.mark.asyncio
    async def test_preserves_unique_text(self, varied_keyframes):
        """Text appearing in few frames should be preserved."""
        ocr = TesseractOCR()
        processor = OCRBatchProcessor(ocr)

        result = await processor.process_keyframes(varied_keyframes)

        assert len(result.unique_texts) > 0
```

## Dependencies

```
pytesseract>=0.3.10
Pillow>=10.0.0
# Optional for EasyOCR:
easyocr>=1.7.0
```

## Definition of Done

- [ ] Tesseract OCR extracting text accurately
- [ ] Bounding boxes available for text location
- [ ] Low-confidence text filtered out
- [ ] Repeated text deduplicated
- [ ] OCR text stored in database
- [ ] Frames without text handled gracefully
- [ ] Multiple languages supported
- [ ] >90% test coverage
