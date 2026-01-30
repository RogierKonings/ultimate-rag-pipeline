"""
VerificationLog model for storing verification results for analysis.

Reference: US-10.4.2 - Verification Metrics & Logging
"""

import uuid

from sqlalchemy import Float, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class VerificationLog(Base, TimestampMixin):
    """
    Log of verification results for analysis and feedback correlation.

    Stores verification outcomes which can be joined with QueryFeedback
    via request_id for quality analysis and model improvement.
    """

    __tablename__ = "verification_logs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Correlation to original query (joins with query_feedback.request_id)
    request_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Request ID of the query being verified",
    )

    # Tenant context
    tenant_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Tenant ID for multi-tenant filtering",
    )

    # Verification result
    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Verification score (0.0 to 1.0)",
    )

    label: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Verification label: supported, partial, unsupported, skipped",
    )

    # Claim counts
    claims_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of claims extracted",
    )

    claims_supported: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of fully supported claims",
    )

    claims_partial: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of partially supported claims",
    )

    claims_unsupported: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of unsupported claims",
    )

    # Performance
    verification_time_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Time taken for verification in milliseconds",
    )

    # Detailed claim information (optional)
    claim_details: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON with individual claim verification details",
    )

    def __repr__(self) -> str:
        return (
            f"<VerificationLog(id={self.id}, request_id={self.request_id}, "
            f"score={self.score}, label={self.label})>"
        )
