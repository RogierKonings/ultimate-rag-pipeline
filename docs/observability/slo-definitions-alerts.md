# SLO Definitions & Alerts

> **Status:** Production Ready
> **Implemented:** US-10.3.4
> **Last Updated:** January 2026

## Overview

Service Level Objectives (SLOs) define reliability targets for the RAG pipeline with automated alerting based on error budgets and burn rates. This enables proactive incident response and provides a basis for capacity planning and stakeholder communication.

---

## Table of Contents

1. [SLO Targets](#slo-targets)
2. [Error Budgets](#error-budgets)
3. [Burn Rate Alerts](#burn-rate-alerts)
4. [Prometheus Recording Rules](#prometheus-recording-rules)
5. [AlertManager Configuration](#alertmanager-configuration)
6. [Grafana SLO Dashboard](#grafana-slo-dashboard)
7. [Runbooks](#runbooks)
8. [Configuration Reference](#configuration-reference)
9. [Implementation Reference](#implementation-reference)

---

## SLO Targets

### Defined SLOs

| SLO | SLI | Target | Window | Description |
|-----|-----|--------|--------|-------------|
| Retrieval Latency | % requests < 250ms | 95% | 30 days | Retrieval requests complete quickly |
| RAG E2E Latency | % requests < 2000ms | 95% | 30 days | Complete RAG queries respond within target |
| RAG Error Rate | % successful queries | 99% | 30 days | RAG queries succeed reliably |
| Service Availability | % time services up | 99.9% | 30 days | Core services remain available |

### SLO Definition Format

```yaml
# config/slo/definitions.yaml
slos:
  retrieval_latency:
    name: "Retrieval Latency"
    description: "Retrieval requests should complete quickly"
    sli:
      type: latency
      metric: "retrieval_search_duration_seconds"
      good_events: "le='0.25'"  # 250ms threshold
    objectives:
      - target: 0.95  # 95% of requests < 250ms
        window: 30d

  rag_e2e_latency:
    name: "RAG End-to-End Latency"
    description: "Complete RAG queries should respond within target"
    sli:
      type: latency
      metric: "rag_e2e_latency_seconds"
      good_events: "le='2.0'"  # 2s threshold
    objectives:
      - target: 0.95
        window: 30d

  rag_error_rate:
    name: "RAG Error Rate"
    description: "RAG queries should succeed"
    sli:
      type: availability
      good_metric: "rag_queries_total{status='success'}"
      total_metric: "rag_queries_total"
    objectives:
      - target: 0.99  # 99% success rate
        window: 30d

  service_availability:
    name: "Service Availability"
    description: "Services should be available"
    sli:
      type: availability
      good_metric: "up{job=~'orchestrator|retrieval|ingestion'}"
      total_metric: "1"
    objectives:
      - target: 0.999  # 99.9% availability
        window: 30d
```

---

## Error Budgets

### Error Budget Calculation

```
Error Budget = 1 - SLO Target
```

| SLO | Target | Error Budget | Allowed Failures (30d) |
|-----|--------|--------------|------------------------|
| Retrieval Latency | 95% | 5% | 5% of requests can exceed 250ms |
| RAG E2E Latency | 95% | 5% | 5% of requests can exceed 2s |
| RAG Error Rate | 99% | 1% | 1% of queries can fail |
| Service Availability | 99.9% | 0.1% | ~43 minutes downtime/month |

### Error Budget Consumption

Error budget tracks how much of the allowed failures have been used:

```
Budget Remaining = 1 - (Actual Error Rate / Error Budget)
```

Example for 99% error rate SLO:
- Error budget: 1% (0.01)
- Actual error rate: 0.5%
- Budget consumed: 0.5% / 1% = 50%
- Budget remaining: 50%

### Budget Exhaustion

When error budget reaches 0%:
- Consider halting non-critical deployments
- Focus on reliability improvements
- Review incident causes

---

## Burn Rate Alerts

### Burn Rate Concept

Burn rate measures how fast the error budget is being consumed:

```
Burn Rate = (Actual Error Rate) / (Error Budget Rate)
```

A burn rate of 1x means the budget will be exhausted exactly at the end of the window.

### Multi-Window Burn Rate

To reduce false positives, alerts use both short and long windows:

| Alert | Burn Rate | Short Window | Long Window | Budget Consumed | Response |
|-------|-----------|--------------|-------------|-----------------|----------|
| Critical | 14.4x | 5m | 1h | 2% in 1h | Page immediately |
| Critical | 6x | 30m | 6h | 5% in 6h | Page |
| Warning | 1x | 6h | 3d | 10% in 3d | Create ticket |

### Why Multi-Window?

- **Short window only**: Too many false positives from brief spikes
- **Long window only**: Alerts too late, budget already depleted
- **Both windows**: High confidence of sustained issue

### Alert Conditions

```yaml
# Critical: High burn rate in both short and long windows
- alert: RAGErrorBudgetBurn_Critical
  expr: |
    slo:rag_error_rate:burn_rate_5m > 14.4
    and
    slo:rag_error_rate:burn_rate_1h > 14.4
  for: 2m
  labels:
    severity: critical

# Warning: Elevated burn rate sustained
- alert: RAGErrorBudgetBurn_Warning
  expr: |
    slo:rag_error_rate:burn_rate_1h > 2
    and
    slo:rag_error_rate:burn_rate_6h > 2
  for: 15m
  labels:
    severity: warning
```

---

## Prometheus Recording Rules

### SLI Calculations

```yaml
# config/prometheus/slo_rules.yaml
groups:
  - name: slo_recording_rules
    interval: 30s
    rules:
      # Retrieval Latency SLI
      - record: sli:retrieval_latency:ratio_rate5m
        expr: |
          sum(rate(retrieval_search_duration_seconds_bucket{le="0.25"}[5m]))
          /
          sum(rate(retrieval_search_duration_seconds_count[5m]))

      - record: sli:retrieval_latency:ratio_rate1h
        expr: |
          sum(rate(retrieval_search_duration_seconds_bucket{le="0.25"}[1h]))
          /
          sum(rate(retrieval_search_duration_seconds_count[1h]))

      - record: sli:retrieval_latency:ratio_rate30d
        expr: |
          sum(increase(retrieval_search_duration_seconds_bucket{le="0.25"}[30d]))
          /
          sum(increase(retrieval_search_duration_seconds_count[30d]))

      # RAG E2E Latency SLI
      - record: sli:rag_e2e_latency:ratio_rate5m
        expr: |
          sum(rate(rag_e2e_latency_seconds_bucket{le="2.0"}[5m]))
          /
          sum(rate(rag_e2e_latency_seconds_count[5m]))

      - record: sli:rag_e2e_latency:ratio_rate1h
        expr: |
          sum(rate(rag_e2e_latency_seconds_bucket{le="2.0"}[1h]))
          /
          sum(rate(rag_e2e_latency_seconds_count[1h]))

      # Error Rate SLI
      - record: sli:rag_error_rate:ratio_rate5m
        expr: |
          sum(rate(rag_queries_total{status="success"}[5m]))
          /
          sum(rate(rag_queries_total[5m]))

      - record: sli:rag_error_rate:ratio_rate1h
        expr: |
          sum(rate(rag_queries_total{status="success"}[1h]))
          /
          sum(rate(rag_queries_total[1h]))

      - record: sli:rag_error_rate:ratio_rate30d
        expr: |
          sum(increase(rag_queries_total{status="success"}[30d]))
          /
          sum(increase(rag_queries_total[30d]))
```

### Error Budget and Burn Rate

```yaml
      # Error Budget Remaining (30d window, 99% target)
      - record: slo:rag_error_rate:error_budget_remaining
        expr: |
          1 - (
            (1 - sli:rag_error_rate:ratio_rate30d)
            /
            (1 - 0.99)  # 1% error budget
          )

      # Burn Rate calculations
      - record: slo:rag_error_rate:burn_rate_5m
        expr: |
          (1 - sli:rag_error_rate:ratio_rate5m) / (1 - 0.99)

      - record: slo:rag_error_rate:burn_rate_1h
        expr: |
          (1 - sli:rag_error_rate:ratio_rate1h) / (1 - 0.99)

      - record: slo:rag_error_rate:burn_rate_6h
        expr: |
          (1 - sli:rag_error_rate:ratio_rate6h) / (1 - 0.99)
```

---

## AlertManager Configuration

### Alert Rules

```yaml
# config/prometheus/slo_alerts.yaml
groups:
  - name: slo_alerts
    rules:
      # Critical: Fast error budget burn
      - alert: RAGErrorBudgetBurn_Critical
        expr: |
          slo:rag_error_rate:burn_rate_5m > 14.4
          and
          slo:rag_error_rate:burn_rate_1h > 14.4
        for: 2m
        labels:
          severity: critical
          slo: rag_error_rate
        annotations:
          summary: "RAG error budget burning critically fast"
          description: |
            Burn rate is {{ $value | printf "%.1f" }}x the sustainable rate.
            At this rate, the 30-day error budget will be exhausted in
            {{ printf "%.1f" (div 720 $value) }} hours.
          runbook_url: "https://docs.example.com/runbooks/slo/rag-error-budget-burn"

      # Warning: Elevated burn rate
      - alert: RAGErrorBudgetBurn_Warning
        expr: |
          slo:rag_error_rate:burn_rate_1h > 2
          and
          slo:rag_error_rate:burn_rate_6h > 2
        for: 15m
        labels:
          severity: warning
          slo: rag_error_rate
        annotations:
          summary: "RAG error budget burn rate elevated"
          description: |
            Burn rate is {{ $value | printf "%.1f" }}x sustainable.
            Investigate before budget exhaustion.

      # Latency SLO violations
      - alert: RetrievalLatencySLO_Critical
        expr: |
          sli:retrieval_latency:ratio_rate5m < 0.90
          and
          sli:retrieval_latency:ratio_rate1h < 0.95
        for: 5m
        labels:
          severity: critical
          slo: retrieval_latency
        annotations:
          summary: "Retrieval latency SLO violation"
          description: |
            Only {{ $value | printf "%.1f" }}% of requests are under 250ms.
            Target is 95%.
          runbook_url: "https://docs.example.com/runbooks/slo/retrieval-latency"

      - alert: RAGE2ELatencySLO_Critical
        expr: |
          sli:rag_e2e_latency:ratio_rate5m < 0.90
          and
          sli:rag_e2e_latency:ratio_rate1h < 0.95
        for: 5m
        labels:
          severity: critical
          slo: rag_e2e_latency
        annotations:
          summary: "RAG E2E latency SLO violation"
          description: |
            Only {{ $value | printf "%.1f" }}% of requests complete under 2s.
            Target is 95%.

      # Error budget exhaustion warning
      - alert: RAGErrorBudgetLow
        expr: |
          slo:rag_error_rate:error_budget_remaining < 0.25
        for: 5m
        labels:
          severity: warning
          slo: rag_error_rate
        annotations:
          summary: "RAG error budget running low"
          description: |
            Only {{ $value | printf "%.1f" }}% of monthly error budget remains.
            Consider freezing non-critical changes.
```

### Routing Configuration

```yaml
# alertmanager.yaml
route:
  receiver: default
  group_by: [alertname, slo]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - match:
        severity: critical
        slo: rag_error_rate
      receiver: pagerduty-slo
      continue: true

    - match:
        severity: critical
      receiver: slack-critical

    - match:
        severity: warning
      receiver: slack-warning

receivers:
  - name: default
    slack_configs:
      - channel: '#rag-alerts'

  - name: pagerduty-slo
    pagerduty_configs:
      - service_key: '<pagerduty-key>'
        severity: critical

  - name: slack-critical
    slack_configs:
      - channel: '#rag-alerts-critical'
        color: 'danger'

  - name: slack-warning
    slack_configs:
      - channel: '#rag-alerts'
        color: 'warning'
```

---

## Grafana SLO Dashboard

### Dashboard Panels

| Panel | Type | Description |
|-------|------|-------------|
| Error Budget Remaining | Gauge | % of monthly budget remaining |
| Burn Rate (1h) | Stat | Current burn rate (1x = sustainable) |
| SLI: Error Rate | Time series | Success rate over time with SLO line |
| SLI: Retrieval Latency | Time series | % under 250ms with SLO line |
| SLI: E2E Latency | Time series | % under 2s with SLO line |
| Error Budget Over Time | Time series | Budget consumption trend |
| 30-Day SLO Compliance | Table | All SLIs vs targets |

### Panel Queries

#### Error Budget Remaining (Gauge)

```promql
slo:rag_error_rate:error_budget_remaining * 100
```

Thresholds:
- Green: > 50%
- Yellow: 25-50%
- Red: < 25%

#### Burn Rate (Stat)

```promql
slo:rag_error_rate:burn_rate_1h
```

Thresholds:
- Green: < 1
- Yellow: 1-2
- Red: > 10

#### SLI: Error Rate (Time Series)

```promql
# Actual success rate
sli:rag_error_rate:ratio_rate5m * 100

# SLO target line
99
```

#### 30-Day Compliance (Table)

```promql
# Error Rate SLI
sli:rag_error_rate:ratio_rate30d * 100

# Retrieval Latency SLI
sli:retrieval_latency:ratio_rate30d * 100

# E2E Latency SLI
sli:rag_e2e_latency:ratio_rate30d * 100
```

### Dashboard JSON Location

```
services/shared/observability/grafana/provisioning/dashboards/slo.json
```

---

## Runbooks

### Available Runbooks

| Alert | Runbook |
|-------|---------|
| RAGErrorBudgetBurn_Critical | [rag-error-budget-burn.md](../runbooks/slo/rag-error-budget-burn.md) |
| RetrievalLatencySLO_Critical | [retrieval-latency.md](../runbooks/slo/retrieval-latency.md) |
| RAGE2ELatencySLO_Critical | [rag-e2e-latency.md](../runbooks/slo/rag-e2e-latency.md) |
| ServiceAvailability | [service-availability.md](../runbooks/slo/service-availability.md) |

### Runbook Structure

Each runbook includes:

1. **Alert Description**: What triggered the alert
2. **Impact Assessment**: User impact and business consequences
3. **Investigation Steps**: How to diagnose the issue
4. **Mitigation Actions**: Immediate steps to reduce impact
5. **Escalation Procedures**: When and how to escalate
6. **Recovery Verification**: How to confirm resolution

### Example: RAG Error Budget Burn

```markdown
# Runbook: RAG Error Budget Burn

## Alert: RAGErrorBudgetBurn_Critical

### Impact
- Users experiencing elevated error rates
- At current rate, budget exhausted in X hours
- May require incident declaration

### Investigation Steps

1. **Check service health**
   kubectl get pods -n rag-pipeline
   curl -s http://orchestrator:8003/health | jq

2. **Identify error source**
   # Check error breakdown
   sum by (error_type) (rate(rag_queries_total{status="error"}[5m]))

3. **Check dependencies**
   curl http://qdrant:6333/health
   curl http://opensearch:9200/_cluster/health

4. **Check recent deployments**
   kubectl rollout history deployment/orchestrator -n rag-pipeline

### Mitigation

1. **Roll back if recent deployment**
   kubectl rollout undo deployment/orchestrator -n rag-pipeline

2. **Enable degraded mode if dependency issue**
   # Verify circuit breakers are working

3. **Scale up if capacity issue**
   kubectl scale deployment/orchestrator --replicas=5

### Escalation
- Warning > 30 min: Page on-call SRE
- Critical > 10 min: Declare incident

### Recovery Verification
- Error rate < 1%
- Burn rate < 1x
- No new alerts for 15 min
```

---

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SLO_ENABLED` | Enable SLO recording rules | `true` |
| `SLO_ERROR_RATE_TARGET` | Error rate SLO target | `0.99` |
| `SLO_RETRIEVAL_LATENCY_TARGET` | Retrieval latency target | `0.95` |
| `SLO_RETRIEVAL_LATENCY_THRESHOLD` | Latency threshold (seconds) | `0.25` |
| `SLO_E2E_LATENCY_TARGET` | E2E latency target | `0.95` |
| `SLO_E2E_LATENCY_THRESHOLD` | Latency threshold (seconds) | `2.0` |
| `SLO_AVAILABILITY_TARGET` | Availability target | `0.999` |

### File Locations

| File | Description |
|------|-------------|
| `config/slo/definitions.yaml` | SLO definitions |
| `config/prometheus/slo_rules.yaml` | Prometheus recording rules |
| `config/prometheus/slo_alerts.yaml` | AlertManager alert rules |
| `config/alertmanager/alertmanager.yaml` | Alert routing configuration |

---

## Implementation Reference

| Component | Location |
|-----------|----------|
| SLO definitions | `config/slo/definitions.yaml` |
| Recording rules | `config/prometheus/slo_rules.yaml` |
| Alert rules | `config/prometheus/slo_alerts.yaml` |
| Grafana dashboard | `services/shared/observability/grafana/provisioning/dashboards/slo.json` |
| Runbooks | `docs/runbooks/slo/` |

---

## Related Documentation

- [Business & Quality Metrics](./business-quality-metrics.md) - Metrics that feed SLIs
- [Observability Overview](./README.md) - Complete observability stack
- [Alerting](#alerting) - General alerting configuration
