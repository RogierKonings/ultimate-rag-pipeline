"""Initial schema with documents, chunks, and audit_logs tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-03 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', sa.String(255), nullable=False, comment='External identifier for the source'),
        sa.Column('source_type', sa.String(50), nullable=False, comment='Type of source: FILE, WEB, DB, API'),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False, comment='SHA-256 hash for deduplication'),
        sa.Column('doc_metadata', postgresql.JSONB, server_default='{}', nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('visibility', sa.String(20), server_default='private', nullable=False),
        sa.Column('allowed_groups', postgresql.JSONB, server_default='[]', nullable=False),
        sa.Column('status', sa.String(20), server_default='active', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create documents indexes
    op.create_index('ix_documents_tenant_id', 'documents', ['tenant_id'])
    op.create_index('ix_documents_source_id', 'documents', ['source_id'])
    op.create_index('ix_documents_content_hash', 'documents', ['content_hash'])
    op.create_index('ix_documents_tenant_status', 'documents', ['tenant_id', 'status'])
    
    # Create chunks table
    op.create_table(
        'chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer, nullable=False, comment='Order within document'),
        sa.Column('content', sa.Text, nullable=False, comment='Chunk text content'),
        sa.Column('token_count', sa.Integer, nullable=True),
        sa.Column('embedding_model', sa.String(100), nullable=True),
        sa.Column('embedding_version', sa.String(20), nullable=True),
        sa.Column('chunk_metadata', postgresql.JSONB, server_default='{}', nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), server_default='active', nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create chunks indexes
    op.create_index('ix_chunks_document_id', 'chunks', ['document_id'])
    op.create_index('ix_chunks_tenant_id', 'chunks', ['tenant_id'])
    op.create_index('ix_chunks_document_chunk', 'chunks', ['document_id', 'chunk_index'], unique=True)
    op.create_index('ix_chunks_tenant_status', 'chunks', ['tenant_id', 'status'])
    
    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_source', sa.String(100), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('resource_type', sa.String(100), nullable=True),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('request_id', sa.String(100), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('audit_metadata', postgresql.JSONB, server_default='{}', nullable=False),
        sa.Column('audit_changes', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create audit_logs indexes
    op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('ix_audit_logs_tenant_created', 'audit_logs', ['tenant_id', 'created_at'])
    op.create_index('ix_audit_logs_event_type', 'audit_logs', ['event_type'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('ix_audit_logs_user', 'audit_logs', ['user_id', 'created_at'])


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table('audit_logs')
    op.drop_table('chunks')
    op.drop_table('documents')
