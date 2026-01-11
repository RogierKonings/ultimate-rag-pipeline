# US-6.8: Alerting

> **Story ID:** US-6.8  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-6.2 (Prometheus Metrics), US-6.3 (Key Metrics Definition)

## User Story

**As a** SRE  
**I want** proactive alerting  
**So that** I'm notified of issues before users are impacted

## Context

Alerting is critical for maintaining system reliability. This story implements a comprehensive alerting system using Prometheus Alertmanager that:

- Detects anomalies based on defined thresholds
- Routes alerts to appropriate channels (Slack, PagerDuty, email)
- Supports silencing and inhibition rules
- Integrates with SLO-based error budget burn rate alerts

Alerts should follow best practices:
- **Actionable**: Every alert should have a clear runbook
- **Meaningful**: Avoid alert fatigue with proper thresholds
- **Tiered**: Critical issues page immediately, less urgent create tickets

## Technical Requirements

### Directory Structure

```
observability/
├── alerting/
│   ├── __init__.py
│   ├── rules/
│   │   ├── rag_alerts.yaml          # RAG-specific alerts
│   │   ├── infrastructure_alerts.yaml # Infrastructure alerts
│   │   ├── slo_alerts.yaml          # SLO burn rate alerts
│   │   └── recording_rules.yaml     # Recording rules for alerts
│   ├── alertmanager/
│   │   ├── alertmanager.yaml        # Alertmanager configuration
│   │   ├── templates/
│   │   │   ├── slack.tmpl           # Slack message template
│   │   │   └── pagerduty.tmpl       # PagerDuty template
│   │   └── silences/
│   │       └── maintenance.yaml     # Maintenance silence rules
│   └── runbooks/
│       ├── high_error_rate.md
│       ├── high_latency.md
│       ├── queue_depth.md
│       └── resource_exhaustion.md
├── k8s/
│   ├── alertmanager.yaml
│   └── prometheus-rules.yaml
└── docs/
    └── alerting.md
```

### Alertmanager Configuration

```yaml
# alertmanager/alertmanager.yaml
global:
  resolve_timeout: 5m
  slack_api_url: '${SLACK_WEBHOOK_URL}'
  pagerduty_url: 'https://events.pagerduty.com/v2/enqueue'

# Templates for notifications
templates:
  - '/etc/alertmanager/templates/*.tmpl'

# Routing tree
route:
  group_by: ['alertname', 'severity', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default-slack'
  
  routes:
    # Critical alerts -> PagerDuty immediately
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      group_wait: 0s
      repeat_interval: 1h
      continue: true
    
    # Critical alerts also go to Slack
    - match:
        severity: critical
      receiver: 'slack-critical'
      continue: false
    
    # Warning alerts -> Slack
    - match:
        severity: warning
      receiver: 'slack-warning'
      repeat_interval: 6h
    
    # Info alerts -> Low priority channel
    - match:
        severity: info
      receiver: 'slack-info'
      repeat_interval: 24h
    
    # SLO burn rate alerts have special routing
    - match_re:
        alertname: 'SLO.*BurnRate.*'
      receiver: 'slack-slo'
      group_by: ['alertname', 'slo']
      repeat_interval: 2h

# Inhibition rules
inhibit_rules:
  # If a critical alert fires, suppress related warnings
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'service']
  
  # If service is down, suppress all other alerts for it
  - source_match:
      alertname: 'ServiceDown'
    target_match_re:
      alertname: '.*'
    equal: ['service']

# Receiver configurations
receivers:
  - name: 'default-slack'
    slack_configs:
      - channel: '#alerts-rag'
        send_resolved: true
        title: '{{ template "slack.title" . }}'
        text: '{{ template "slack.text" . }}'
        actions:
          - type: button
            text: 'Runbook'
            url: '{{ template "slack.runbook_url" . }}'
          - type: button
            text: 'Dashboard'
            url: '{{ template "slack.dashboard_url" . }}'
  
  - name: 'slack-critical'
    slack_configs:
      - channel: '#alerts-critical'
        send_resolved: true
        color: '{{ if eq .Status "firing" }}danger{{ else }}good{{ end }}'
        title: '🚨 {{ template "slack.title" . }}'
        text: '{{ template "slack.text" . }}'
  
  - name: 'slack-warning'
    slack_configs:
      - channel: '#alerts-rag'
        send_resolved: true
        color: 'warning'
        title: '⚠️ {{ template "slack.title" . }}'
        text: '{{ template "slack.text" . }}'
  
  - name: 'slack-info'
    slack_configs:
      - channel: '#alerts-info'
        send_resolved: true
        color: '#36a64f'
        title: 'ℹ️ {{ template "slack.title" . }}'
        text: '{{ template "slack.text" . }}'
  
  - name: 'slack-slo'
    slack_configs:
      - channel: '#slo-alerts'
        send_resolved: true
        title: '📊 {{ template "slack.title" . }}'
        text: '{{ template "slack.slo_text" . }}'
  
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_SERVICE_KEY}'
        severity: critical
        description: '{{ template "pagerduty.description" . }}'
        details:
          firing: '{{ template "pagerduty.firing" . }}'
          num_firing: '{{ .Alerts.Firing | len }}'
          runbook_url: '{{ template "pagerduty.runbook_url" . }}'
```

