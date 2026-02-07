# Story R2: Retrieval Degradation Contract Implementation

- Type: Architecture
- Priority: P0
- Source backlog item: R2

## Goal
Replace hardcoded degradation metadata with real component availability and degradation mode output from retrieval runtime.

## Problem
API responses expose degradation fields but currently return static/default values.

## Evidence
- `crates/rag-retrieval/src/api/routes/search.rs:105`
- `crates/rag-retrieval/src/api/routes/search.rs:106`
- `crates/rag-retrieval/src/api/routes/multi.rs:133`
- `services/orchestrator/workflow/nodes/retrieval.py:145`

## In Scope
- Introduce runtime degradation evaluation in retrieval service.
- Populate `degradation_mode`, `components_used`, `components_skipped` from real execution outcomes.
- Ensure multi-query endpoint emits the same contract.
- Keep orchestrator parser compatibility.

## Out of Scope
- New cross-service degradation taxonomy redesign.

## Implementation Tasks
1. Define internal evaluation logic after search/rerank stages.
2. Populate response fields in both single and multi routes.
3. Add tests for normal and degraded paths.
4. Validate orchestrator retrieval node behavior with new values.

## Acceptance Criteria
- [ ] Normal and degraded runs produce different metadata correctly.
- [ ] `components_used/skipped` are accurate for each request mode.
- [ ] No hardcoded defaults remain in success path.

## Test Plan
- API tests with forced component failures (semantic, keyword, rerank).
- Contract test for response shape stability.

## Handoff Notes
Keep field names unchanged to avoid frontend/orchestrator breaks.
