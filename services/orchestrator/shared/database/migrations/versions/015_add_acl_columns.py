"""Add ACL columns to documents for unified access control.

Revision ID: 015_add_acl_columns
Revises: 014_rename_visibility_internal
Create Date: 2026-03-03

Adds owner_id, allowed_users, denied_groups, and denied_users columns
to support the full ACL model across PostgreSQL, Qdrant, and OpenSearch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_add_acl_columns"
down_revision: str | None = "014_rename_visibility_internal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("owner_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("allowed_users", sa.ARRAY(sa.Text()), server_default="{}"),
    )
    op.add_column(
        "documents",
        sa.Column("denied_groups", sa.ARRAY(sa.Text()), server_default="{}"),
    )
    op.add_column(
        "documents",
        sa.Column("denied_users", sa.ARRAY(sa.Text()), server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("documents", "denied_users")
    op.drop_column("documents", "denied_groups")
    op.drop_column("documents", "allowed_users")
    op.drop_column("documents", "owner_id")
