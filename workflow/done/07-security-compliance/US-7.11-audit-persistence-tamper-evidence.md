# US-7.11: Audit Log Persistence & Tamper-evidence

## Goal
Persist audit logs to Loki and Postgres `audit_log` table with tamper-evident guarantees.

## Requirements
- Implement audit middleware to capture user/tenant, action, resource, IP, trace_id, status, timestamp.
- Write audit entries to Postgres `audit_log` with hash chaining or WORM-like immutability flag; store hash of previous record to detect tampering.
- Ship structured JSON audit logs to Loki with trace_id and hash references.
- Provide export script/runbook; define retention and access controls.

## Acceptance Criteria
- Audit entries stored in DB with valid hash chain; tampering detection test passes.
- Logs visible in Loki with matching trace_id and DB record ids.
- 401/403/5xx actions also logged with reason.
- Export script works and enforces access control.

## Verification
- `pytest tests/security/test_audit_tamper_evidence.py`
- Query DB to validate hash chain; cross-check Loki entry via trace_id.
