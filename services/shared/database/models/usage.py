"""
Token usage tracking models for quota management and billing.

US-10.5.4: Token Usage Accounting
"""

import uuid
from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin


class TokenUsage(Base, TimestampMixin):
    """
    Daily token usage aggregation per tenant and model.

    Usage data is buffered in Redis and periodically flushed to this table.
    Each row represents one day's usage for a specific tenant/model combination.
    """

    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    embedding_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "date", "model", name="uq_usage_tenant_date_model"),
        Index("ix_token_usage_tenant_id", "tenant_id"),
        Index("ix_token_usage_date", "date"),
        Index("ix_token_usage_tenant_date", "tenant_id", "date"),
    )

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens (prompt + completion + embedding)."""
        return self.prompt_tokens + self.completion_tokens + self.embedding_tokens


class TenantQuota(Base, TimestampMixin):
    """
    Quota configuration per tenant.

    When quota_enabled is True and monthly_token_limit is set,
    requests exceeding the limit will receive a 429 response.
    """

    __tablename__ = "tenant_quotas"

    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    monthly_token_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, default=None
    )  # None = unlimited
    quota_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alert_threshold_percent: Mapped[int] = mapped_column(
        BigInteger, default=80, nullable=False
    )  # Alert when usage exceeds this percentage

    def is_unlimited(self) -> bool:
        """Check if tenant has unlimited quota."""
        return not self.quota_enabled or self.monthly_token_limit is None
