# Story F1: Frontend SSE Consumption for Streaming Query

- Type: Feature
- Priority: P2
- Source backlog item: F1

## Goal
Add client-side streaming support for `/api/v1/query/stream` to improve time-to-first-token and long-answer UX.

## In Scope
- Build frontend stream client for SSE events.
- Add UI state for START/DELTA/CITATIONS/DONE/ERROR.
- Keep existing synchronous query path as fallback.

## Out of Scope
- New model routing behavior.

## Context Files
- `services/orchestrator/api/routes/query.py`
- `frontend/src/lib/stores/search.ts`
- `frontend/src/lib/components/AnswerCard.svelte`

## Implementation Tasks
1. Add streaming API method in frontend API layer.
2. Extend search store for incremental response updates.
3. Update answer UI to render partial content and final citations.
4. Add cancel/retry behavior.

## Acceptance Criteria
- [ ] User sees partial response tokens while generation is in progress.
- [ ] Final response and citations match completed stream payload.
- [ ] Fallback to sync query works when stream fails.

## Test Plan
- Store-level tests for SSE event handling.
- Component tests for streaming UI states.

## Handoff Notes
Handle reconnect/cancellation cleanly to avoid duplicate streams.
