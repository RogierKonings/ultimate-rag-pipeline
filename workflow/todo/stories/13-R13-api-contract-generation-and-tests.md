# Story R13: Generate Shared API Contracts and Add Contract Tests

- Type: Architecture
- Priority: P2
- Source backlog item: R13

## Goal
Prevent API drift between backend response models and frontend TypeScript types.

## Problem
Backend query response contains fields not represented in frontend type definitions.

## Evidence
- `services/orchestrator/api/models/responses.py:110`
- `services/orchestrator/api/models/responses.py:128`
- `frontend/src/lib/api/types.ts:86`

## In Scope
- Establish a contract source of truth (OpenAPI/schema-based generation).
- Generate frontend types from backend schema.
- Add CI contract checks.

## Out of Scope
- Full frontend store refactor.

## Implementation Tasks
1. Define generation pipeline (script/tooling) for TS types.
2. Replace manual duplicated interfaces where feasible.
3. Add CI job that fails on stale generated contracts.
4. Add at least one end-to-end contract assertion.

## Acceptance Criteria
- [ ] `QueryResponse` frontend type includes quality/cache fields from backend.
- [ ] Generated contract files are reproducible.
- [ ] CI detects drift automatically.

## Test Plan
- Contract generation snapshot test.
- API-to-TS compatibility test in CI.

## Handoff Notes
Prefer incremental migration; keep compatibility shims until all callers are updated.
