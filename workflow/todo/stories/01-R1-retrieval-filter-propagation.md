# Story R1: Retrieval Filter Propagation and Enforcement

- Type: Refactor
- Priority: P0
- Source backlog item: R1

## Goal
Ensure `RetrieveRequest.filters` is actually applied in retrieval execution for hybrid, semantic-only, and keyword-only modes.

## Problem
The API accepts `filters` but currently does not enforce them through the search path.

## Evidence
- `crates/rag-retrieval/src/api/routes/search.rs:158`
- `crates/rag-retrieval/src/api/routes/search.rs:193`
- `crates/rag-retrieval/src/api/routes/search.rs:208`
- `crates/rag-retrieval/src/hybrid/searcher.rs:544`

## In Scope
- Parse request filters into `UnifiedFilter` (or equivalent canonical filter model).
- Pass parsed filters to `HybridSearcher::search*` for all modes.
- Implement filter conversion in:
  - `convert_to_semantic_filters`
  - `convert_to_keyword_filters`
- Add/extend unit/integration tests proving filtering behavior.

## Out of Scope
- New filter schema design.
- ACL model redesign.

## Implementation Tasks
1. Add a parsing helper in API layer to convert raw JSON filters.
2. Wire parsed filter into all mode branches.
3. Implement conversion helpers in `hybrid/searcher.rs`.
4. Add tests for tenant filter and at least one metadata filter.

## Acceptance Criteria
- [ ] A request with `filters` changes returned results deterministically.
- [ ] Behavior works in `hybrid`, `semantic`, and `keyword` modes.
- [ ] Invalid filters return clear 4xx validation errors.
- [ ] Tests cover positive and negative filter cases.

## Test Plan
- Retrieval API route tests for filter pass-through.
- Hybrid searcher tests for conversion correctness.
- One integration test against mock backends.

## Handoff Notes
Use existing `UnifiedFilter` structures first; do not introduce a second filter DSL.