### Slack Message Templates

```go
{{/* templates/slack.tmpl */}}

{{ define "slack.title" -}}
[{{ .Status | toUpper }}{{ if eq .Status "firing" }}:{{ .Alerts.Firing | len }}{{ end }}] {{ .CommonLabels.alertname }}
{{- end }}

{{ define "slack.text" -}}
{{ range .Alerts }}
*Alert:* {{ .Labels.alertname }}{{ if .Labels.severity }} - `{{ .Labels.severity }}`{{ end }}
*Service:* {{ .Labels.service | default "unknown" }}
*Description:* {{ .Annotations.description }}
*Summary:* {{ .Annotations.summary }}

{{ if .Annotations.runbook_url }}📖 <{{ .Annotations.runbook_url }}|Runbook>{{ end }}
{{ if .Annotations.dashboard_url }}📊 <{{ .Annotations.dashboard_url }}|Dashboard>{{ end }}

*Labels:*
{{ range .Labels.SortedPairs }}  • {{ .Name }}: `{{ .Value }}`
{{ end }}
---
{{ end }}
{{- end }}

{{ define "slack.runbook_url" -}}
{{ if .CommonAnnotations.runbook_url }}{{ .CommonAnnotations.runbook_url }}{{ else }}https://docs.example.com/runbooks{{ end }}
{{- end }}

{{ define "slack.dashboard_url" -}}
{{ if .CommonAnnotations.dashboard_url }}{{ .CommonAnnotations.dashboard_url }}{{ else }}https://grafana.example.com/d/rag-overview{{ end }}
{{- end }}

{{ define "slack.slo_text" -}}
{{ range .Alerts }}
*SLO:* {{ .Labels.slo }}
*Burn Rate:* {{ printf "%.2f" .Value }}x normal
*Error Budget Impact:* {{ .Annotations.error_budget_impact }}
*Window:* {{ .Labels.window }}

{{ .Annotations.summary }}

📖 <{{ .Annotations.runbook_url }}|Runbook> | 📊 <{{ .Annotations.dashboard_url }}|SLO Dashboard>
---
{{ end }}
{{- end }}
```

### RAG-Specific Alert Rules

