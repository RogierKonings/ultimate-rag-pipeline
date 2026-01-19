"""Add query_feedback table for user feedback storage.

Revision ID: 009_query_feedback
Revises: 008_tenant_isolation
Create Date: 2026-01-19

This migration adds the query_feedback table to store user feedback
on RAG query responses for quality monitoring and improvement.

Reference: US-10.3.3 - Business & Quality Metrics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "009_query_feedback"
down_revision: str | None = "008_tenant_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_feedback",
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
            index=True,
            comment="Request ID of the query being rated",
        ),
        sa.Column(
            "tenant_id",
            sa.String(100),
            nullable=True,
            index=True,
            comment="Tenant ID for multi-tenant filtering",
        ),
        sa.Column(
            "rating",
            sa.Integer,
            nullable=False,
            comment="User rating from 1 (poor) to 5 (excellent)",
        ),
        sa.Column(
            "feedback_type",
            sa.String(50),
            nullable=False,
            server_default="general",
            comment="Type of feedback: helpful, unhelpful, wrong, general",
        ),
        sa.Column(
            "comment",
            sa.Text,
            nullable=True,
            comment="Optional user comment",
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            nullable=True,
            index=True,
            comment="Session ID for context",
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

    # Create index for querying feedback by request
    op.create_index(
        "ix_query_feedback_request_tenant",
        "query_feedback",
        ["request_id", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_feedback_request_tenant", table_name="query_feedback")
    op.drop_table("query_feedback")
