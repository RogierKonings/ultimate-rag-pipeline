# Story R15: Decompose Large Hotspot Modules

- Type: Refactor
- Priority: P2
- Source backlog item: R15

## Goal
Reduce change risk by splitting very large modules into cohesive service and adapter layers.

## Problem
Several high-traffic modules are large enough to slow reasoning and increase regression risk.

## Evidence
- `services/orchestrator/api/routes/query.py` (560 LOC)
- `services/orchestrator/gateway/client.py` (715 LOC)
- `crates/rag-retrieval/src/acl/filter.rs` (947 LOC)

## In Scope
- Extract orchestration route orchestration logic into service classes/functions.
- Split gateway client responsibilities (request building, retries, streaming parsing, health).
- Split ACL filter builders/rules/evaluation concerns.

## Out of Scope
- Functional behavior changes unrelated to decomposition.

## Implementation Tasks
1. Define split boundaries and target module structure.
2. Move logic incrementally with compatibility wrappers.
3. Update imports and tests.
4. Ensure no behavior drift.

## Acceptance Criteria
- [ ] Each target file reduced to manageable size and clear responsibility.
- [ ] Existing API behavior unchanged.
- [ ] Tests remain green.

## Test Plan
- Existing suite plus focused regression tests around moved code paths.

## Handoff Notes
Refactor in small commits; avoid simultaneous semantic changes.
