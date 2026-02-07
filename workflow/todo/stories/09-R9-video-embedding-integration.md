# Story R9: Replace Placeholder Video Embeddings with Real Embedding Service

- Type: Feature
- Priority: P1
- Source backlog item: R9

## Goal
Use real embedding service calls for video chunks instead of placeholder generated vectors.

## Problem
Current video embedding generation uses deterministic placeholder math, not model embeddings.

## Evidence
- `crates/rag-video/src/pipeline/executor.rs:432`

## In Scope
- Add embedding client dependency to video pipeline.
- Generate embeddings via service API.
- Validate dimension and indexing assumptions.

## Out of Scope
- Video reranking model changes.

## Implementation Tasks
1. Create/configure embedding client in video pipeline.
2. Replace placeholder vector generation.
3. Handle batching, retries, and partial failures.
4. Add tests for dimension checks and fallback behavior.

## Acceptance Criteria
- [ ] Video chunk embeddings come from embedding service.
- [ ] Dimension mismatch is detected and surfaced clearly.
- [ ] Pipeline has controlled fallback/error behavior.

## Test Plan
- Unit tests with mock embedding client.
- Integration test for pipeline embedding stage.

## Handoff Notes
Keep embedding model configurable per environment.
