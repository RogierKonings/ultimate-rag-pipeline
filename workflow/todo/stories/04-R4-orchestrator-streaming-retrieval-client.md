# Story R4: Wire Retrieval Client for Streaming Query Path

- Type: Architecture
- Priority: P0
- Source backlog item: R4

## Goal
Enable retrieval-backed context in `/query/stream` by initializing and injecting a real retrieval client.

## Problem
Streaming endpoint checks `app.state.retrieval_client`, but startup sets it to `None`.

## Evidence
- `services/orchestrator/api/app.py:111`
- `services/orchestrator/api/routes/query.py:388`
- `services/orchestrator/api/routes/query.py:393`

## In Scope
- Create retrieval client at startup.
- Store on app state and consume in streaming path.
- Add graceful fallback/logging when retrieval is unavailable.

## Out of Scope
- Non-streaming workflow changes.

## Implementation Tasks
1. Implement retrieval client module or adapter if missing.
2. Initialize it in lifespan startup with config timeouts/retries.
3. Update streaming path to use typed client response.
4. Add tests for both client available/unavailable states.

## Acceptance Criteria
- [ ] Streaming endpoint includes retrieval context when client is healthy.
- [ ] Service still streams without retrieval when client fails.
- [ ] Startup and shutdown lifecycle correctly manages client resources.

## Test Plan
- API test: stream with mocked retrieval success.
- API test: stream with retrieval failure fallback.

## Handoff Notes
Avoid broad exception swallowing in stream loop; record structured failure reasons.
