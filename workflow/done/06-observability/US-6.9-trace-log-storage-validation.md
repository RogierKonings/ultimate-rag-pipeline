# US-6.9: Trace/Log Storage Validation (Tempo/Loki)

## Goal
Validate that traces and logs from all services reach Tempo/Jaeger and Loki, and are queryable with trace-log correlation.

## Requirements
- OTLP exporter configured in services; ensure trace context propagation across HTTP/async.
- Loki ingestion pipeline configured (via OTEL or promtail); structured JSON logs include trace_id/span_id.
- Dashboards/queries to retrieve traces/logs by service/tenant/request id.
- Smoke tests to assert trace + log presence for sample requests.

## Acceptance Criteria
- End-to-end request produces a trace visible in Tempo/Jaeger with spans from ingestion, retrieval, orchestrator, LLM.
- Corresponding logs in Loki contain trace_id/span_id and can be joined to spans.
- Alert on missing ingestion (>X% missing traces/logs) optionally configured.
- Documentation/runbook for querying and troubleshooting missing telemetry.

## Verification
- Trigger sample query; verify in Tempo UI and Loki query `|= "trace_id"`.
- `pytest tests/observability/test_trace_log_correlation.py`
