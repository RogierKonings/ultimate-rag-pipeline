# Story R3: Multi-Query Tenant and Filter Alignment

- Type: Refactor
- Priority: P0
- Source backlog item: R3

## Goal
Make `/api/v1/retrieve/multi` apply tenant context, filters, and rerank semantics consistently with `/api/v1/retrieve`.

## Problem
Multi-query path uses random context and ignores request filters and tenant identity.

## Evidence
- `crates/rag-retrieval/src/api/routes/multi.rs:61`
- `crates/rag-retrieval/src/api/routes/multi.rs:164`
- `crates/rag-retrieval/src/api/routes/multi.rs:44`

## In Scope
- Extract tenant/user context from headers and/or filters in multi route.
- Apply filters to each sub-query search call.
- Clarify and implement rerank behavior for aggregated results.

## Out of Scope
- New aggregation algorithms.

## Implementation Tasks
1. Mirror context extraction strategy from single-query route.
2. Thread context and filters into `execute_single_query`.
3. Implement/confirm rerank behavior after aggregation.
4. Add parity tests between single and multi endpoints.

## Acceptance Criteria
- [ ] Multi-query respects tenant scoping.
- [ ] Multi-query respects filters for all sub-queries.
- [ ] Response contract remains backward compatible.

## Test Plan
- Route tests with tenant header + filter combinations.
- Aggregation tests with filtered datasets.

## Handoff Notes
Prefer shared helper functions to avoid duplication between single and multi routes.
