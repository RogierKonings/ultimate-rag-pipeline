"""
Feedback Collection.

Provides feedback collection and storage for LLM traces.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from .config import PhoenixConfig

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of feedback."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"
    CORRECTION = "correction"
    ANNOTATION = "annotation"


@dataclass
class Feedback:
    """A single feedback entry."""

    id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    span_id: Optional[str] = None

    feedback_type: FeedbackType = FeedbackType.RATING
    score: Optional[float] = None  # 0.0 - 1.0
    label: Optional[str] = None  # e.g., "relevant", "irrelevant"
    correction: Optional[str] = None  # Corrected response
    comment: Optional[str] = None

    user_id: Optional[str] = None
    session_id: Optional[str] = None

    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "feedback_type": self.feedback_type.value,
            "score": self.score,
            "label": self.label,
            "correction": self.correction,
            "comment": self.comment,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Feedback":
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.utcnow()

        return cls(
            id=data.get("id", str(uuid4())),
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id"),
            feedback_type=FeedbackType(data.get("feedback_type", "rating")),
            score=data.get("score"),
            label=data.get("label"),
            correction=data.get("correction"),
            comment=data.get("comment"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            created_at=created_at,
            metadata=data.get("metadata", {}),
        )


class FeedbackCollector:
    """
    Collects and stores user feedback for LLM traces.

    Stores feedback in PostgreSQL and optionally sends to Phoenix.
    """

    def __init__(self, config: Optional[PhoenixConfig] = None):
        """
        Initialize feedback collector.

        Args:
            config: Phoenix configuration
        """
        self.config = config or PhoenixConfig.from_env()
        self._pool = None

    async def _get_pool(self):
        """Get or create database connection pool."""
        if self._pool is None:
            if not self.config.postgres_url:
                raise ValueError("PostgreSQL URL required for feedback storage")

            import asyncpg

            self._pool = await asyncpg.create_pool(self.config.postgres_url)
        return self._pool

    async def record_feedback(
        self,
        trace_id: str,
        score: Optional[float] = None,
        feedback_type: FeedbackType = FeedbackType.RATING,
        label: Optional[str] = None,
        correction: Optional[str] = None,
        comment: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        span_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Feedback:
        """
        Record user feedback for a trace.

        Args:
            trace_id: The trace ID to associate feedback with
            score: Numeric score (0.0 - 1.0)
            feedback_type: Type of feedback
            label: Label/category for the feedback
            correction: Corrected response
            comment: Free-form comment
            user_id: User who provided feedback
            session_id: Session identifier
            span_id: Specific span ID (optional)
            metadata: Additional metadata

        Returns:
            The recorded Feedback object
        """
        feedback = Feedback(
            trace_id=trace_id,
            span_id=span_id,
            feedback_type=feedback_type,
            score=score,
            label=label,
            correction=correction,
            comment=comment,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )

        # Store in PostgreSQL
        await self._store_feedback(feedback)

        # Send to Phoenix
        if self.config.enabled:
            await self._send_to_phoenix(feedback)

        logger.info(f"Recorded feedback {feedback.id} for trace {trace_id}")
        return feedback

    async def record_thumbs_up(
        self,
        trace_id: str,
        user_id: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Feedback:
        """Record a thumbs up."""
        return await self.record_feedback(
            trace_id=trace_id,
            score=1.0,
            feedback_type=FeedbackType.THUMBS_UP,
            label="positive",
            user_id=user_id,
            comment=comment,
        )

    async def record_thumbs_down(
        self,
        trace_id: str,
        user_id: Optional[str] = None,
        comment: Optional[str] = None,
        correction: Optional[str] = None,
    ) -> Feedback:
        """Record a thumbs down with optional correction."""
        return await self.record_feedback(
            trace_id=trace_id,
            score=0.0,
            feedback_type=FeedbackType.THUMBS_DOWN,
            label="negative",
            user_id=user_id,
            comment=comment,
            correction=correction,
        )

    async def record_rating(
        self,
        trace_id: str,
        rating: int,
        max_rating: int = 5,
        user_id: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Feedback:
        """Record a numeric rating."""
        # Normalize to 0-1 scale
        score = rating / max_rating

        return await self.record_feedback(
            trace_id=trace_id,
            score=score,
            feedback_type=FeedbackType.RATING,
            label=f"{rating}/{max_rating}",
            user_id=user_id,
            comment=comment,
            metadata={"raw_rating": rating, "max_rating": max_rating},
        )

    async def record_correction(
        self,
        trace_id: str,
        correction: str,
        user_id: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Feedback:
        """Record a correction to the response."""
        return await self.record_feedback(
            trace_id=trace_id,
            score=0.0,  # Corrections imply the original was wrong
            feedback_type=FeedbackType.CORRECTION,
            correction=correction,
            user_id=user_id,
            comment=comment,
        )

    async def _store_feedback(self, feedback: Feedback) -> None:
        """Store feedback in PostgreSQL."""
        import json

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_feedback
                (id, trace_id, span_id, feedback_type, score, label,
                 correction, comment, user_id, session_id, created_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                feedback.id,
                feedback.trace_id,
                feedback.span_id,
                feedback.feedback_type.value,
                feedback.score,
                feedback.label,
                feedback.correction,
                feedback.comment,
                feedback.user_id,
                feedback.session_id,
                feedback.created_at,
                json.dumps(feedback.metadata),
            )

    async def _send_to_phoenix(self, feedback: Feedback) -> None:
        """Send feedback to Phoenix."""
        try:
            import httpx

            payload = {
                "annotation_name": f"user_feedback_{feedback.feedback_type.value}",
                "trace_id": feedback.trace_id,
                "span_id": feedback.span_id,
                "annotator_kind": "HUMAN",
                "result": {
                    "score": feedback.score,
                    "label": feedback.label,
                    "explanation": feedback.comment,
                },
                "metadata": {
                    "user_id": feedback.user_id,
                    "correction": feedback.correction,
                    **feedback.metadata,
                },
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.config.phoenix_url}/v1/annotations",
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()

        except Exception as e:
            logger.warning(f"Failed to send feedback to Phoenix: {e}")

    async def get_feedback_for_trace(
        self,
        trace_id: str,
    ) -> list[Feedback]:
        """
        Get all feedback for a trace.

        Args:
            trace_id: The trace ID

        Returns:
            List of Feedback objects
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM llm_feedback
                WHERE trace_id = $1
                ORDER BY created_at DESC
                """,
                trace_id,
            )

            return [Feedback.from_dict(dict(row)) for row in rows]

    async def get_feedback_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """
        Get feedback summary statistics.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            Summary statistics
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Build query with optional time filters
            query = "SELECT * FROM llm_feedback WHERE 1=1"
            params = []

            if start_time:
                params.append(start_time)
                query += f" AND created_at >= ${len(params)}"

            if end_time:
                params.append(end_time)
                query += f" AND created_at <= ${len(params)}"

            rows = await conn.fetch(query, *params)

            # Calculate statistics
            total = len(rows)
            if total == 0:
                return {
                    "total_feedback": 0,
                    "avg_score": None,
                    "positive_rate": None,
                    "feedback_by_type": {},
                }

            scores = [r["score"] for r in rows if r["score"] is not None]
            positive = sum(1 for s in scores if s >= 0.5)

            by_type = {}
            for row in rows:
                ft = row["feedback_type"]
                if ft not in by_type:
                    by_type[ft] = 0
                by_type[ft] += 1

            return {
                "total_feedback": total,
                "avg_score": sum(scores) / len(scores) if scores else None,
                "positive_rate": positive / len(scores) if scores else None,
                "feedback_by_type": by_type,
                "corrections_count": by_type.get("correction", 0),
            }

    async def get_low_scoring_traces(
        self,
        threshold: float = 0.3,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get traces with low feedback scores.

        Args:
            threshold: Score threshold
            limit: Maximum results

        Returns:
            List of low-scoring traces with feedback
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT trace_id, AVG(score) as avg_score, COUNT(*) as feedback_count
                FROM llm_feedback
                WHERE score IS NOT NULL
                GROUP BY trace_id
                HAVING AVG(score) < $1
                ORDER BY AVG(score) ASC
                LIMIT $2
                """,
                threshold,
                limit,
            )

            return [dict(row) for row in rows]
