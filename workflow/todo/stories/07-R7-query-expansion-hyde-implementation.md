# Story R7: Implement Query Expansion and HyDE

- Type: Feature
- Priority: P1
- Source backlog item: R7

## Goal
Implement production-grade query expansion and HyDE generation in retrieval pipeline via LLM gateway.

## Problem
Expansion and HyDE code paths are partially stubbed, limiting retrieval quality gains.

## Evidence
- `crates/rag-retrieval/src/query/expander.rs:342`
- `crates/rag-retrieval/src/hybrid/pipeline.rs:280`

## In Scope
- Implement LLM call for expansion.
- Implement HyDE generation and integrate into query embedding path.
- Add retries/timeouts and fallback behavior.

## Out of Scope
- Prompt tuning experiments beyond baseline templates.

## Implementation Tasks
1. Add gateway client integration to expansion/hyde modules.
2. Implement deterministic parsing/validation of generated queries/docs.
3. Add config flags and safe fallbacks to original query.
4. Add tests for success/failure/timeout paths.

## Acceptance Criteria
- [ ] Expansion returns non-empty alternatives when enabled and healthy.
- [ ] HyDE query-to-embed path activates when enabled.
- [ ] Failure in either feature degrades gracefully to base query.

## Test Plan
- Unit tests for parser and fallback logic.
- Integration tests with mocked gateway responses.

## Handoff Notes
Preserve existing default-off behavior if uncertainty about latency budget.
