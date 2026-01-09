# US-4.11: Streaming Contract Validation

## Goal
Ensure SSE streaming matches architecture contract (`start`, `delta`, `citations`, `done` events) and meets TTFT targets.

## Requirements
- Implement SSE emitter that emits events in order: start → delta* → citations → done.
- Include conversation_id, message_id, retrieval_id, and token counts in final `done` event.
- Enforce max input length and guardrail retries without breaking stream.
- Measure and log TTFT; expose Prometheus metric.

## Acceptance Criteria
- Integration test asserts event order and payload fields match `docs/architecture.md` example.
- TTFT <500ms for warm path; metric exported.
- Stream recovers or terminates cleanly on guardrail retries; client sees final done/error.
- OpenAPI/Docs include streaming contract.

## Verification
- `pytest tests/api/test_streaming_contract.py`
- Manual `curl -N http://.../api/v1/query/stream` shows correct SSE events.
