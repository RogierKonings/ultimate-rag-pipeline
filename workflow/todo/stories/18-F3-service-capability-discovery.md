# Story F3: Service Capability Discovery Endpoint

- Type: Feature
- Priority: P2
- Source backlog item: F3

## Goal
Expose runtime capability metadata so frontend can enable/disable features (video, reranker, streaming) safely.

## In Scope
- Add capability endpoint(s) in relevant services.
- Define capability schema with versioning.
- Wire frontend startup/feature gating to this data.

## Out of Scope
- Full remote feature flag platform.

## Context Files
- `crates/rag-llm-gateway/src/api/routes/health.rs`
- `crates/rag-retrieval/src/api/routes/health.rs`
- `frontend/src/routes/+page.svelte`

## Implementation Tasks
1. Define shared capability shape.
2. Implement endpoint in backend service(s).
3. Add frontend capability fetch and gating logic.
4. Add tests for enabled/disabled features.

## Acceptance Criteria
- [ ] Frontend does not call unsupported endpoints when capability is false.
- [ ] Capability payload reflects real runtime readiness.
- [ ] Backward-compatible defaults exist when endpoint unavailable.

## Test Plan
- Backend schema tests for capability payload.
- Frontend integration tests for feature gating.

## Handoff Notes
Prefer additive schema evolution with `version` field.
