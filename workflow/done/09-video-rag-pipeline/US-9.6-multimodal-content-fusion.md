# US-9.6: Multi-Modal Content Fusion

> **Story ID:** US-9.6
> **Epic:** Video RAG Pipeline
> **Priority:** High
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.2 (Transcription), US-9.4 (Visual Analysis), US-9.5 (OCR)

## User Story

**As a** system
**I want** to combine all extracted content into searchable chunks
**So that** users can find video moments using any modality

## Context

After extracting transcript, scene descriptions, and OCR text, these modalities must be fused into coherent chunks that represent segments of the video. Each chunk combines time-aligned content from all sources into a `fused_text` field optimized for embedding and search. This enables users to search using spoken words, visual descriptions, or on-screen text interchangeably.

## Technical Requirements

### Video Chunk Data Model

```python
# processors/video/fusion.py
from dataclasses import dataclass, field
from uuid import UUID
from typing import Literal

@dataclass
class VideoChunk:
    """A searchable segment of video content."""
    video_id: UUID
    chunk_index: int
    start_time_ms: int
    end_time_ms: int

    # Content from each modality
    transcript_text: str = ""
    scene_description: str = ""
    ocr_text: str = ""

    # Combined text for embedding
    fused_text: str = ""

    # Metadata
    keyframe_index: int | None = None
    keyframe_path: str | None = None
    source_modalities: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.end_time_ms - self.start_time_ms

    @property
    def has_content(self) -> bool:
        return bool(self.transcript_text or self.scene_description or self.ocr_text)
```

### Content Fusion Service

