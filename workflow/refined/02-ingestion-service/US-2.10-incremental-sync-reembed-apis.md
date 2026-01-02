# US-2.10: Incremental Sync & Re-embed APIs

## Goal
Expose `/api/v1/ingest/sync` and `/api/v1/ingest/reembed` matching architecture contracts for incremental sync and model migration.

## Requirements
- Implement `/api/v1/ingest/sync` with source config payload; enqueue Celery task for incremental sync.
- Implement `/api/v1/ingest/reembed` to start re-embedding job with target scope; create `embedding_jobs` record.
- Validate requests with Pydantic v2; enforce tenant scoping and auth hooks.
- Return job IDs and estimated completion; include status endpoints or reuse existing job polling.
- OpenAPI docs updated.

## Acceptance Criteria
- Requests/response bodies match `docs/architecture.md` Ingestion Service API examples.
- Celery tasks created with correct payload; `embedding_jobs` table populated.
- 401/403 on missing/invalid auth; 422 on invalid payload.
- OpenAPI reflects endpoints; smoke tests pass.

## Verification
- `pytest tests/api/test_ingest_sync.py::test_sync_success`
- `curl -X POST /api/v1/ingest/reembed …` returns job_id and persists record.