```yaml
# rules/rag_alerts.yaml
groups:
  - name: rag_request_alerts
    interval: 30s
    rules:
      # High Error Rate
      - alert: RAGHighErrorRate
        expr: |
          (
            sum(rate(rag_query_total{status="error"}[5m])) by (service)
            / sum(rate(rag_query_total[5m])) by (service)
          ) > 0.05
        for: 5m
        labels:
          severity: critical
          team: rag-platform
        annotations:
          summary: "High error rate on {{ $labels.service }}"
          description: "Error rate is {{ printf \"%.2f\" $value }}% (threshold 5%)"
          runbook_url: "https://docs.example.com/runbooks/high-error-rate"
          dashboard_url: "https://grafana.example.com/d/rag-overview"
      
      # Warning level error rate
      - alert: RAGElevatedErrorRate
        expr: |
          (
            sum(rate(rag_query_total{status="error"}[5m])) by (service)
            / sum(rate(rag_query_total[5m])) by (service)
          ) > 0.01
        for: 10m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "Elevated error rate on {{ $labels.service }}"
          description: "Error rate is {{ printf \"%.2f\" $value }}% (threshold 1%)"
          runbook_url: "https://docs.example.com/runbooks/high-error-rate"
      
      # High Latency (P95)
      - alert: RAGHighLatency
        expr: |
          histogram_quantile(0.95, 
            sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, service)
          ) > 2
        for: 5m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "High P95 latency on {{ $labels.service }}"
          description: "P95 latency is {{ printf \"%.2f\" $value }}s (threshold 2s)"
          runbook_url: "https://docs.example.com/runbooks/high-latency"
      
      # Critical latency
      - alert: RAGCriticalLatency
        expr: |
          histogram_quantile(0.95, 
            sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, service)
          ) > 5
        for: 2m
        labels:
          severity: critical
          team: rag-platform
        annotations:
          summary: "Critical P95 latency on {{ $labels.service }}"
          description: "P95 latency is {{ printf \"%.2f\" $value }}s (threshold 5s)"
          runbook_url: "https://docs.example.com/runbooks/high-latency"
      
      # Service Down (no requests)
      - alert: RAGServiceDown
        expr: |
          sum(rate(rag_query_total[5m])) by (service) == 0
          and
          sum(up{job=~"rag-.*"}) by (service) == 0
        for: 2m
        labels:
          severity: critical
          team: rag-platform
        annotations:
          summary: "{{ $labels.service }} is down"
          description: "No requests received in the last 5 minutes and service is unreachable"
          runbook_url: "https://docs.example.com/runbooks/service-down"

  - name: rag_llm_alerts
    interval: 30s
    rules:
      # High LLM Error Rate
      - alert: LLMHighErrorRate
        expr: |
          (
            sum(rate(rag_llm_requests_total{status="error"}[5m])) by (model, provider)
            / sum(rate(rag_llm_requests_total[5m])) by (model, provider)
          ) > 0.05
        for: 5m
        labels:
          severity: critical
          team: ml-platform
        annotations:
          summary: "High LLM error rate for {{ $labels.model }}"
          description: "LLM error rate is {{ printf \"%.2f\" $value }}%"
          runbook_url: "https://docs.example.com/runbooks/llm-errors"
      
      # Rate Limited by LLM Provider
      - alert: LLMRateLimited
        expr: |
          sum(rate(rag_llm_requests_total{status="rate_limited"}[5m])) by (provider) > 0.1
        for: 2m
        labels:
          severity: warning
          team: ml-platform
        annotations:
          summary: "Rate limited by {{ $labels.provider }}"
          description: "Receiving rate limit responses from LLM provider"
          runbook_url: "https://docs.example.com/runbooks/llm-rate-limit"
      
      # High TTFT (Time to First Token)
      - alert: LLMHighTTFT
        expr: |
          histogram_quantile(0.95,
            sum(rate(rag_llm_time_to_first_token_seconds_bucket[5m])) by (le, model)
          ) > 2
        for: 5m
        labels:
          severity: warning
          team: ml-platform
        annotations:
          summary: "High time to first token for {{ $labels.model }}"
          description: "P95 TTFT is {{ printf \"%.2f\" $value }}s"
      
      # Token Usage Spike
      - alert: LLMTokenUsageSpike
        expr: |
          (
            sum(rate(rag_llm_tokens_total[1h])) 
            / sum(rate(rag_llm_tokens_total[24h] offset 1h))
          ) > 3
        for: 30m
        labels:
          severity: warning
          team: ml-platform
        annotations:
          summary: "LLM token usage spike detected"
          description: "Token usage is {{ printf \"%.1f\" $value }}x higher than baseline"

  - name: rag_retrieval_alerts
    interval: 30s
    rules:
      # High Retrieval Latency
      - alert: RetrievalHighLatency
        expr: |
          histogram_quantile(0.95,
            sum(rate(rag_retrieval_duration_seconds_bucket[5m])) by (le, strategy)
          ) > 0.5
        for: 5m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "High retrieval latency for {{ $labels.strategy }}"
          description: "P95 retrieval latency is {{ printf \"%.2f\" $value }}s"
      
      # Low Result Count (potential quality issue)
      - alert: RetrievalLowResults
        expr: |
          (
            sum(rate(rag_retrieval_result_count_bucket{le="1"}[1h])) 
            / sum(rate(rag_retrieval_result_count_count[1h]))
          ) > 0.2
        for: 30m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "High rate of low-result retrievals"
          description: "{{ printf \"%.1f\" $value }}% of queries return 0-1 results"
      
      # Vector DB Connection Issues
      - alert: VectorDBConnectionIssue
        expr: |
          sum(rate(rag_vector_db_errors_total[5m])) > 0.1
        for: 5m
        labels:
          severity: critical
          team: rag-platform
        annotations:
          summary: "Vector database connection issues"
          description: "Errors communicating with vector database"

  - name: rag_ingestion_alerts
    interval: 30s
    rules:
      # High Queue Depth
      - alert: IngestionQueueBacklog
        expr: |
          sum(rag_ingestion_queue_size) > 500
        for: 15m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "Ingestion queue backlog"
          description: "Queue depth is {{ $value }} documents"
          runbook_url: "https://docs.example.com/runbooks/queue-depth"
      
      # Critical Queue Depth
      - alert: IngestionQueueCritical
        expr: |
          sum(rag_ingestion_queue_size) > 2000
        for: 5m
        labels:
          severity: critical
          team: rag-platform
        annotations:
          summary: "Critical ingestion queue backlog"
          description: "Queue depth is {{ $value }} documents - immediate action required"
      
      # Ingestion Failures
      - alert: IngestionHighFailureRate
        expr: |
          (
            sum(rate(rag_documents_ingested_total{status="error"}[1h]))
            / sum(rate(rag_documents_ingested_total[1h]))
          ) > 0.1
        for: 30m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "High ingestion failure rate"
          description: "{{ printf \"%.1f\" $value }}% of documents failing to ingest"

  - name: rag_cache_alerts
    interval: 30s
    rules:
      # Low Cache Hit Rate
      - alert: CacheLowHitRate
        expr: |
          (
            sum(rate(rag_cache_hits_total[1h])) 
            / (sum(rate(rag_cache_hits_total[1h])) + sum(rate(rag_cache_misses_total[1h])))
          ) < 0.5
        for: 30m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "Low cache hit rate"
          description: "Cache hit rate is {{ printf \"%.1f\" $value }}%"
      
      # Cache Latency High
      - alert: CacheHighLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(rag_cache_latency_seconds_bucket[5m])) by (le, cache_type)
          ) > 0.01
        for: 5m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "High cache latency for {{ $labels.cache_type }}"
          description: "P99 cache latency is {{ printf \"%.3f\" $value }}s"
```