```python
# processors/video/content_fusion.py
from dataclasses import dataclass
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

@dataclass
class FusionConfig:
    """Configuration for content fusion."""
    target_chunk_duration_ms: int = 20_000  # 20 seconds
    min_chunk_duration_ms: int = 10_000  # 10 seconds
    max_chunk_duration_ms: int = 30_000  # 30 seconds
    overlap_ms: int = 2_000  # 2 second overlap

    # Fusion template
    include_modality_labels: bool = True
    separator: str = "\n\n"

@dataclass
class FusionResult:
    success: bool
    chunks: list[VideoChunk]
    total_duration_ms: int
    error: str | None = None

class ContentFusionService:
    """Fuses multi-modal content into searchable video chunks."""

    def __init__(self, config: FusionConfig = None):
        self.config = config or FusionConfig()

    def fuse_content(
        self,
        video_id: UUID,
        duration_ms: int,
        transcripts: list[dict],  # [{"start_ms", "end_ms", "text"}]
        keyframes: list[dict],    # [{"timestamp_ms", "frame_index", "scene_description", "ocr_text"}]
    ) -> FusionResult:
        """
        Combine transcript, scene, and OCR content into chunks.

        Strategy:
        1. Divide video into time-based chunks
        2. Align transcript segments to chunks
        3. Align keyframe content to chunks
        4. Generate fused text for each chunk
        """
        try:
            # Generate chunk boundaries
            boundaries = self._generate_chunk_boundaries(duration_ms)

            chunks = []
            for i, (start_ms, end_ms) in enumerate(boundaries):
                chunk = self._create_chunk(
                    video_id=video_id,
                    chunk_index=i,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    transcripts=transcripts,
                    keyframes=keyframes
                )

                if chunk.has_content:
                    chunks.append(chunk)

            logger.info(f"Created {len(chunks)} video chunks from {len(boundaries)} time segments")

            return FusionResult(
                success=True,
                chunks=chunks,
                total_duration_ms=duration_ms
            )

        except Exception as e:
            logger.error(f"Content fusion failed: {e}")
            return FusionResult(success=False, chunks=[], total_duration_ms=0, error=str(e))

    def _generate_chunk_boundaries(self, duration_ms: int) -> list[tuple[int, int]]:
        """Generate time boundaries for chunks with overlap."""
        boundaries = []
        current_start = 0

        while current_start < duration_ms:
            chunk_end = min(
                current_start + self.config.target_chunk_duration_ms,
                duration_ms
            )

            # Ensure minimum chunk size for last chunk
            if duration_ms - chunk_end < self.config.min_chunk_duration_ms:
                chunk_end = duration_ms

            boundaries.append((current_start, chunk_end))

            # Next chunk starts with overlap
            current_start = chunk_end - self.config.overlap_ms

            # Prevent infinite loop
            if chunk_end >= duration_ms:
                break

        return boundaries

    def _create_chunk(
        self,
        video_id: UUID,
        chunk_index: int,
        start_ms: int,
        end_ms: int,
        transcripts: list[dict],
        keyframes: list[dict]
    ) -> VideoChunk:
        """Create a single chunk with aligned content."""

        # Get transcript text for this time range
        transcript_text = self._get_transcript_for_range(transcripts, start_ms, end_ms)

        # Get keyframe content for this time range
        scene_descriptions = []
        ocr_texts = []
        best_keyframe = None

        for kf in keyframes:
            if start_ms <= kf["timestamp_ms"] < end_ms:
                if kf.get("scene_description"):
                    scene_descriptions.append(kf["scene_description"])
                if kf.get("ocr_text"):
                    ocr_texts.append(kf["ocr_text"])
                if best_keyframe is None:
                    best_keyframe = kf

        scene_text = self._deduplicate_descriptions(scene_descriptions)
        ocr_text = self._deduplicate_ocr(ocr_texts)

        # Generate fused text
        fused_text = self._generate_fused_text(transcript_text, scene_text, ocr_text)

        # Track source modalities
        modalities = []
        if transcript_text:
            modalities.append("transcript")
        if scene_text:
            modalities.append("visual")
        if ocr_text:
            modalities.append("ocr")

        return VideoChunk(
            video_id=video_id,
            chunk_index=chunk_index,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            transcript_text=transcript_text,
            scene_description=scene_text,
            ocr_text=ocr_text,
            fused_text=fused_text,
            keyframe_index=best_keyframe["frame_index"] if best_keyframe else None,
            keyframe_path=best_keyframe.get("storage_path") if best_keyframe else None,
            source_modalities=modalities
        )

    def _get_transcript_for_range(
        self,
        transcripts: list[dict],
        start_ms: int,
        end_ms: int
    ) -> str:
        """Extract transcript text that falls within the time range."""
        texts = []

        for seg in transcripts:
            seg_start = seg["start_ms"]
            seg_end = seg["end_ms"]

            # Include if there's any overlap
            if seg_end > start_ms and seg_start < end_ms:
                texts.append(seg["text"])

        return " ".join(texts).strip()

    def _deduplicate_descriptions(self, descriptions: list[str]) -> str:
        """Combine multiple scene descriptions, removing redundancy."""
        if not descriptions:
            return ""

        if len(descriptions) == 1:
            return descriptions[0]

        # For multiple descriptions, combine unique sentences
        seen = set()
        unique_sentences = []

        for desc in descriptions:
            sentences = [s.strip() for s in desc.split(".") if s.strip()]
            for sentence in sentences:
                normalized = sentence.lower()
                if normalized not in seen:
                    seen.add(normalized)
                    unique_sentences.append(sentence)

        return ". ".join(unique_sentences[:5]) + "."  # Limit to 5 sentences

    def _deduplicate_ocr(self, ocr_texts: list[str]) -> str:
        """Combine OCR texts, removing duplicates."""
        if not ocr_texts:
            return ""

        # Split into lines and deduplicate
        seen = set()
        unique_lines = []

        for text in ocr_texts:
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for line in lines:
                if line.lower() not in seen:
                    seen.add(line.lower())
                    unique_lines.append(line)

        return " | ".join(unique_lines[:10])  # Limit to 10 lines

    def _generate_fused_text(
        self,
        transcript: str,
        scene: str,
        ocr: str
    ) -> str:
        """Generate combined text optimized for embedding."""
        parts = []

        if self.config.include_modality_labels:
            if transcript:
                parts.append(f"[Speech] {transcript}")
            if scene:
                parts.append(f"[Visual] {scene}")
            if ocr:
                parts.append(f"[Text on screen] {ocr}")
        else:
            if transcript:
                parts.append(transcript)
            if scene:
                parts.append(scene)
            if ocr:
                parts.append(ocr)

        return self.config.separator.join(parts)
```

### Video Chunk Storage

