# Story R10: Implement LLM Gateway Reranker Capability

- Type: Feature
- Priority: P1
- Source backlog item: R10

## Goal
Implement non-stub reranker behavior in `rag-llm-gateway` or explicitly expose reranker as unavailable capability.

## Problem
Gateway starts with reranker enabled but actual model loading/scoring remains unimplemented.

## Evidence
- `crates/rag-llm-gateway/src/bin/main.rs:40`
- `crates/rag-llm-gateway/src/reranker/model.rs:56`
- `crates/rag-llm-gateway/src/reranker/model.rs:152`

## In Scope
- Implement ONNX model load and scoring path, or
- Explicitly disable reranker endpoint with capability + health signaling.

## Out of Scope
- New reranker model research.

## Implementation Tasks
1. Decide implementation vs explicit disablement.
2. Wire decision into startup and health/readiness reporting.
3. Ensure endpoint behavior is explicit and test-covered.
4. Update downstream expectations in retrieval service.

## Acceptance Criteria
- [ ] No ambiguous "enabled but unavailable" runtime state.
- [ ] `/v1/rerank` behavior is deterministic and documented.
- [ ] Health/capability signals match real runtime behavior.

## Test Plan
- Startup tests for reranker enabled/disabled paths.
- Endpoint tests for success and unavailable modes.

## Handoff Notes
Prefer explicit capability flags over silent no-op behavior.
