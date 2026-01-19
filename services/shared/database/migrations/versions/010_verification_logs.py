"""Add verification_logs table for answer verification tracking.

Revision ID: 010_verification_logs
Revises: 009_query_feedback
Create Date: 2026-01-19

This migration adds the verification_logs table to store verification
results for quality analysis and correlation with user feedback.

Reference: US-10.4.2 - Verification Metrics & Logging
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010_verification_logs"
down_revision: str | None = "009_query_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="Request ID of the query being verified",
        ),
        sa.Column(
            "tenant_id",
            sa.String(100),
            nullable=True,
            comment="Tenant ID for multi-tenant filtering",
        ),
        sa.Column(
            "score",
            sa.Float,
            nullable=False,
            comment="Verification score (0.0 to 1.0)",
        ),
        sa.Column(
            "label",
            sa.String(20),
            nullable=False,
            comment="Verification label: supported, partial, unsupported, skipped",
        ),
        sa.Column(
            "claims_total",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Total number of claims extracted",
        ),
        sa.Column(
            "claims_supported",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Number of fully supported claims",
        ),
        sa.Column(
            "claims_partial",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Number of partially supported claims",
        ),
        sa.Column(
            "claims_unsupported",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Number of unsupported claims",
        ),
        sa.Column(
            "verification_time_ms",
            sa.Float,
            nullable=False,
            comment="Time taken for verification in milliseconds",
        ),
        sa.Column(
            "claim_details",
            postgresql.JSON,
            nullable=True,
            comment="JSON with individual claim verification details",
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

    # Create indexes for common queries
    op.create_index(
        "ix_verification_logs_request_id",
        "verification_logs",
        ["request_id"],
    )
    op.create_index(
        "ix_verification_logs_tenant_id",
        "verification_logs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_verification_logs_created_at",
        "verification_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_verification_logs_created_at", table_name="verification_logs")
    op.drop_index("ix_verification_logs_tenant_id", table_name="verification_logs")
    op.drop_index("ix_verification_logs_request_id", table_name="verification_logs")
    op.drop_table("verification_logs")
