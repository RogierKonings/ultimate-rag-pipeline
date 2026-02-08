# Story R6: Consolidate Retrieval Execution Path

- Type: Refactor
- Priority: P1
- Source backlog item: R6

## Goal
Adopt one canonical retrieval execution path and remove drift between `SearchPipeline` and route-local logic.

## Problem
`SearchPipeline` exists with incomplete stages, while API routes execute a separate pipeline path and `AppState.pipeline` is not wired.

## Evidence
- `crates/rag-retrieval/src/hybrid/pipeline.rs:233`
- `crates/rag-retrieval/src/hybrid/pipeline.rs:424`
- `crates/rag-retrieval/src/bin/main.rs:164`
- `crates/rag-retrieval/src/api/state.rs:40`

## In Scope
- Decide canonical path.
- Remove dead/duplicate path or route everything through one path.
- Keep response contract stable.

## Out of Scope
- New ranking algorithm work.

## Implementation Tasks
1. Architecture decision record inside PR.
2. Refactor API routes to canonical path.
3. Remove unreachable state/config fields where appropriate.
4. Update benchmarks/tests to target canonical path.

## Acceptance Criteria
- [ ] Only one effective retrieval execution path remains.
- [ ] No TODO-only stages in active runtime path.
- [ ] All retrieval tests pass after refactor.

## Test Plan
- Full retrieval unit/integration suite.
- Benchmark smoke for canonical path.

## Handoff Notes
Keep changes incremental to simplify rollback.
