"""
Base model class and common mixins for SQLAlchemy models.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    Provides common functionality and type hints for all models.
    """

    # Type annotation map for common types
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
    }


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at timestamp columns.

    Usage:
        class MyModel(Base, TimestampMixin):
            ...
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Mixin that adds soft delete support via status and deleted_at columns.

    Usage:
        class MyModel(Base, SoftDeleteMixin):
            ...
    """

    status: Mapped[str] = mapped_column(
        default="active",
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def soft_delete(self) -> None:
        """Mark this record as deleted."""
        self.status = "deleted"
        self.deleted_at = datetime.utcnow()

    @property
    def is_deleted(self) -> bool:
        """Check if this record is soft deleted."""
        return self.status == "deleted"
