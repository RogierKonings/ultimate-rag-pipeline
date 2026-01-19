# Runbook: RAG Error Budget Burn

## Alert

- **Name:** `SLOTenant_error_rateBurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** tenant_error_rate
- **Target:** 99% success rate per tenant

## Impact

Users are experiencing elevated error rates. The monthly error budget is being consumed faster than sustainable. At current rate, the 30-day error budget will be exhausted before the window ends.

## Investigation Steps

### 1. Check Service Health

```bash
kubectl get pods -n rag-pipeline
curl -s http://orchestrator:8003/health | jq
curl -s http://retrieval:8002/health | jq
```

### 2. Identify Error Source

Check Grafana dashboard: [SLO Overview](http://grafana:3000/d/slo-overview)

Query specific error types:
```promql
sum by (error_type, tenant_id) (rate(rag_queries_total{status="error"}[5m]))
```

### 3. Check Dependencies

```bash
# Qdrant
curl http://qdrant:6333/health

# OpenSearch
curl http://opensearch:9200/_cluster/health

# LLM Gateway
curl http://llm-gateway:8004/health
```

### 4. Review Recent Deployments

```bash
kubectl rollout history deployment/orchestrator -n rag-pipeline
kubectl rollout history deployment/retrieval -n rag-pipeline
```

## Mitigation

### If Qdrant/OpenSearch Unhealthy

Circuit breaker should activate degraded mode. Verify:
```promql
retrieval_service_degradation_mode{mode!="hybrid_full"} == 1
```

### If LLM Gateway Issues

- Check rate limits
- Verify model availability
- Consider switching to fallback model

### If Recent Deployment

```bash
kubectl rollout undo deployment/orchestrator -n rag-pipeline
```

### If Unknown Cause

- Enable debug logging temporarily
- Collect traces for failed requests via Jaeger

## Escalation

| Condition | Action |
|-----------|--------|
| Warning persists > 30 min | Page on-call SRE |
| Critical persists > 10 min | Declare incident |
| Budget exhausted | Immediate incident |

## Recovery Verification

- [ ] Error rate returns to < 1% per tenant
- [ ] Burn rate drops below 1x
- [ ] No new alerts for 15 min
- [ ] Error budget remaining stabilizes
