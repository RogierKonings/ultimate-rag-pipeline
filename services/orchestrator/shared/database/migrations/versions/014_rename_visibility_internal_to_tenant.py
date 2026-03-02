"""Rename visibility 'internal' to 'tenant' in source_documents.

Revision ID: 014_rename_visibility_internal
Revises: 013_add_video_tags
Create Date: 2026-02-06

Aligns the database with the canonical Visibility enum in rag-types,
which uses 'tenant' instead of 'internal'.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_rename_visibility_internal"
down_revision: str | None = "013_add_video_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE documents SET visibility = 'tenant' WHERE visibility = 'internal'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE documents SET visibility = 'internal' WHERE visibility = 'tenant'"
    )
