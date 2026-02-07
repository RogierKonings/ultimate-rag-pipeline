# Story R14: CORS Hardening and Config Wiring

- Type: Architecture
- Priority: P2
- Source backlog item: R14

## Goal
Replace permissive CORS defaults with environment-aware policy and ensure Rust `cors_enabled` config is actually enforced.

## Problem
CORS is currently wide open in multiple services, and some CORS config flags are not wired into router behavior.

## Evidence
- `services/orchestrator/api/app.py:236`
- `crates/rag-ingestion/src/api/server.rs:44`
- `crates/rag-retrieval/src/api/server.rs:78`
- `crates/rag-retrieval/src/api/server.rs:212`

## In Scope
- Implement explicit allowed origins by environment.
- Wire `cors_enabled` into router creation.
- Keep local/dev ergonomics while hardening production.

## Out of Scope
- Auth middleware redesign.

## Implementation Tasks
1. Add config shape for allowed origins/methods/headers.
2. Update routers to conditionally apply CORS layers.
3. Add tests for enabled/disabled and prod-safe defaults.
4. Document env variables in README/config docs.

## Acceptance Criteria
- [ ] Production config requires explicit origins (no `*` default).
- [ ] `cors_enabled=false` disables CORS layer.
- [ ] Dev config remains functional for local UI.

## Test Plan
- Router tests validating headers under different configs.
- One e2e smoke in dev profile.

## Handoff Notes
Coordinate with frontend domain deployment settings before tightening prod origins.
