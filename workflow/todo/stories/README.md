# Refactor and Feature Story Pack

This folder converts `workflow/todo/refactor-opportunities.md` into implementation-ready stories for autonomous execution.

## How To Use
1. Pick the next story by priority/order below.
2. Read the story file end-to-end before changing code.
3. Implement only the in-scope items.
4. Validate against the acceptance criteria and test plan.
5. Update story status in your PR description.

## Story Index

### P0 (Do First)
1. `01-R1-retrieval-filter-propagation.md`
2. `02-R2-retrieval-degradation-contract.md`
3. `03-R3-multi-query-tenant-filter-alignment.md`
4. `04-R4-orchestrator-streaming-retrieval-client.md`
5. `05-R5-video-api-contract-alignment.md`

### P1
6. `06-R6-retrieval-pipeline-consolidation.md`
7. `07-R7-query-expansion-hyde-implementation.md`
8. `08-R8-ingestion-endpoint-completion.md`
9. `09-R9-video-embedding-integration.md`
10. `10-R10-llm-gateway-reranker-implementation.md`
11. `11-R11-orchestrator-shared-http-clients.md`

### P2
12. `12-R12-frontend-proxy-unification.md`
13. `13-R13-api-contract-generation-and-tests.md`
14. `14-R14-cors-hardening-and-config-wiring.md`
15. `15-R15-large-module-decomposition.md`

### Additional Feature Stories
16. `16-F1-frontend-sse-consumption.md`
17. `17-F2-retrieval-explain-debug-endpoint.md`
18. `18-F3-service-capability-discovery.md`
19. `19-F4-cache-invalidation-on-ingestion-events.md`

## Source Mapping
- R1-R15 and F1-F4 are fully mapped from `workflow/todo/refactor-opportunities.md`.