```python
# processors/video/chunk_storage.py
from dataclasses import dataclass
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
import logging

logger = logging.getLogger(__name__)

class VideoChunkStorage:
    """Stores video chunks in PostgreSQL."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def store_chunks(
        self,
        chunks: list["VideoChunk"]
    ) -> int:
        """Store video chunks in database."""
        if not chunks:
            return 0

        records = [
            {
                "id": uuid4(),
                "video_id": chunk.video_id,
                "chunk_index": chunk.chunk_index,
                "start_time_ms": chunk.start_time_ms,
                "end_time_ms": chunk.end_time_ms,
                "transcript_text": chunk.transcript_text or None,
                "scene_description": chunk.scene_description or None,
                "ocr_text": chunk.ocr_text or None,
                "fused_text": chunk.fused_text,
                "keyframe_path": chunk.keyframe_path,
                "source_modalities": chunk.source_modalities
            }
            for chunk in chunks
        ]

        stmt = insert(VideoChunkModel).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["video_id", "chunk_index"],
            set_={
                "transcript_text": stmt.excluded.transcript_text,
                "scene_description": stmt.excluded.scene_description,
                "ocr_text": stmt.excluded.ocr_text,
                "fused_text": stmt.excluded.fused_text
            }
        )

        await self.session.execute(stmt)
        await self.session.commit()

        logger.info(f"Stored {len(records)} video chunks")
        return len(records)

    async def get_chunks(
        self,
        video_id: UUID
    ) -> list[dict]:
        """Retrieve all chunks for a video."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(VideoChunkModel)
            .where(VideoChunkModel.video_id == video_id)
            .order_by(VideoChunkModel.chunk_index)
        )

        return [
            {
                "id": str(r.id),
                "chunk_index": r.chunk_index,
                "start_time_ms": r.start_time_ms,
                "end_time_ms": r.end_time_ms,
                "transcript_text": r.transcript_text,
                "scene_description": r.scene_description,
                "ocr_text": r.ocr_text,
                "fused_text": r.fused_text
            }
            for r in result.scalars()
        ]
```

### Database Schema

```sql
CREATE TABLE video_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id UUID NOT NULL REFERENCES source_videos(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_time_ms INTEGER NOT NULL,
    end_time_ms INTEGER NOT NULL,
    transcript_text TEXT,
    scene_description TEXT,
    ocr_text TEXT,
    fused_text TEXT NOT NULL,
    keyframe_path VARCHAR(1000),
    source_modalities TEXT[],
    embedding_id VARCHAR(100),  -- Qdrant point ID
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(video_id, chunk_index)
);

CREATE INDEX idx_video_chunks_video ON video_chunks(video_id);
CREATE INDEX idx_video_chunks_time ON video_chunks(video_id, start_time_ms);
CREATE INDEX idx_video_chunks_fused_text_gin ON video_chunks USING gin(to_tsvector('english', fused_text));
```

### Pipeline Integration

```python
# In VideoProcessingPipeline

async def _run_fusion_stage(
    self,
    transcripts: list["TranscriptSegment"],
    visual_results: dict[int, "VisionAnalysisResult"],
    ocr_results: dict[int, "OCRResult"],
    keyframes: list["ExtractedKeyframe"]
) -> list[VideoChunk]:
    """Fuse all modalities into video chunks."""
    await self._update_progress("fusing_content", 0)

    # Prepare transcript data
    transcript_data = [
        {"start_ms": seg.start_ms, "end_ms": seg.end_ms, "text": seg.text}
        for seg in transcripts
    ]

    # Prepare keyframe data with scene descriptions and OCR
    keyframe_data = []
    for kf in keyframes:
        kf_data = {
            "timestamp_ms": kf.timestamp_ms,
            "frame_index": kf.frame_index,
            "storage_path": str(kf.image_path) if kf.image_path else None,
            "scene_description": None,
            "ocr_text": None
        }

        if kf.frame_index in visual_results:
            result = visual_results[kf.frame_index]
            if result.success:
                kf_data["scene_description"] = result.description

        if kf.frame_index in ocr_results:
            result = ocr_results[kf.frame_index]
            if result.success:
                kf_data["ocr_text"] = result.full_text

        keyframe_data.append(kf_data)

    await self._update_progress("fusing_content", 30)

    # Run fusion
    fusion_service = ContentFusionService(FusionConfig(
        target_chunk_duration_ms=self.options.get("chunk_duration_seconds", 20) * 1000
    ))

    result = fusion_service.fuse_content(
        video_id=self.video_id,
        duration_ms=int(self.video_duration_seconds * 1000),
        transcripts=transcript_data,
        keyframes=keyframe_data
    )

    if not result.success:
        raise ProcessingError(f"Content fusion failed: {result.error}")

    await self._update_progress("fusing_content", 70)

    # Store chunks
    await self.chunk_storage.store_chunks(result.chunks)

    # Update video with chunk count
    await self.video_service.update_chunk_count(self.video_id, len(result.chunks))

    await self._update_progress("fusing_content", 100)

    return result.chunks
```

## Fusion Examples

### Example 1: Presentation Video

**Time range:** 00:01:20 - 00:01:40

| Modality | Content |
|----------|---------|
| Transcript | "As you can see from this chart, our revenue grew by forty percent in Q3" |
| Visual | A person presenting in front of a large screen showing a bar chart with company logo visible |
| OCR | "Q3 Revenue Growth | +40% YoY | Company Corp" |

**Fused text:**
```
[Speech] As you can see from this chart, our revenue grew by forty percent in Q3

[Visual] A person presenting in front of a large screen showing a bar chart with company logo visible

[Text on screen] Q3 Revenue Growth | +40% YoY | Company Corp
```

