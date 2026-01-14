"""Content fusion service for multi-modal video content.

This module provides the ContentFusionService class that combines
transcript, scene descriptions, and OCR text into searchable chunks.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from processors.video.transcriber import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass
class FusionConfig:
    """Configuration for content fusion.

    Attributes:
        target_chunk_duration_ms: Target chunk duration in milliseconds.
        min_chunk_duration_ms: Minimum chunk duration.
        max_chunk_duration_ms: Maximum chunk duration.
        overlap_ms: Overlap between consecutive chunks.
        include_modality_labels: Include [Speech], [Visual], etc. labels.
        separator: Separator between modalities.
    """

    target_chunk_duration_ms: int = 20_000  # 20 seconds
    min_chunk_duration_ms: int = 10_000     # 10 seconds
    max_chunk_duration_ms: int = 30_000     # 30 seconds
    overlap_ms: int = 2_000                 # 2 second overlap
    include_modality_labels: bool = True
    separator: str = "\n\n"


@dataclass
class VideoChunk:
    """A fused video content chunk.

    Attributes:
        id: Chunk UUID.
        video_id: Parent video UUID.
        tenant_id: Tenant UUID.
        chunk_index: Index within video.
        start_time_ms: Start time in milliseconds.
        end_time_ms: End time in milliseconds.
        transcript_text: Speech transcript for this time range.
        scene_description: Visual scene descriptions.
        ocr_text: On-screen text from OCR.
        fused_text: Combined text for embedding.
        keyframe_path: Path to representative keyframe.
        keyframe_index: Index of representative keyframe.
        source_modalities: List of included modalities.
        embedding: Optional embedding vector.
        embedding_id: Optional embedding ID in vector store.
    """

    id: UUID
    video_id: UUID
    tenant_id: UUID
    chunk_index: int
    start_time_ms: int
    end_time_ms: int
    transcript_text: str = ""
    scene_description: str = ""
    ocr_text: str = ""
    fused_text: str = ""
    keyframe_path: str | None = None
    keyframe_index: int | None = None
    source_modalities: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    embedding_id: str | None = None

    @property
    def duration_ms(self) -> int:
        """Get chunk duration in milliseconds."""
        return self.end_time_ms - self.start_time_ms

    @property
    def duration_seconds(self) -> float:
        """Get chunk duration in seconds."""
        return self.duration_ms / 1000.0

    @property
    def start_seconds(self) -> float:
        """Get start time in seconds."""
        return self.start_time_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        """Get end time in seconds."""
        return self.end_time_ms / 1000.0

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "id": str(self.id),
            "video_id": str(self.video_id),
            "tenant_id": str(self.tenant_id),
            "chunk_index": self.chunk_index,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "transcript_text": self.transcript_text,
            "scene_description": self.scene_description,
            "ocr_text": self.ocr_text,
            "fused_text": self.fused_text,
            "keyframe_path": self.keyframe_path,
            "keyframe_index": self.keyframe_index,
            "source_modalities": self.source_modalities,
            "embedding_id": self.embedding_id,
        }


@dataclass
class KeyframeContent:
    """Content associated with a keyframe.

    Attributes:
        frame_index: Keyframe index.
        timestamp_ms: Timestamp in milliseconds.
        scene_description: Vision LLM description.
        ocr_text: Extracted OCR text.
        storage_path: Path to keyframe in storage.
    """

    frame_index: int
    timestamp_ms: int
    scene_description: str = ""
    ocr_text: str = ""
    storage_path: str | None = None


class ContentFusionService:
    """Fuses multi-modal video content into searchable chunks.

    Combines transcript segments, scene descriptions, and OCR text
    into time-aligned chunks suitable for embedding and retrieval.

    Example:
        fusion = ContentFusionService(
            config=FusionConfig(target_chunk_duration_ms=20000)
        )
        chunks = fusion.create_chunks(
            video_id=video_id,
            tenant_id=tenant_id,
            duration_ms=video_duration_ms,
            transcript_segments=segments,
            keyframe_contents=keyframes,
        )
    """

    def __init__(self, config: FusionConfig | None = None):
        """Initialize content fusion service.

        Args:
            config: Fusion configuration.
        """
        self.config = config or FusionConfig()

    def create_chunks(
        self,
        video_id: UUID,
        tenant_id: UUID,
        duration_ms: int,
        transcript_segments: list[TranscriptSegment] | None = None,
        keyframe_contents: list[KeyframeContent] | None = None,
    ) -> list[VideoChunk]:
        """Create fused content chunks from video content.

        Args:
            video_id: Video UUID.
            tenant_id: Tenant UUID.
            duration_ms: Video duration in milliseconds.
            transcript_segments: List of transcript segments.
            keyframe_contents: List of keyframe contents with descriptions.

        Returns:
            List of VideoChunk objects.
        """
        transcript_segments = transcript_segments or []
        keyframe_contents = keyframe_contents or []

        # Generate chunk boundaries
        boundaries = self._generate_chunk_boundaries(duration_ms)

        logger.info(
            "Creating %d chunks for video_id=%s (duration=%dms)",
            len(boundaries),
            video_id,
            duration_ms,
        )

        chunks = []
        for i, (start_ms, end_ms) in enumerate(boundaries):
            chunk = self._create_single_chunk(
                video_id=video_id,
                tenant_id=tenant_id,
                chunk_index=i,
                start_ms=start_ms,
                end_ms=end_ms,
                transcript_segments=transcript_segments,
                keyframe_contents=keyframe_contents,
            )
            chunks.append(chunk)

        # Log statistics
        with_transcript = sum(1 for c in chunks if c.transcript_text)
        with_scene = sum(1 for c in chunks if c.scene_description)
        with_ocr = sum(1 for c in chunks if c.ocr_text)

        logger.info(
            "Created %d chunks: %d with transcript, %d with scene, %d with OCR",
            len(chunks),
            with_transcript,
            with_scene,
            with_ocr,
        )

        return chunks

    def _generate_chunk_boundaries(
        self,
        duration_ms: int,
    ) -> list[tuple[int, int]]:
        """Generate chunk time boundaries with overlap.

        Args:
            duration_ms: Total duration in milliseconds.

        Returns:
            List of (start_ms, end_ms) tuples.
        """
        boundaries = []
        target = self.config.target_chunk_duration_ms
        overlap = self.config.overlap_ms

        start_ms = 0
        while start_ms < duration_ms:
            # Calculate end time
            end_ms = min(start_ms + target, duration_ms)

            # Ensure minimum duration (except for last chunk)
            if end_ms - start_ms < self.config.min_chunk_duration_ms:
                if boundaries:
                    # Extend previous chunk instead
                    prev_start, _ = boundaries[-1]
                    boundaries[-1] = (prev_start, end_ms)
                    break
                # First chunk too short, keep it
                boundaries.append((start_ms, end_ms))
                break

            boundaries.append((start_ms, end_ms))

            # Next chunk starts with overlap
            start_ms = end_ms - overlap
            if start_ms >= duration_ms:
                break

        return boundaries

    def _create_single_chunk(
        self,
        video_id: UUID,
        tenant_id: UUID,
        chunk_index: int,
        start_ms: int,
        end_ms: int,
        transcript_segments: list[TranscriptSegment],
        keyframe_contents: list[KeyframeContent],
    ) -> VideoChunk:
        """Create a single fused chunk.

        Args:
            video_id: Video UUID.
            tenant_id: Tenant UUID.
            chunk_index: Chunk index.
            start_ms: Start time.
            end_ms: End time.
            transcript_segments: All transcript segments.
            keyframe_contents: All keyframe contents.

        Returns:
            VideoChunk.
        """
        # Get transcript text for this time range
        transcript_text = self._get_transcript_in_range(
            segments=transcript_segments,
            start_ms=start_ms,
            end_ms=end_ms,
        )

        # Get keyframe content for this time range
        scene_descriptions = []
        ocr_texts = []
        representative_keyframe = None

        for kf in keyframe_contents:
            if start_ms <= kf.timestamp_ms <= end_ms:
                if kf.scene_description:
                    scene_descriptions.append(kf.scene_description)
                if kf.ocr_text:
                    ocr_texts.append(kf.ocr_text)
                # Use first keyframe in range as representative
                if representative_keyframe is None:
                    representative_keyframe = kf

        # Deduplicate scene descriptions
        scene_description = self._deduplicate_text(scene_descriptions)

        # Deduplicate OCR text
        ocr_text = self._deduplicate_text(ocr_texts)

        # Generate fused text
        fused_text = self._generate_fused_text(
            transcript=transcript_text,
            scene=scene_description,
            ocr=ocr_text,
        )

        # Track source modalities
        modalities = []
        if transcript_text:
            modalities.append("speech")
        if scene_description:
            modalities.append("visual")
        if ocr_text:
            modalities.append("ocr")

        return VideoChunk(
            id=uuid4(),
            video_id=video_id,
            tenant_id=tenant_id,
            chunk_index=chunk_index,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            transcript_text=transcript_text,
            scene_description=scene_description,
            ocr_text=ocr_text,
            fused_text=fused_text,
            keyframe_path=representative_keyframe.storage_path if representative_keyframe else None,
            keyframe_index=representative_keyframe.frame_index if representative_keyframe else None,
            source_modalities=modalities,
        )

    def _get_transcript_in_range(
        self,
        segments: list[TranscriptSegment],
        start_ms: int,
        end_ms: int,
    ) -> str:
        """Get transcript text within a time range.

        Args:
            segments: List of transcript segments.
            start_ms: Range start.
            end_ms: Range end.

        Returns:
            Combined transcript text.
        """
        texts = []
        for segment in segments:
            seg_start = segment.start_ms
            seg_end = segment.end_ms

            # Check for overlap
            if seg_end > start_ms and seg_start < end_ms:
                texts.append(segment.text)

        return " ".join(texts).strip()

    def _deduplicate_text(self, texts: list[str]) -> str:
        """Deduplicate and combine text entries.

        Args:
            texts: List of text strings.

        Returns:
            Combined deduplicated text.
        """
        if not texts:
            return ""

        # Simple deduplication by keeping unique sentences
        seen = set()
        unique_texts = []

        for text in texts:
            normalized = text.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique_texts.append(text.strip())

        return " ".join(unique_texts)

    def _generate_fused_text(
        self,
        transcript: str,
        scene: str,
        ocr: str,
    ) -> str:
        """Generate fused text from all modalities.

        Args:
            transcript: Speech transcript.
            scene: Scene description.
            ocr: OCR text.

        Returns:
            Combined fused text.
        """
        parts = []

        if transcript:
            if self.config.include_modality_labels:
                parts.append(f"[Speech] {transcript}")
            else:
                parts.append(transcript)

        if scene:
            if self.config.include_modality_labels:
                parts.append(f"[Visual] {scene}")
            else:
                parts.append(scene)

        if ocr:
            if self.config.include_modality_labels:
                parts.append(f"[Text on screen] {ocr}")
            else:
                parts.append(ocr)

        return self.config.separator.join(parts)


class VideoChunkStorage:
    """Storage service for video chunks.

    Handles database persistence of fused video chunks.
    """

    def __init__(self, database_url: str = ""):
        """Initialize chunk storage.

        Args:
            database_url: PostgreSQL connection URL.
        """
        self.database_url = database_url
        self._pool = None

    async def _get_pool(self):
        """Get or create database connection pool."""
        if self._pool is None:
            import asyncpg

            if not self.database_url:
                from config import get_settings
                settings = get_settings()
                self.database_url = settings.database_url

            self._pool = await asyncpg.create_pool(self.database_url)
        return self._pool

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def store_chunks(
        self,
        chunks: list[VideoChunk],
    ) -> int:
        """Store video chunks in the database.

        Args:
            chunks: List of video chunks.

        Returns:
            Number of chunks stored.
        """
        if not chunks:
            return 0

        pool = await self._get_pool()

        # Delete existing chunks for this video
        video_id = chunks[0].video_id
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM video_chunks WHERE video_id = $1",
                video_id,
            )

        # Insert new chunks
        records = []
        for chunk in chunks:
            records.append((
                chunk.id,
                chunk.video_id,
                chunk.tenant_id,
                chunk.chunk_index,
                chunk.start_time_ms,
                chunk.end_time_ms,
                chunk.transcript_text or None,
                chunk.scene_description or None,
                chunk.ocr_text or None,
                chunk.fused_text,
                chunk.keyframe_path,
                chunk.keyframe_index,
                chunk.source_modalities,
                chunk.embedding_id,
            ))

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO video_chunks (
                    id, video_id, tenant_id, chunk_index,
                    start_time_ms, end_time_ms,
                    transcript_text, scene_description, ocr_text, fused_text,
                    keyframe_path, keyframe_index, source_modalities, embedding_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                records,
            )

        logger.info("Stored %d chunks for video_id=%s", len(chunks), video_id)
        return len(chunks)

    async def get_chunks(
        self,
        video_id: UUID,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """Get chunks for a video.

        Args:
            video_id: Video UUID.
            start_ms: Optional start time filter.
            end_ms: Optional end time filter.

        Returns:
            List of chunk dictionaries.
        """
        pool = await self._get_pool()

        query = """
            SELECT * FROM video_chunks
            WHERE video_id = $1
        """
        params = [video_id]

        if start_ms is not None:
            query += f" AND end_time_ms >= ${len(params) + 1}"
            params.append(start_ms)

        if end_ms is not None:
            query += f" AND start_time_ms <= ${len(params) + 1}"
            params.append(end_ms)

        query += " ORDER BY chunk_index"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [dict(row) for row in rows]

    async def delete_chunks(self, video_id: UUID) -> int:
        """Delete all chunks for a video.

        Args:
            video_id: Video UUID.

        Returns:
            Number of chunks deleted.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM video_chunks WHERE video_id = $1",
                video_id,
            )

        deleted = int(result.split()[-1])
        logger.info("Deleted %d chunks for video_id=%s", deleted, video_id)
        return deleted