### SLO Burn Rate Alerts

```yaml
# rules/slo_alerts.yaml
groups:
  - name: slo_burn_rate_alerts
    interval: 30s
    rules:
      # Query Latency SLO - Fast burn (page immediately)
      - alert: SLOQueryLatencyFastBurn
        expr: |
          (
            1 - (
              sum(rate(rag_query_duration_seconds_bucket{le="2"}[5m]))
              / sum(rate(rag_query_duration_seconds_count[5m]))
            )
          ) > (0.01 * 14.4)
          and
          (
            1 - (
              sum(rate(rag_query_duration_seconds_bucket{le="2"}[1h]))
              / sum(rate(rag_query_duration_seconds_count[1h]))
            )
          ) > (0.01 * 14.4)
        for: 2m
        labels:
          severity: critical
          slo: query_latency
          window: 1h
        annotations:
          summary: "Query latency SLO burning fast"
          description: "Error budget being consumed at 14.4x normal rate"
          error_budget_impact: "Will exhaust 30-day budget in ~2 days at this rate"
          runbook_url: "https://docs.example.com/runbooks/slo-burn-rate"
          dashboard_url: "https://grafana.example.com/d/rag-slo"
      
      # Query Latency SLO - Slow burn (warning)
      - alert: SLOQueryLatencySlowBurn
        expr: |
          (
            1 - (
              sum(rate(rag_query_duration_seconds_bucket{le="2"}[6h]))
              / sum(rate(rag_query_duration_seconds_count[6h]))
            )
          ) > (0.01 * 6)
          and
          (
            1 - (
              sum(rate(rag_query_duration_seconds_bucket{le="2"}[30m]))
              / sum(rate(rag_query_duration_seconds_count[30m]))
            )
          ) > (0.01 * 6)
        for: 15m
        labels:
          severity: warning
          slo: query_latency
          window: 6h
        annotations:
          summary: "Query latency SLO burning slowly"
          description: "Error budget being consumed at 6x normal rate"
          error_budget_impact: "Will exhaust 30-day budget in ~5 days at this rate"
      
      # Availability SLO - Fast burn
      - alert: SLOAvailabilityFastBurn
        expr: |
          (
            sum(rate(rag_query_total{status="error"}[5m]))
            / sum(rate(rag_query_total[5m]))
          ) > (0.001 * 14.4)
          and
          (
            sum(rate(rag_query_total{status="error"}[1h]))
            / sum(rate(rag_query_total[1h]))
          ) > (0.001 * 14.4)
        for: 2m
        labels:
          severity: critical
          slo: availability
          window: 1h
        annotations:
          summary: "Availability SLO burning fast"
          description: "Error budget being consumed at 14.4x normal rate"
          error_budget_impact: "Will exhaust 30-day budget in ~2 days at this rate"
      
      # Availability SLO - Slow burn
      - alert: SLOAvailabilitySlowBurn
        expr: |
          (
            sum(rate(rag_query_total{status="error"}[3d]))
            / sum(rate(rag_query_total[3d]))
          ) > (0.001 * 1)
          and
          (
            sum(rate(rag_query_total{status="error"}[6h]))
            / sum(rate(rag_query_total[6h]))
          ) > (0.001 * 1)
        for: 1h
        labels:
          severity: warning
          slo: availability
          window: 3d
        annotations:
          summary: "Availability SLO burning slowly"
          description: "Error budget being consumed steadily"
          error_budget_impact: "On track to exhaust 30-day budget"
      
      # LLM TTFT SLO
      - alert: SLOLLMTTFTBurn
        expr: |
          (
            1 - (
              sum(rate(rag_llm_time_to_first_token_seconds_bucket{le="1"}[1h]))
              / sum(rate(rag_llm_time_to_first_token_seconds_count[1h]))
            )
          ) > (0.05 * 6)
        for: 15m
        labels:
          severity: warning
          slo: llm_ttft
          window: 1h
        annotations:
          summary: "LLM TTFT SLO at risk"
          description: "Time to first token error budget burning at 6x rate"
```

