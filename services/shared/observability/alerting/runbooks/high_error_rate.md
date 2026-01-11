# Runbook: RAGHighErrorRate

## Alert Details

- **Alert Name:** RAGHighErrorRate
- **Severity:** Critical
- **Service:** rag-pipeline
- **Threshold:** Error rate > 5% over 5 minutes

## Description

This alert fires when the RAG pipeline experiences a high rate of errors. This indicates that a significant portion of user queries are failing.

## Impact

- Users may receive errors instead of answers
- SLO compliance is at risk
- User experience degradation
- Potential data loss if ingestion is affected

## Investigation Steps

### 1. Check Current Error Rate

```promql
sum(rate(rag_query_total{status="error"}[5m])) / sum(rate(rag_query_total[5m])) * 100
```

### 2. Identify Error Sources

```promql
# Errors by service
sum(rate(rag_query_total{status="error"}[5m])) by (service)

# Errors by error type
sum(rate(rag_errors_total[5m])) by (error_type, component)
```

### 3. Check Recent Deployments

```bash
kubectl get pods -n rag-pipeline -o wide --sort-by='.status.startTime'
kubectl rollout history deployment -n rag-pipeline
```

### 4. Review Error Logs

```logql
{namespace="rag-pipeline"} |= "error" | json | level="ERROR"
```

### 5. Check Downstream Dependencies

- Qdrant health: `rag_component_health{component="qdrant"}`
- OpenSearch health: `rag_component_health{component="opensearch"}`
- Redis health: `rag_component_health{component="redis"}`
- PostgreSQL connections: `rag_db_pool_connections_active`

## Remediation Steps

### If caused by recent deployment:

1. Identify the problematic deployment
2. Roll back:
   ```bash
   kubectl rollout undo deployment/<service-name> -n rag-pipeline
   ```
3. Verify error rate decreases

### If caused by downstream service:

1. Check the specific service health
2. Restart if necessary:
   ```bash
   kubectl rollout restart deployment/<service-name> -n rag-pipeline
   ```
3. Scale up if resource-related:
   ```bash
   kubectl scale deployment/<service-name> --replicas=<count> -n rag-pipeline
   ```

### If caused by resource exhaustion:

1. Check CPU/memory limits
2. Scale horizontally or vertically
3. Review recent traffic patterns

## Escalation

If unable to resolve within 15 minutes:

1. Page on-call engineer via PagerDuty
2. Start incident channel in Slack (#rag-incidents)
3. Notify stakeholders

## Related Dashboards

- [RAG Overview](http://grafana:3000/d/rag-overview)
- [Error Analysis](http://grafana:3000/d/rag-errors)

## Related Alerts

- RAGHighLatency
- RAGComponentUnhealthy
