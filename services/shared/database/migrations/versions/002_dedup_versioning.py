"""Add deduplication and versioning support (US-2.11)

- Rename source_id to source_uri and increase length
- Add version column to documents
- Add unique constraint on (tenant_id, source_uri, content_hash)
- Add schema_version column to chunks

Revision ID: 002_dedup_versioning
Revises: 001_initial
Create Date: 2026-01-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_dedup_versioning'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename source_id to source_uri and change type to accommodate longer URIs
    op.alter_column(
        'documents',
        'source_id',
        new_column_name='source_uri',
        type_=sa.String(2048),
        comment='Canonical URI for the source (e.g., file path, URL, database record)',
    )

    # 2. Drop old index and create new one with updated column name
    op.drop_index('ix_documents_source_id', table_name='documents')
    op.create_index('ix_documents_source_uri', 'documents', ['source_uri'])

    # 3. Add version column to documents (default to 1 for existing records)
    op.add_column(
        'documents',
        sa.Column(
            'version',
            sa.Integer,
            nullable=False,
            server_default='1',
            comment='Document version, incremented on re-ingest with new content',
        )
    )

    # 4. Add unique constraint for deduplication (tenant_id, source_uri, content_hash)
    op.create_index(
        'uq_documents_tenant_source_hash',
        'documents',
        ['tenant_id', 'source_uri', 'content_hash'],
        unique=True,
    )

    # 5. Add schema_version column to chunks
    op.add_column(
        'chunks',
        sa.Column(
            'schema_version',
            sa.String(20),
            nullable=False,
            server_default='1.0',
            comment='Schema version for chunk structure compatibility',
        )
    )


def downgrade() -> None:
    # Remove schema_version from chunks
    op.drop_column('chunks', 'schema_version')

    # Remove unique constraint
    op.drop_index('uq_documents_tenant_source_hash', table_name='documents')

    # Remove version column
    op.drop_column('documents', 'version')

    # Rename source_uri back to source_id
    op.drop_index('ix_documents_source_uri', table_name='documents')
    op.alter_column(
        'documents',
        'source_uri',
        new_column_name='source_id',
        type_=sa.String(255),
        comment='External identifier for the source',
    )
    op.create_index('ix_documents_source_id', 'documents', ['source_id'])