### Infrastructure Alerts

```yaml
# rules/infrastructure_alerts.yaml
groups:
  - name: infrastructure_alerts
    interval: 30s
    rules:
      # High CPU Usage
      - alert: HighCPUUsage
        expr: |
          (
            100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
          ) > 80
        for: 10m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is {{ printf \"%.1f\" $value }}%"
      
      # High Memory Usage
      - alert: HighMemoryUsage
        expr: |
          (
            (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)
            / node_memory_MemTotal_bytes
          ) * 100 > 85
        for: 10m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is {{ printf \"%.1f\" $value }}%"
      
      # Disk Space Low
      - alert: DiskSpaceLow
        expr: |
          (
            (node_filesystem_size_bytes - node_filesystem_avail_bytes)
            / node_filesystem_size_bytes
          ) * 100 > 80
        for: 10m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk usage is {{ printf \"%.1f\" $value }}%"
      
      # Pod Restarts
      - alert: PodRestartingFrequently
        expr: |
          increase(kube_pod_container_status_restarts_total[1h]) > 5
        for: 5m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "Pod {{ $labels.pod }} restarting frequently"
          description: "{{ $value }} restarts in the last hour"
      
      # Database Connection Pool Exhaustion
      - alert: DBConnectionPoolExhaustion
        expr: |
          (
            rag_db_connections_active
            / (rag_db_connections_active + rag_db_connections_idle)
          ) > 0.9
        for: 5m
        labels:
          severity: warning
          team: rag-platform
        annotations:
          summary: "Database connection pool nearly exhausted"
          description: "{{ printf \"%.1f\" $value }}% of connections in use"
```

### Runbook Example

