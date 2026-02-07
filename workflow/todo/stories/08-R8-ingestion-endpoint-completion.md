# Story R8: Complete Ingestion Lifecycle Endpoints

- Type: Feature
- Priority: P1
- Source backlog item: R8

## Goal
Finish currently partial ingestion/document lifecycle endpoints so API semantics match route contracts.

## Problem
Several ingestion endpoints return placeholders, partial behavior, or single-store operations only.

## Evidence
- `crates/rag-ingestion/src/api/routes/documents.rs:159`
- `crates/rag-ingestion/src/api/routes/documents.rs:176`
- `crates/rag-ingestion/src/api/routes/documents.rs:216`
- `crates/rag-ingestion/src/api/routes/documents.rs:345`
- `crates/rag-ingestion/src/api/routes/ingest.rs:269`

## In Scope
- Implement real sync status lookup.
- Implement get-document by ID.
- Implement hard delete propagation to Qdrant/OpenSearch.
- Implement reindex orchestration.
- Implement sync/reembed background job dispatching.

## Out of Scope
- New ingestion source connectors.

## Implementation Tasks
1. Add missing repository/service calls.
2. Route all multi-store write/delete via coordinator path.
3. Update job payload/worker handling for sync and reembed.
4. Add tests for each endpoint state transition.

## Acceptance Criteria
- [ ] All exposed lifecycle endpoints perform non-placeholder behavior.
- [ ] Hard delete removes data from all configured stores.
- [ ] Reindex enqueues and executes observable workflow.

## Test Plan
- API route tests with mocked stores.
- Integration tests for delete/reindex consistency.

## Handoff Notes
Document idempotency and retry semantics for all lifecycle operations.