### Example 2: Sports Highlight

**Time range:** 00:05:00 - 00:05:20

| Modality | Content |
|----------|---------|
| Transcript | "And he scores! What an incredible goal from number seven!" |
| Visual | Soccer player celebrating after scoring, crowd cheering in stadium |
| OCR | "HOME 2 - 1 AWAY | 67:32" |

**Fused text:**
```
[Speech] And he scores! What an incredible goal from number seven!

[Visual] Soccer player celebrating after scoring, crowd cheering in stadium

[Text on screen] HOME 2 - 1 AWAY | 67:32
```

## Configuration

```python
class FusionConfig(BaseSettings):
    chunk_target_duration_seconds: int = 20
    chunk_min_duration_seconds: int = 10
    chunk_max_duration_seconds: int = 30
    chunk_overlap_seconds: int = 2
    include_modality_labels: bool = True

    class Config:
        env_prefix = "FUSION_"
```

## Acceptance Criteria

- [ ] Align transcript, scene descriptions, and OCR by timestamp
- [ ] Create video chunks with combined `fused_text` field
- [ ] Each chunk has: start_time, end_time, transcript, scene_description, ocr_text, fused_text
- [ ] Preserve source attribution in chunk metadata
- [ ] Handle missing modalities (e.g., no speech, no OCR text)

## Testing Requirements

```python
class TestContentFusion:
    def test_creates_chunks_for_duration(self):
        service = ContentFusionService(FusionConfig(target_chunk_duration_ms=20000))
        result = service.fuse_content(
            video_id=uuid4(),
            duration_ms=120000,  # 2 minutes
            transcripts=[],
            keyframes=[]
        )

        # Should create ~6 chunks for 2 minutes at 20s each
        assert len(result.chunks) >= 5
        assert len(result.chunks) <= 7

    def test_aligns_transcript_to_chunks(self):
        service = ContentFusionService()
        transcripts = [
            {"start_ms": 0, "end_ms": 5000, "text": "Hello world"},
            {"start_ms": 5000, "end_ms": 10000, "text": "This is a test"},
            {"start_ms": 25000, "end_ms": 30000, "text": "Second chunk content"}
        ]

        result = service.fuse_content(
            video_id=uuid4(),
            duration_ms=60000,
            transcripts=transcripts,
            keyframes=[]
        )

        # First chunk should have first two transcript segments
        assert "Hello world" in result.chunks[0].transcript_text
        assert "This is a test" in result.chunks[0].transcript_text

    def test_handles_missing_modalities(self):
        service = ContentFusionService()
        result = service.fuse_content(
            video_id=uuid4(),
            duration_ms=30000,
            transcripts=[{"start_ms": 0, "end_ms": 10000, "text": "Only speech"}],
            keyframes=[]
        )

        chunk = result.chunks[0]
        assert chunk.transcript_text == "Only speech"
        assert chunk.scene_description == ""
        assert chunk.ocr_text == ""
        assert "transcript" in chunk.source_modalities
        assert "visual" not in chunk.source_modalities

    def test_deduplicates_scene_descriptions(self):
        service = ContentFusionService()
        keyframes = [
            {"timestamp_ms": 0, "frame_index": 0, "scene_description": "Person at desk"},
            {"timestamp_ms": 5000, "frame_index": 1, "scene_description": "Person at desk. Computer visible."},
            {"timestamp_ms": 10000, "frame_index": 2, "scene_description": "Different scene"}
        ]

        result = service.fuse_content(
            video_id=uuid4(),
            duration_ms=30000,
            transcripts=[],
            keyframes=keyframes
        )

        # Should not repeat "Person at desk" multiple times
        assert result.chunks[0].scene_description.count("Person at desk") == 1

    def test_includes_modality_labels_when_configured(self):
        service = ContentFusionService(FusionConfig(include_modality_labels=True))
        result = service.fuse_content(
            video_id=uuid4(),
            duration_ms=30000,
            transcripts=[{"start_ms": 0, "end_ms": 10000, "text": "Hello"}],
            keyframes=[]
        )

        assert "[Speech]" in result.chunks[0].fused_text
```

## Definition of Done

- [ ] Time-based chunk boundaries calculated correctly
- [ ] Transcript aligned to chunks with overlap handling
- [ ] Keyframe content aligned to chunks
- [ ] Duplicate content deduplicated
- [ ] Fused text generated with all modalities
- [ ] Missing modalities handled gracefully
- [ ] Chunks stored in PostgreSQL
- [ ] Source modalities tracked per chunk
- [ ] >90% test coverage