```markdown
# Runbook: High Error Rate

## Alert: RAGHighErrorRate

### Overview
This alert fires when the error rate for a RAG service exceeds 5% over a 5-minute window.

### Severity
Critical

### Impact
Users may experience failed queries, incomplete responses, or degraded service.

### Investigation Steps

1. **Check the service logs**
   ```bash
   kubectl logs -l app=<service> --tail=100 -f
   ```

2. **Check recent deployments**
   ```bash
   kubectl rollout history deployment/<service>
   ```

3. **Check error breakdown in Grafana**
   - Open the [RAG Overview Dashboard](https://grafana.example.com/d/rag-overview)
   - Look at "Error Rate by Service" panel
   - Check "Request Breakdown by Status" for error types

4. **Check dependencies**
   - Vector database: Is Qdrant responding?
   - LLM service: Is the model responding?
   - Cache: Is Redis accessible?

5. **Check resource utilization**
   ```bash
   kubectl top pods -l app=<service>
   ```

### Common Causes

| Cause | Indicators | Resolution |
|-------|------------|------------|
| LLM provider outage | All LLM calls failing | Check provider status page, switch to backup |
| Vector DB connection issues | Connection errors in logs | Check Qdrant health, restart if needed |
| OOM kills | Pod restarts, memory errors | Scale up resources |
| Bad deployment | Errors started after deploy | Rollback deployment |
| Rate limiting | 429 errors | Add rate limiting, increase quotas |

### Resolution Steps

1. **If LLM provider issue:**
   ```bash
   # Switch to backup provider
   kubectl set env deployment/<service> LLM_PROVIDER=backup
   ```

2. **If resource issue:**
   ```bash
   # Scale up
   kubectl scale deployment/<service> --replicas=<n+2>
   ```

3. **If bad deployment:**
   ```bash
   # Rollback
   kubectl rollout undo deployment/<service>
   ```

### Escalation
If unresolved after 15 minutes, escalate to on-call ML engineer.

### Post-Incident
- Update this runbook with new findings
- Create ticket for root cause analysis
- Update alerting thresholds if needed
```

### Kubernetes Deployment

```yaml
# alertmanager.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alertmanager
  namespace: observability
spec:
  replicas: 2
  selector:
    matchLabels:
      app: alertmanager
  template:
    metadata:
      labels:
        app: alertmanager
    spec:
      containers:
        - name: alertmanager
          image: prom/alertmanager:v0.26.0
          args:
            - '--config.file=/etc/alertmanager/alertmanager.yaml'
            - '--storage.path=/alertmanager'
            - '--cluster.listen-address=0.0.0.0:9094'
            - '--cluster.peer=alertmanager-0.alertmanager:9094'
            - '--cluster.peer=alertmanager-1.alertmanager:9094'
          ports:
            - containerPort: 9093
              name: http
            - containerPort: 9094
              name: cluster
          env:
            - name: SLACK_WEBHOOK_URL
              valueFrom:
                secretKeyRef:
                  name: alertmanager-secrets
                  key: slack-webhook
            - name: PAGERDUTY_SERVICE_KEY
              valueFrom:
                secretKeyRef:
                  name: alertmanager-secrets
                  key: pagerduty-key
          resources:
            requests:
              memory: 128Mi
              cpu: 50m
            limits:
              memory: 256Mi
              cpu: 200m
          volumeMounts:
            - name: config
              mountPath: /etc/alertmanager
            - name: storage
              mountPath: /alertmanager
          livenessProbe:
            httpGet:
              path: /-/healthy
              port: 9093
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /-/ready
              port: 9093
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: config
          configMap:
            name: alertmanager-config
        - name: storage
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: alertmanager
  namespace: observability
spec:
  selector:
    app: alertmanager
  ports:
    - name: http
      port: 9093
      targetPort: 9093
    - name: cluster
      port: 9094
      targetPort: 9094
  clusterIP: None
---
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: rag-alerts
  namespace: observability
  labels:
    team: rag-pipeline
spec:
  groups:
    # Include all alert groups from rag_alerts.yaml
    - name: rag_request_alerts
      rules:
        - alert: RAGHighErrorRate
          expr: |
            (sum(rate(rag_query_total{status="error"}[5m])) by (service)
            / sum(rate(rag_query_total[5m])) by (service)) > 0.05
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "High error rate on {{ $labels.service }}"
```

### Alert Testing

