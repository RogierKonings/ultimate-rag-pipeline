# Story R12: Unify Frontend API Proxy Handlers

- Type: Refactor
- Priority: P2
- Source backlog item: R12

## Goal
Consolidate duplicated proxy route logic into a shared utility with consistent forwarding and error mapping.

## Problem
Proxy handlers for ingestion/retrieval/orchestrator duplicate logic and differ in `fetch` usage and URL composition.

## Evidence
- `frontend/src/routes/api/proxy/retrieval/[...path]/+server.ts:7`
- `frontend/src/routes/api/proxy/ingestion/[...path]/+server.ts:21`
- `frontend/src/routes/api/proxy/orchestrator/[...path]/+server.ts:7`

## In Scope
- Build shared proxy helper utility.
- Migrate all three proxy handlers to helper.
- Standardize header handling, error translation, and method forwarding.

## Out of Scope
- Frontend state store redesign.

## Implementation Tasks
1. Create proxy helper (`forwardProxyRequest` style).
2. Migrate three proxy route modules.
3. Ensure SSR-safe `event.fetch` usage is consistent.
4. Add proxy tests (happy path + upstream error).

## Acceptance Criteria
- [ ] Single implementation path for proxy forwarding.
- [ ] Same error payload behavior across all proxies.
- [ ] Existing frontend API modules continue to work unchanged.

## Test Plan
- Unit tests for helper.
- Integration tests for each proxy route.

## Handoff Notes
Keep ingestion filename normalization behavior preserved or move it into a deliberate adapter layer.
