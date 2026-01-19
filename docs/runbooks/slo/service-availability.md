# Runbook: Service Availability SLO Breach

## Alert

- **Name:** `SLOquery_availabilityBurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** query_availability
- **Target:** 99.9% success rate

## Impact

RAG queries are failing at a higher rate than acceptable. Users are experiencing errors when asking questions. The availability error budget is being consumed rapidly.

## Investigation Steps

### 1. Check Current Error Rate

```promql
# Overall error rate
1 - (sum(rate(rag_query_total{status="success"}[5m])) / sum(rate(rag_query_total[5m])))

# Errors by type
sum(rate(rag_query_total{status="error"}[5m])) by (error_type)
```

### 2. Check All Service Health

```bash
# Quick health check all services
curl -s http://orchestrator:8003/health | jq
curl -s http://retrieval:8002/health | jq
curl -s http://llm-gateway:8004/health | jq
curl -s http://ingestion:8001/health | jq
```

```bash
# Pod status
kubectl get pods -n rag-pipeline
kubectl get pods -n rag-pipeline | grep -v Running
```

### 3. Check Error Logs

```bash
# Orchestrator errors
kubectl logs -n rag-pipeline deployment/orchestrator --since=10m | grep -i error

# Retrieval errors
kubectl logs -n rag-pipeline deployment/retrieval --since=10m | grep -i error
```

### 4. Check Dependencies

```bash
# Qdrant
curl http://qdrant:6333/health

# OpenSearch
curl http://opensearch:9200/_cluster/health

# Redis
redis-cli -h redis ping

# PostgreSQL
pg_isready -h postgres -p 5432
```

### 5. Identify Error Source

```promql
# Errors by component
sum(rate(rag_errors_total[5m])) by (component, error_type)

# Retrieval failures
sum(rate(rag_retrieval_duration_seconds_count[5m])) - sum(rate(rag_query_total{status="success"}[5m]))
```

### 6. Check Circuit Breaker Status

```promql
# Degradation mode active
retrieval_service_degradation_mode

# Circuit breaker state
retrieval_circuit_breaker_state
```

### 7. Check Recent Changes

```bash
# Recent deployments
kubectl rollout history deployment/orchestrator -n rag-pipeline
kubectl rollout history deployment/retrieval -n rag-pipeline

# Recent config changes
kubectl get events -n rag-pipeline --sort-by='.lastTimestamp' | head -20
```

## Common Failure Modes

### Database Connection Failures

**Symptoms:**
- Connection pool exhausted errors
- Timeout errors to PostgreSQL

**Check:**
```promql
pg_stat_activity_count{datname="ragpipeline"}
```

**Fix:**
- Increase connection pool size
- Check for long-running queries
- Restart affected pods

### Vector Store Failures

**Symptoms:**
- Qdrant connection errors
- Timeout on vector search

**Check:**
```bash
curl http://qdrant:6333/collections/documents
```

**Fix:**
- Circuit breaker should activate degraded mode
- If not, manually enable keyword-only search
- Check Qdrant cluster health

### LLM Gateway Failures

**Symptoms:**
- Model not available errors
- Rate limit exceeded
- Timeout on generation

**Check:**
```promql
sum(rate(rag_llm_requests_total{status="error"}[5m])) by (error_type)
```

**Fix:**
- Switch to fallback model
- Implement request queuing
- Check provider status

### Memory/Resource Exhaustion

**Symptoms:**
- OOMKilled pods
- CPU throttling

**Check:**
```bash
kubectl top pods -n rag-pipeline
kubectl describe pod <pod-name> -n rag-pipeline | grep -A5 "Last State"
```

**Fix:**
- Increase resource limits
- Scale horizontally
- Identify memory leaks

## Mitigation

### Immediate Actions

1. **Check if rollback needed:**
   ```bash
   kubectl rollout undo deployment/orchestrator -n rag-pipeline
   ```

2. **Scale up healthy components:**
   ```bash
   kubectl scale deployment orchestrator -n rag-pipeline --replicas=5
   ```

3. **Enable graceful degradation:**
   - Disable non-essential features
   - Serve cached responses where possible

### If Single Dependency Down

1. Circuit breaker should handle automatically
2. Verify degraded mode is active
3. Monitor that partial functionality works

### If Multiple Dependencies Down

1. Consider serving static responses
2. Implement maintenance mode
3. Communicate to users

### If Unknown Cause

1. Enable debug logging:
   ```bash
   kubectl set env deployment/orchestrator LOG_LEVEL=DEBUG -n rag-pipeline
   ```

2. Collect traces from Jaeger for failed requests

3. Check distributed tracing for error propagation

## Escalation

| Condition | Action |
|-----------|--------|
| Error rate > 1% for 15 min | Page on-call SRE |
| Error rate > 5% for 5 min | Declare incident |
| Complete service outage | Immediate incident, page all |

## Recovery Verification

- [ ] Error rate returns to < 0.1%
- [ ] Burn rate drops below 1x
- [ ] All service health checks passing
- [ ] No new error alerts for 15 min
- [ ] Dependent services healthy
- [ ] No pods in crash loop

## Post-Incident

- [ ] Document root cause
- [ ] Update runbook if new failure mode
- [ ] Consider adding automated remediation
- [ ] Review alerting thresholds
