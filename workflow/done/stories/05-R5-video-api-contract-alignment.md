# Story R5: Video API Contract Alignment Across Frontend and Backend

- Type: Feature
- Priority: P0
- Source backlog item: R5

## Goal
Resolve mismatch where frontend calls video ingestion/retrieval endpoints that are not exposed by current service routers.

## Problem
Video UI and upload flow target endpoints not present in Rust ingestion/retrieval route registration.

## Evidence
- `frontend/src/lib/api/video.ts:44`
- `frontend/src/lib/api/video.ts:95`
- `frontend/src/routes/api/upload/video/+server.ts:84`
- `crates/rag-ingestion/src/api/server.rs:53`
- `crates/rag-retrieval/src/api/server.rs:88`

## In Scope
Choose one path and implement fully:
- Path A: implement missing backend routes (`/api/v1/videos*`, `/api/v1/retrieve/video`, clip/stream endpoints).
- Path B: gate/hide frontend video features by backend capability until routes exist.

## Out of Scope
- Model quality improvements for video search.

## Implementation Tasks
1. Decide Path A or Path B (document decision in PR).
2. Implement route-level contract alignment.
3. Update proxy handlers and frontend API client accordingly.
4. Add e2e check that selected path works without runtime 404s.

## Acceptance Criteria
- [ ] No frontend call to non-existent endpoint in selected mode.
- [ ] Video tab behavior is deterministic (available or gated, not broken).
- [ ] Route contract documented in service README/openapi.

## Test Plan
- Frontend integration tests for video actions.
- Backend API route tests for chosen path.

## Handoff Notes
If Path B is chosen, add explicit UI messaging and capability checks.
