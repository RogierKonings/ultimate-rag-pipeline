# US-2.11: Deduplication & Versioning (Content Hash)

## Goal
Enforce content-hash deduplication and document versioning aligned with `source_documents`/`chunks` schemas.

## Requirements
- Compute SHA-256 content hash on raw document bytes; store in `source_documents.content_hash`.
- Enforce uniqueness per `tenant_id`, `source_uri`, `content_hash`; increment `version` on re-ingest with new hash.
- Update chunk metadata to include `schema_version`, `embedding_model`, `embedding_version`.
- Provide idempotent ingestion: repeated ingest of identical content returns existing document ID and skips re-embed.

## Acceptance Criteria
- Duplicate ingest with same content_hash does not create new document/chunks; returns existing identifiers.
- New content for same `source_uri` increments `version` and triggers re-chunk/embedding.
- DB constraints/indexes in place per architecture schema; migrations included.
- Tests cover same-hash, new-hash, and multi-tenant cases.

## Verification
- `pytest tests/ingest/test_dedup_versioning.py`
- DB shows unique constraint on `(tenant_id, source_uri, content_hash)`.