```python
import pytest
from unittest.mock import Mock, patch
import yaml
from pathlib import Path


def load_alert_rules(path: str) -> dict:
    """Load alert rules from YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def test_all_alerts_have_required_fields():
    """Test all alerts have required annotations."""
    rules = load_alert_rules("rules/rag_alerts.yaml")
    
    for group in rules["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                assert "summary" in rule.get("annotations", {}), \
                    f"Alert {rule['alert']} missing summary"
                assert "severity" in rule.get("labels", {}), \
                    f"Alert {rule['alert']} missing severity"


def test_critical_alerts_have_runbooks():
    """Test critical alerts have runbook URLs."""
    rules = load_alert_rules("rules/rag_alerts.yaml")
    
    for group in rules["groups"]:
        for rule in group["rules"]:
            if rule.get("labels", {}).get("severity") == "critical":
                assert "runbook_url" in rule.get("annotations", {}), \
                    f"Critical alert {rule['alert']} missing runbook_url"


def test_slo_alerts_have_error_budget_info():
    """Test SLO alerts include error budget impact."""
    rules = load_alert_rules("rules/slo_alerts.yaml")
    
    for group in rules["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                annotations = rule.get("annotations", {})
                assert "error_budget_impact" in annotations, \
                    f"SLO alert {rule['alert']} missing error_budget_impact"


def test_alert_expressions_valid():
    """Test alert expressions are syntactically valid PromQL."""
    from prometheus_api_client import PrometheusConnect
    
    # This would require a running Prometheus instance
    # Skip in unit tests, run in integration tests
    pass


def test_alertmanager_config_valid():
    """Test Alertmanager config is valid YAML."""
    config = load_alert_rules("alertmanager/alertmanager.yaml")
    
    assert "route" in config
    assert "receivers" in config
    assert len(config["receivers"]) > 0


def test_all_severities_have_receivers():
    """Test all severity levels are routed to receivers."""
    config = load_alert_rules("alertmanager/alertmanager.yaml")
    
    routes = config["route"].get("routes", [])
    severities_routed = set()
    
    for route in routes:
        if "severity" in route.get("match", {}):
            severities_routed.add(route["match"]["severity"])
    
    assert "critical" in severities_routed
    assert "warning" in severities_routed


def test_inhibition_rules_present():
    """Test inhibition rules are configured."""
    config = load_alert_rules("alertmanager/alertmanager.yaml")
    
    assert "inhibit_rules" in config
    assert len(config["inhibit_rules"]) > 0
```

## Integration Tests

```python
@pytest.mark.integration
def test_alertmanager_api_health():
    """Test Alertmanager API is healthy."""
    import requests
    
    response = requests.get("http://alertmanager:9093/-/healthy")
    assert response.status_code == 200


@pytest.mark.integration
def test_prometheus_rules_loaded():
    """Test Prometheus has loaded alert rules."""
    import requests
    
    response = requests.get("http://prometheus:9090/api/v1/rules")
    data = response.json()
    
    assert data["status"] == "success"
    
    rule_names = [
        rule["name"]
        for group in data["data"]["groups"]
        for rule in group["rules"]
    ]
    
    assert "RAGHighErrorRate" in rule_names


@pytest.mark.integration
def test_alert_fires_correctly():
    """Test alert fires when threshold exceeded."""
    # This would inject test metrics and verify alert fires
    pass
```

## Dependencies

```
prometheus>=2.45.0
alertmanager>=0.26.0
```

## Definition of Done

- [ ] Alertmanager configuration with routing
- [ ] Slack integration with message templates
- [ ] PagerDuty integration for critical alerts
- [ ] RAG request alerts (error rate, latency)
- [ ] LLM service alerts (errors, rate limits, TTFT)
- [ ] Retrieval alerts (latency, low results)
- [ ] Ingestion alerts (queue depth, failures)
- [ ] Cache alerts (hit rate, latency)
- [ ] SLO burn rate alerts (fast and slow burn)
- [ ] Infrastructure alerts (CPU, memory, disk, pods)
- [ ] Inhibition rules configured
- [ ] All critical alerts have runbooks
- [ ] Runbooks documented for common issues
- [ ] Kubernetes deployment manifests
- [ ] Alertmanager HA cluster configured
- [ ] Alert testing framework
- [ ] >90% test coverage on rule validation
- [ ] Documentation complete
