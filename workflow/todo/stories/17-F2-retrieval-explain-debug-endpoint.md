# Story F2: Retrieval Explain/Debug Endpoint

- Type: Feature
- Priority: P2
- Source backlog item: F2

## Goal
Expose a debug endpoint that returns retrieval stage-level diagnostics for triage and tuning.

## In Scope
- Add endpoint (e.g. `/api/v1/retrieve/explain`).
- Include effective config, stage timings, components used/skipped, top candidates pre/post stages.
- Guard endpoint for internal/admin use.

## Out of Scope
- Public exposure of sensitive scoring internals.

## Context Files
- `crates/rag-retrieval/src/api/routes/search.rs`
- `crates/rag-retrieval/src/api/responses.rs`
- `crates/rag-retrieval/src/observability/*`

## Implementation Tasks
1. Define explain response schema.
2. Capture debug data from pipeline/search path.
3. Add route and auth guard.
4. Add tests and docs.

## Acceptance Criteria
- [ ] Endpoint returns deterministic explain payload for a request.
- [ ] Sensitive fields are redacted or omitted.
- [ ] Endpoint is disabled or protected in production as intended.

## Test Plan
- Route tests for auth and payload schema.
- Unit tests for debug payload generation.

## Handoff Notes
Do not break existing `debug` field in standard retrieve response.
