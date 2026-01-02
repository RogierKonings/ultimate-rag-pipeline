# US-6.10: Evaluation Data Persistence

## Goal
Persist evaluation datasets, examples, and runs per architecture Postgres schema and integrate with Ragas/Phoenix outputs.

## Requirements
- Migrations for `eval_datasets`, `eval_examples`, `eval_runs` per `docs/architecture.md`.
- Ragas/Phoenix evaluation jobs write results into `eval_runs` with metrics JSONB and pipeline/model versions.
- Provide API/CLI to list datasets/runs and retrieve metrics.
- Ensure trace/log context for eval jobs; metrics emitted for eval duration and success/failure.

## Acceptance Criteria
- Eval run persists metrics and links to dataset/examples; schema matches architecture.
- Phoenix/Ragas pipelines write to DB without manual steps; retries on transient errors.
- Tests cover migrations and CRUD for datasets/runs.
- Dashboards can read metrics from DB or via exporter.

## Verification
- `alembic upgrade head && pytest tests/evaluation/test_eval_persistence.py`
- Run sample eval job; inspect `eval_runs` row for metrics and timestamps.
