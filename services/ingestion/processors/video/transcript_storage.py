"""Transcript storage service for video processing.

This module provides the TranscriptStorage class that persists transcript
segments to the PostgreSQL database.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from processors.video.exceptions import VideoProcessingError
from processors.video.transcriber import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass
class TranscriptStorageConfig:
    """Configuration for transcript storage.

    Attributes:
        database_url: PostgreSQL connection URL.
        batch_size: Number of segments to insert per batch.
    """

    database_url: str = ""
    batch_size: int = 100


class TranscriptStorage:
    """Stores transcript segments in the database.

    Handles batch insertion and upsert operations for transcript
    segments from video transcription.

    Example:
        storage = TranscriptStorage(config)
        await storage.store_segments(
            video_id=video_id,
            tenant_id=tenant_id,
            segments=transcript_segments,
        )
    """

    def __init__(self, config: TranscriptStorageConfig | None = None):
        """Initialize transcript storage.

        Args:
            config: Storage configuration.
        """
        self.config = config or TranscriptStorageConfig()
        self._pool = None

    async def _get_pool(self):
        """Get or create database connection pool."""
        if self._pool is None:
            import asyncpg

            if not self.config.database_url:
                from config import get_settings
                settings = get_settings()
                self.config.database_url = settings.database_url

            self._pool = await asyncpg.create_pool(self.config.database_url)
        return self._pool

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def store_segments(
        self,
        video_id: UUID,
        tenant_id: UUID,
        segments: list[TranscriptSegment],
        language: str | None = None,
    ) -> int:
        """Store transcript segments in the database.

        Args:
            video_id: Video identifier.
            tenant_id: Tenant identifier.
            segments: List of transcript segments.
            language: Detected language code.

        Returns:
            Number of segments stored.

        Raises:
            VideoProcessingError: If storage fails.
        """
        if not segments:
            logger.info("No segments to store for video_id=%s", video_id)
            return 0

        try:
            pool = await self._get_pool()

            # Delete existing segments for this video (for reprocessing)
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM video_transcripts WHERE video_id = $1",
                    video_id,
                )

            # Insert segments in batches
            total_stored = 0
            for i in range(0, len(segments), self.config.batch_size):
                batch = segments[i:i + self.config.batch_size]
                stored = await self._insert_batch(
                    video_id=video_id,
                    segments=batch,
                    language=language,
                )
                total_stored += stored

            logger.info(
                "Stored %d transcript segments for video_id=%s",
                total_stored,
                video_id,
            )

            return total_stored

        except Exception as e:
            raise VideoProcessingError(f"Failed to store transcript: {e}") from e

    async def _insert_batch(
        self,
        video_id: UUID,
        segments: list[TranscriptSegment],
        language: str | None,
    ) -> int:
        """Insert a batch of segments.

        Args:
            video_id: Video identifier.
            segments: Batch of segments to insert.
            language: Language code.

        Returns:
            Number of segments inserted.
        """
        import json

        pool = await self._get_pool()

        # Prepare batch data
        records = []
        for segment in segments:
            records.append((
                video_id,
                segment.id,
                segment.start_ms,
                segment.end_ms,
                segment.text,
                json.dumps(segment.words) if segment.words else None,
                language or "unknown",
                segment.confidence,
            ))

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO video_transcripts (
                    video_id, segment_index, start_ms, end_ms,
                    text, words_json, language, confidence
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                records,
            )

        return len(records)

    async def get_segments(
        self,
        video_id: UUID,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """Get transcript segments for a video.

        Args:
            video_id: Video identifier.
            start_ms: Optional start time filter.
            end_ms: Optional end time filter.

        Returns:
            List of segment dictionaries.
        """
        pool = await self._get_pool()

        query = """
            SELECT id, segment_index, start_ms, end_ms, text,
                   words_json, language, confidence
            FROM video_transcripts
            WHERE video_id = $1
        """
        params = [video_id]

        if start_ms is not None:
            query += " AND end_ms >= $2"
            params.append(start_ms)

        if end_ms is not None:
            query += f" AND start_ms <= ${len(params) + 1}"
            params.append(end_ms)

        query += " ORDER BY segment_index"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        import json
        segments = []
        for row in rows:
            segments.append({
                "id": str(row["id"]),
                "segment_index": row["segment_index"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
                "text": row["text"],
                "words": json.loads(row["words_json"]) if row["words_json"] else [],
                "language": row["language"],
                "confidence": row["confidence"],
            })

        return segments

    async def get_text_at_time(
        self,
        video_id: UUID,
        timestamp_ms: int,
    ) -> str | None:
        """Get transcript text at a specific timestamp.

        Args:
            video_id: Video identifier.
            timestamp_ms: Timestamp in milliseconds.

        Returns:
            Transcript text or None.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT text FROM video_transcripts
                WHERE video_id = $1
                  AND start_ms <= $2
                  AND end_ms >= $2
                ORDER BY segment_index
                LIMIT 1
                """,
                video_id,
                timestamp_ms,
            )

        return row["text"] if row else None

    async def get_full_transcript(self, video_id: UUID) -> str:
        """Get the full transcript text for a video.

        Args:
            video_id: Video identifier.

        Returns:
            Full transcript as a single string.
        """
        segments = await self.get_segments(video_id)
        return " ".join(s["text"] for s in segments)

    async def delete_segments(self, video_id: UUID) -> int:
        """Delete all transcript segments for a video.

        Args:
            video_id: Video identifier.

        Returns:
            Number of segments deleted.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM video_transcripts WHERE video_id = $1",
                video_id,
            )

        # Parse "DELETE N" response
        deleted = int(result.split()[-1])
        logger.info("Deleted %d transcript segments for video_id=%s", deleted, video_id)

        return deleted
