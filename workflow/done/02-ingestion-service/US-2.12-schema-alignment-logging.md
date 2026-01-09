# US-2.12: Schema Alignment & Logging Persistence

## Goal
Ensure ingestion persists data to architecture-defined schemas and captures logs/metrics for downstream evaluation.

## Requirements
- Validate ORM/migrations match `docs/architecture.md` schemas for `source_documents`, `chunks`, `embedding_jobs`.
- Persist ingestion/retrieval/eval log records where applicable (e.g., ingestion status events into `retrieval_logs`-compatible structure if shared).
- Enforce embedding dimensions (1024) and chunking defaults (300 target, 512 max, 50 overlap) via config validation.
- Add structured logging for ingest events with trace IDs; expose metrics for ingest latency and documents ingested.

## Acceptance Criteria
- Migration check passes against schema definitions; discrepancies resolved or documented.
- Logs emitted with tenant_id/document_id/job_id and trace context; metrics exported.
- CI test ensures embedding dimension/chunk config match defaults.
- OpenTelemetry/Prometheus hooks enabled for ingest API and tasks.

## Verification
- `alembic upgrade head && pytest tests/ingest/test_schema_alignment.py`
- `curl /metrics` shows ingest counters/histograms; logs include trace IDs.
