# Story R11: Shared HTTP Clients in Orchestrator Workflow Nodes

- Type: Refactor
- Priority: P1
- Source backlog item: R11

## Goal
Stop creating per-request `httpx.AsyncClient` instances in workflow nodes; use shared, lifecycle-managed clients with consistent policies.

## Problem
Current node implementations construct new clients on each request, reducing connection reuse and policy consistency.

## Evidence
- `services/orchestrator/workflow/nodes/retrieval.py:105`
- `services/orchestrator/workflow/nodes/generation.py:137`

## In Scope
- Introduce shared clients in app state/dependency container.
- Apply standard timeout/retry/header policies.
- Refactor nodes to consume shared clients.

## Out of Scope
- Changing external API contracts.

## Implementation Tasks
1. Add shared client factories in startup lifecycle.
2. Inject clients into workflow/node context.
3. Remove node-local `AsyncClient` instantiation.
4. Add tests for lifecycle and request behavior.

## Acceptance Criteria
- [ ] No per-request client construction in retrieval/generation nodes.
- [ ] Connection pooling is reused across requests.
- [ ] Timeouts/retries/headers are centrally defined and applied.

## Test Plan
- Unit tests with mocked shared client.
- Throughput smoke test showing stable connection reuse.

## Handoff Notes
Keep `close()`/shutdown cleanup explicit to avoid leaked connections.
