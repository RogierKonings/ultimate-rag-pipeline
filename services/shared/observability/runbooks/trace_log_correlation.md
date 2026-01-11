# Trace-Log Correlation Troubleshooting Runbook

## Overview

This runbook helps troubleshoot issues with trace-log correlation in the RAG pipeline observability stack.

## Quick Links

- [Grafana Explore](http://grafana:3000/explore)
- [Jaeger UI](http://jaeger:16686)
- [Prometheus Targets](http://prometheus:9090/targets)

---

## Common Issues

### 1. Traces Not Appearing in Jaeger

**Symptoms:**
- No traces visible in Jaeger UI
- `trace_id` not found when searching
- Service not listed in Jaeger service dropdown

**Investigation Steps:**

1. **Check OTEL Collector health:**
   ```bash
   curl http://otel-collector:13133/
   # Should return 200 OK
   ```

2. **Check service is exporting traces:**
   ```bash
   # Query Prometheus for span metrics
   curl -G 'http://prometheus:9090/api/v1/query' \
     --data-urlencode 'query=rate(otelcol_receiver_accepted_spans[5m])'
   ```

3. **Verify OTEL environment variables in service:**
   ```bash
   kubectl exec -it <pod-name> -- env | grep OTEL
   ```

   Expected:
   ```
   OTEL_SERVICE_NAME=<service-name>
   OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
   OTEL_TRACES_SAMPLER=parentbased_traceidratio
   OTEL_TRACES_SAMPLER_ARG=0.1
   ```

4. **Check OTEL Collector logs for errors:**
   ```bash
   kubectl logs -l app=otel-collector -n observability --tail=100
   ```

**Common Causes:**
- Service not configured with OTEL SDK
- Wrong collector endpoint
- Network policy blocking traffic
- Collector queue full (backpressure)

**Resolution:**
- Ensure OTEL SDK is initialized in service startup
- Verify collector endpoint is reachable from service pod
- Check network policies allow egress to collector
- Scale collector or increase queue size if under load

---

### 2. Logs Not Appearing in Loki

**Symptoms:**
- No logs visible when querying Loki
- Service logs not showing in Grafana

**Investigation Steps:**

1. **Check Loki health:**
   ```bash
   curl http://loki:3100/ready
   # Should return "ready"
   ```

2. **Check Promtail status:**
   ```bash
   kubectl logs -l app=promtail -n observability --tail=100
   ```

3. **Verify log labels:**
   ```bash
   curl -G 'http://loki:3100/loki/api/v1/label/service/values'
   ```

4. **Check Promtail is scraping pods:**
   ```bash
   curl http://promtail:3101/service-discovery
   ```

**Common Causes:**
- Promtail not running on node
- Incorrect scrape config
- Logs not in expected format
- Loki ingestion rate limited

**Resolution:**
- Ensure Promtail DaemonSet is running on all nodes
- Verify Promtail config matches log file paths
- Check logs are valid JSON format
- Increase Loki ingestion limits

---

### 3. trace_id Not Indexed in Loki

**Symptoms:**
- Logs exist but can't query by trace_id
- `{trace_id="xxx"}` returns no results
- Have to use `|= "xxx"` content search

**Investigation Steps:**

1. **Check if trace_id is in log labels:**
   ```bash
   curl -G 'http://loki:3100/loki/api/v1/label' | jq
   # Should include "trace_id"
   ```

2. **Check Promtail pipeline configuration:**
   ```yaml
   # Expected in promtail-config.yaml
   pipeline_stages:
     - json:
         expressions:
           trace_id: trace_id
     - labels:
         trace_id:
   ```

3. **Sample a log to verify structure:**
   ```bash
   curl -G 'http://loki:3100/loki/api/v1/query' \
     --data-urlencode 'query={service="orchestrator-service"}' \
     --data-urlencode 'limit=1' | jq
   ```

**Common Causes:**
- Promtail pipeline not extracting trace_id
- trace_id field named differently in logs
- JSON parsing failed

**Resolution:**
- Update Promtail pipeline to extract trace_id
- Ensure logging framework includes trace_id field
- Match field name between logger and Promtail

---

### 4. Trace Context Not Propagating

**Symptoms:**
- Traces show only spans from one service
- Parent-child relationships broken
- Each service creates separate traces

**Investigation Steps:**

1. **Check trace in Jaeger:**
   - Look at span count
   - Verify services in trace
   - Check for missing service

2. **Verify context propagation headers:**
   ```bash
   # Check HTTP request has trace headers
   curl -v http://service:8000/api/endpoint 2>&1 | grep -i traceparent
   ```

3. **Check service instrumentation:**
   ```python
   # Verify middleware is installed
   from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
   FastAPIInstrumentor.instrument_app(app)
   ```

**Common Causes:**
- HTTP client not instrumented
- Missing propagator configuration
- Custom HTTP client bypassing instrumentation
- Async task not propagating context

**Resolution:**
- Ensure all HTTP clients are instrumented
- Configure W3C TraceContext propagator
- Use instrumented HTTP client (httpx, aiohttp)
- Pass trace context to Celery tasks

---

### 5. Missing Telemetry Alerts

**Symptoms:**
- Not alerted when observability fails
- Silent failures in pipeline

**Investigation Steps:**

1. **Check alert rules are loaded:**
   ```bash
   curl http://prometheus:9090/api/v1/rules | jq '.data.groups[].rules[] | select(.name | contains("Missing"))'
   ```

2. **Check Alertmanager is receiving:**
   ```bash
   curl http://alertmanager:9093/api/v1/alerts
   ```

**Resolution:**
Add missing telemetry alerts:
```yaml
- alert: MissingTraces
  expr: absent(rate(otelcol_receiver_accepted_spans[5m]) > 0) == 1
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: No traces received in 15 minutes
```

---

## Useful LogQL Queries

### Find logs by trace_id
```logql
{trace_id="abc123def456"}
```

### Find logs by trace_id (content search fallback)
```logql
{service=~".+"} |= "abc123def456"
```

### Find error logs with trace context
```logql
{service="orchestrator-service"} | json | level="error"
```

### Find slow requests
```logql
{service="orchestrator-service"} | json | duration_ms > 2000
```

### Get log count by service
```logql
sum by (service) (count_over_time({service=~".+"}[1h]))
```

---

## Useful PromQL Queries

### Trace export success rate
```promql
sum(rate(otelcol_exporter_sent_spans[5m])) /
(sum(rate(otelcol_exporter_sent_spans[5m])) + sum(rate(otelcol_exporter_send_failed_spans[5m])))
```

### Services with missing traces
```promql
absent(rate(otelcol_receiver_accepted_spans{service_name="orchestrator-service"}[5m]) > 0)
```

### Log ingestion rate by service
```promql
sum by (service) (rate(loki_distributor_lines_received_total[5m]))
```

---

## Grafana Trace-to-Logs Configuration

Ensure datasources are configured with correlation:

```yaml
# datasources.yaml
- name: Jaeger
  type: jaeger
  url: http://jaeger:16686
  jsonData:
    tracesToLogs:
      datasourceUid: loki
      tags:
        - service
      mappedTags:
        - key: trace_id
          value: trace_id
      spanStartTimeShift: "-1h"
      spanEndTimeShift: "1h"
      filterByTraceID: true
      filterBySpanID: true

- name: Loki
  type: loki
  url: http://loki:3100
  jsonData:
    derivedFields:
      - datasourceUid: jaeger
        matcherRegex: "trace_id=([\\w]+)"
        name: TraceID
        url: "$${__value.raw}"
```

---

## Escalation

If issues persist after following this runbook:

1. Collect diagnostics:
   ```bash
   kubectl logs -l app=otel-collector -n observability > collector.log
   kubectl logs -l app=promtail -n observability > promtail.log
   kubectl describe pods -l app.kubernetes.io/component=observability -n observability
   ```

2. Create incident with:
   - Symptom description
   - Investigation steps taken
   - Diagnostic logs
   - Time range of issue

3. Contact on-call SRE team via PagerDuty
