# Story F4: Answer Cache Invalidation on Ingestion Events

- Type: Feature
- Priority: P2
- Source backlog item: F4

## Goal
Invalidate or refresh answer cache when ingestion updates/deletes/reindexes documents to prevent stale responses.

## In Scope
- Define ingestion-to-orchestrator invalidation trigger path.
- Invalidate by tenant/document scope.
- Add observability for invalidation outcomes.

## Out of Scope
- Full event bus platform migration.

## Context Files
- `services/orchestrator/cache/answer_cache.py`
- `services/orchestrator/workflow/nodes/cache_check.py`
- `crates/rag-ingestion/src/api/routes/documents.rs`
- `crates/rag-ingestion/src/indexing/coordinator.rs`

## Implementation Tasks
1. Define invalidation contract (sync call or async event).
2. Trigger invalidation on delete/reindex/sync impacts.
3. Add metrics/logging for invalidation counts/errors.
4. Add tests for stale-data prevention.

## Acceptance Criteria
- [ ] Document update/delete/reindex causes relevant cache invalidation.
- [ ] Tenant-scoped invalidation is available for bulk changes.
- [ ] Cache metrics reflect invalidation activity.

## Test Plan
- Unit tests for invalidation selection logic.
- Integration test: query cached answer, mutate doc, verify cache miss/new answer.

## Handoff Notes
Reuse existing answer-cache invalidation methods before adding new primitives.
