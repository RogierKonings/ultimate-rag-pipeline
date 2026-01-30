"""Add token_usage and tenant_quotas tables for usage tracking.

Revision ID: 011_token_usage_tracking
Revises: 010_verification_logs
Create Date: 2026-01-19

This migration adds tables for tracking per-tenant token usage
and configuring quota limits.

Reference: US-10.5.4 - Token Usage Accounting
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_token_usage_tracking"
down_revision: str | None = "010_verification_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create token_usage table for daily aggregation
    op.create_table(
        "token_usage",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            sa.String(100),
            nullable=False,
            comment="Tenant identifier",
        ),
        sa.Column(
            "date",
            sa.Date,
            nullable=False,
            comment="Date of usage aggregation",
        ),
        sa.Column(
            "model",
            sa.String(100),
            nullable=False,
            comment="Model identifier (e.g., gpt-4, claude-3)",
        ),
        sa.Column(
            "prompt_tokens",
            sa.BigInteger,
            nullable=False,
            server_default="0",
            comment="Total prompt tokens consumed",
        ),
        sa.Column(
            "completion_tokens",
            sa.BigInteger,
            nullable=False,
            server_default="0",
            comment="Total completion tokens generated",
        ),
        sa.Column(
            "embedding_tokens",
            sa.BigInteger,
            nullable=False,
            server_default="0",
            comment="Total embedding tokens processed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        # Unique constraint for upsert operations
        sa.UniqueConstraint(
            "tenant_id", "date", "model", name="uq_usage_tenant_date_model"
        ),
    )

    # Create indexes for common query patterns
    op.create_index("ix_token_usage_tenant_id", "token_usage", ["tenant_id"])
    op.create_index("ix_token_usage_date", "token_usage", ["date"])
    op.create_index("ix_token_usage_tenant_date", "token_usage", ["tenant_id", "date"])

    # Create tenant_quotas table for quota configuration
    op.create_table(
        "tenant_quotas",
        sa.Column(
            "tenant_id",
            sa.String(100),
            primary_key=True,
            comment="Tenant identifier",
        ),
        sa.Column(
            "monthly_token_limit",
            sa.BigInteger,
            nullable=True,
            comment="Monthly token limit (NULL = unlimited)",
        ),
        sa.Column(
            "quota_enabled",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="Whether quota enforcement is enabled",
        ),
        sa.Column(
            "alert_threshold_percent",
            sa.BigInteger,
            nullable=False,
            server_default="80",
            comment="Alert when usage exceeds this percentage",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_quotas")
    op.drop_index("ix_token_usage_tenant_date", table_name="token_usage")
    op.drop_index("ix_token_usage_date", table_name="token_usage")
    op.drop_index("ix_token_usage_tenant_id", table_name="token_usage")
    op.drop_table("token_usage")
