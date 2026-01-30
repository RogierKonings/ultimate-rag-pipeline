"""Add embedding_jobs and retrieval_logs tables per architecture schema (US-2.12)

- Add embedding_jobs table for tracking re-embedding jobs
- Add retrieval_logs table for retrieval/evaluation logging

Revision ID: 003_embedding_jobs
Revises: 002_dedup_versioning
Create Date: 2026-01-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '003_embedding_jobs'
down_revision: Union[str, None] = '002_dedup_versioning'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create embedding_jobs table per architecture.md schema
    op.create_table(
        'embedding_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'status',
            sa.String(20),
            server_default='pending',
            nullable=False,
            comment='Job status: pending, running, completed, failed',
        ),
        sa.Column('embedding_model', sa.String(100), nullable=True),
        sa.Column(
            'target_scope',
            postgresql.JSONB,
            server_default='{}',
            nullable=False,
            comment='Filter for documents to re-embed',
        ),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column(
            'stats',
            postgresql.JSONB,
            server_default='{}',
            nullable=False,
            comment='Job statistics: documents_processed, chunks_embedded, etc.',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Create indexes for embedding_jobs
    op.create_index('ix_embedding_jobs_tenant_id', 'embedding_jobs', ['tenant_id'])
    op.create_index('ix_embedding_jobs_status', 'embedding_jobs', ['status'])
    op.create_index(
        'ix_embedding_jobs_tenant_status',
        'embedding_jobs',
        ['tenant_id', 'status'],
    )

    # Create retrieval_logs table per architecture.md schema
    op.create_table(
        'retrieval_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('query', sa.Text, nullable=False),
        sa.Column('effective_query', sa.Text, nullable=True),
        sa.Column(
            'retrieved_chunk_ids',
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
        sa.Column(
            'scores',
            postgresql.JSONB,
            nullable=True,
            comment='Scores for retrieved chunks',
        ),
        sa.Column(
            'filters_applied',
            postgresql.JSONB,
            nullable=True,
            comment='Filters used in the query',
        ),
        sa.Column('latency_ms', sa.Integer, nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Additional fields for ingestion logging (US-2.12)
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'trace_id',
            sa.String(64),
            nullable=True,
            comment='OpenTelemetry trace ID for distributed tracing',
        ),
        sa.Column(
            'span_id',
            sa.String(32),
            nullable=True,
            comment='OpenTelemetry span ID',
        ),
        sa.Column(
            'event_type',
            sa.String(50),
            nullable=True,
            comment='Event type: ingestion, retrieval, evaluation',
        ),
        sa.Column(
            'event_metadata',
            postgresql.JSONB,
            server_default='{}',
            nullable=False,
            comment='Additional event-specific metadata',
        ),
    )

    # Create indexes for retrieval_logs
    op.create_index(
        'ix_retrieval_logs_tenant_id',
        'retrieval_logs',
        ['tenant_id'],
    )
    op.create_index(
        'ix_retrieval_logs_tenant_created',
        'retrieval_logs',
        ['tenant_id', 'created_at'],
    )
    op.create_index(
        'ix_retrieval_logs_trace_id',
        'retrieval_logs',
        ['trace_id'],
    )
    op.create_index(
        'ix_retrieval_logs_document_id',
        'retrieval_logs',
        ['document_id'],
    )
    op.create_index(
        'ix_retrieval_logs_job_id',
        'retrieval_logs',
        ['job_id'],
    )


def downgrade() -> None:
    # Drop retrieval_logs table
    op.drop_index('ix_retrieval_logs_job_id', table_name='retrieval_logs')
    op.drop_index('ix_retrieval_logs_document_id', table_name='retrieval_logs')
    op.drop_index('ix_retrieval_logs_trace_id', table_name='retrieval_logs')
    op.drop_index('ix_retrieval_logs_tenant_created', table_name='retrieval_logs')
    op.drop_index('ix_retrieval_logs_tenant_id', table_name='retrieval_logs')
    op.drop_table('retrieval_logs')

    # Drop embedding_jobs table
    op.drop_index('ix_embedding_jobs_tenant_status', table_name='embedding_jobs')
    op.drop_index('ix_embedding_jobs_status', table_name='embedding_jobs')
    op.drop_index('ix_embedding_jobs_tenant_id', table_name='embedding_jobs')
    op.drop_table('embedding_jobs')
