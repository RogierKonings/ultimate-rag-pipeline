"""
QueryFeedback model for storing user feedback on RAG responses.

Reference: US-10.3.3 - Business & Quality Metrics
"""

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class QueryFeedback(Base, TimestampMixin):
    """
    User feedback on RAG query responses.

    Stores feedback submitted by users which is correlated with the original
    query via request_id. Used for quality monitoring and improvement.
    """

    __tablename__ = "query_feedback"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Correlation to original query
    request_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Request ID of the query being rated",
    )

    # Tenant context
    tenant_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Tenant ID for multi-tenant filtering",
    )

    # Feedback data
    rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="User rating from 1 (poor) to 5 (excellent)",
    )

    feedback_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        comment="Type of feedback: helpful, unhelpful, wrong, general",
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional user comment",
    )

    # Session context
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="Session ID for context",
    )

    def __repr__(self) -> str:
        return (
            f"<QueryFeedback(id={self.id}, request_id={self.request_id}, "
            f"rating={self.rating}, type={self.feedback_type})>"
        )
