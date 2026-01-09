# US-4.10: Conversation Persistence (Postgres)

## Goal
Persist conversations/messages (with citations) to Postgres per architecture schema while maintaining Redis for fast session access.

## Requirements
- Migrations for `conversations` and `messages` tables matching `docs/architecture.md`.
- Write-through: on message creation, store in Postgres and Redis; include citations JSONB.
- Provide pagination and retrieval endpoints/hooks for session history.
- Data retention/TTL configurable for Redis; Postgres as source of truth.

## Acceptance Criteria
- Messages persisted with correct schema (tenant_id, user_id, citations); Redis cache stays in sync.
- Orchestrator can reload history from Postgres after Redis flush.
- Tests cover create/read flows and cache miss recovery.
- OTEL spans include conversation_id/message_id.

## Verification
- `alembic upgrade head && pytest tests/memory/test_conversation_persistence.py`
- Inspect DB rows after query flow; simulate Redis flush and verify reload.
