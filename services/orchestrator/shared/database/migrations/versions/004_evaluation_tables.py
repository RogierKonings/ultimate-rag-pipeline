"""
Evaluation tables for RAG quality evaluation.

Revision ID: 004_evaluation_tables
Revises: 003_embedding_jobs
Create Date: 2024-01-12

Tables created:
- eval_datasets: Evaluation dataset metadata
- eval_examples: Individual evaluation examples
- eval_runs: Evaluation run results
- eval_metrics: Individual metric values per run
- llm_feedback: User feedback on LLM responses
- experiments: A/B test experiments
- experiment_runs: Individual experiment runs
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '004_evaluation_tables'
down_revision = '003_embedding_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create eval_datasets table
    op.create_table(
        'eval_datasets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.String(50), nullable=False, default='1.0.0'),
        sa.Column('config', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('example_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.create_index('ix_eval_datasets_name', 'eval_datasets', ['name'])
    op.create_index('ix_eval_datasets_created_at', 'eval_datasets', ['created_at'])

    # Create eval_examples table
    op.create_table(
        'eval_examples',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('eval_datasets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('contexts', postgresql.JSONB(), nullable=False, default=[]),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('ground_truth', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('ix_eval_examples_dataset_id', 'eval_examples', ['dataset_id'])
    op.create_index('ix_eval_examples_content_hash', 'eval_examples', ['content_hash'])

    # Create eval_runs table
    op.create_table(
        'eval_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('dataset_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('eval_datasets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('dataset_name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='pending'),
        sa.Column('pipeline_version', sa.String(100), nullable=True),
        sa.Column('model_version', sa.String(100), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('total_samples', sa.Integer(), nullable=False, default=0),
        sa.Column('successful_samples', sa.Integer(), nullable=False, default=0),
        sa.Column('failed_samples', sa.Integer(), nullable=False, default=0),
        sa.Column('aggregated_scores', postgresql.JSONB(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_eval_runs_name', 'eval_runs', ['name'])
    op.create_index('ix_eval_runs_dataset_id', 'eval_runs', ['dataset_id'])
    op.create_index('ix_eval_runs_status', 'eval_runs', ['status'])
    op.create_index('ix_eval_runs_started_at', 'eval_runs', ['started_at'])

    # Create eval_metrics table
    op.create_table(
        'eval_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('eval_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(100), nullable=False),
        sa.Column('mean', sa.Float(), nullable=False),
        sa.Column('std', sa.Float(), nullable=False, default=0.0),
        sa.Column('min', sa.Float(), nullable=False),
        sa.Column('max', sa.Float(), nullable=False),
        sa.Column('median', sa.Float(), nullable=False),
        sa.Column('p5', sa.Float(), nullable=True),
        sa.Column('p95', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('run_id', 'metric_name', name='uq_eval_metrics_run_metric'),
    )

    op.create_index('ix_eval_metrics_run_id', 'eval_metrics', ['run_id'])
    op.create_index('ix_eval_metrics_metric_name', 'eval_metrics', ['metric_name'])

    # Create llm_feedback table
    op.create_table(
        'llm_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('trace_id', sa.String(64), nullable=False),
        sa.Column('span_id', sa.String(32), nullable=True),
        sa.Column('feedback_type', sa.String(50), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('correction', sa.Text(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(100), nullable=True),
        sa.Column('session_id', sa.String(100), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('ix_llm_feedback_trace_id', 'llm_feedback', ['trace_id'])
    op.create_index('ix_llm_feedback_feedback_type', 'llm_feedback', ['feedback_type'])
    op.create_index('ix_llm_feedback_user_id', 'llm_feedback', ['user_id'])
    op.create_index('ix_llm_feedback_created_at', 'llm_feedback', ['created_at'])
    op.create_index('ix_llm_feedback_score', 'llm_feedback', ['score'])

    # Create experiments table
    op.create_table(
        'experiments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('hypothesis', sa.Text(), nullable=True),
        sa.Column('experiment_type', sa.String(100), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='active'),
        sa.Column('baseline_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('winning_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conclusion', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_experiments_name', 'experiments', ['name'])
    op.create_index('ix_experiments_status', 'experiments', ['status'])
    op.create_index('ix_experiments_experiment_type', 'experiments', ['experiment_type'])
    op.create_index('ix_experiments_created_at', 'experiments', ['created_at'])

    # Create experiment_runs table
    op.create_table(
        'experiment_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('experiment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('metrics', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('status', sa.String(50), nullable=False, default='running'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('artifacts', postgresql.JSONB(), nullable=False, default=[]),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, default={}),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_experiment_runs_experiment_id', 'experiment_runs', ['experiment_id'])
    op.create_index('ix_experiment_runs_status', 'experiment_runs', ['status'])
    op.create_index('ix_experiment_runs_started_at', 'experiment_runs', ['started_at'])

    # Add foreign keys for experiments
    op.create_foreign_key(
        'fk_experiments_baseline_run',
        'experiments',
        'experiment_runs',
        ['baseline_run_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_experiments_winning_run',
        'experiments',
        'experiment_runs',
        ['winning_run_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Drop foreign keys first
    op.drop_constraint('fk_experiments_winning_run', 'experiments', type_='foreignkey')
    op.drop_constraint('fk_experiments_baseline_run', 'experiments', type_='foreignkey')

    # Drop tables in reverse order
    op.drop_table('experiment_runs')
    op.drop_table('experiments')
    op.drop_table('llm_feedback')
    op.drop_table('eval_metrics')
    op.drop_table('eval_runs')
    op.drop_table('eval_examples')
    op.drop_table('eval_datasets')
