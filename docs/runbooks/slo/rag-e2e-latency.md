# Runbook: RAG End-to-End Latency SLO Breach

## Alert

- **Name:** `SLOrag_e2e_latency_p95BurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** rag_e2e_latency_p95
- **Target:** 95% of requests under 2000ms

## Impact

Complete RAG queries are taking longer than acceptable. Users experience slow response times for their questions. This affects overall user experience and may cause timeouts on client side.

## Investigation Steps

### 1. Check Current E2E Latency

```promql
histogram_quantile(0.95, sum(rate(rag_e2e_latency_seconds_bucket[5m])) by (le))
histogram_quantile(0.99, sum(rate(rag_e2e_latency_seconds_bucket[5m])) by (le))
```

### 2. Break Down by Component

Check each stage of the RAG pipeline:

```promql
# Retrieval stage
histogram_quantile(0.95, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le))

# LLM generation stage
histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le))

# Time to first token
histogram_quantile(0.95, sum(rate(rag_llm_ttft_seconds_bucket[5m])) by (le))
```

### 3. Check Orchestrator Service

```bash
kubectl get pods -n rag-pipeline -l app=orchestrator
curl -s http://orchestrator:8003/health | jq
```

```promql
# Active queries
rag_query_active

# Query rate
sum(rate(rag_query_total[5m]))
```

### 4. Check LLM Gateway

```bash
curl -s http://llm-gateway:8004/health | jq
```

```promql
# LLM request rate and errors
sum(rate(rag_llm_requests_total[5m])) by (status, model)

# Token throughput
sum(rate(rag_llm_output_tokens_total[5m]))
```

### 5. Check for Queuing

```promql
# Queue depth if available
rag_queue_size{queue_name="default"}

# Concurrent requests
rag_query_active
```

### 6. Check Dependencies

```bash
# All service health
curl http://orchestrator:8003/health
curl http://retrieval:8002/health
curl http://llm-gateway:8004/health
```

## Root Cause Analysis

### Latency Budget Breakdown (Target: 2000ms)

| Component | Budget | Check |
|-----------|--------|-------|
| Query preprocessing | 50ms | Usually not the issue |
| Retrieval (semantic + keyword) | 250ms | See retrieval-latency runbook |
| Reranking | 200ms | Check reranker metrics |
| LLM generation | 1500ms | Most variable component |

### Common Causes

1. **LLM Slowdown** (most common)
   - Model overloaded
   - Long context windows
   - Complex prompts

2. **Retrieval Delay**
   - See [retrieval-latency runbook](./retrieval-latency.md)

3. **Network Issues**
   - Inter-service latency
   - DNS resolution delays

4. **Resource Contention**
   - CPU throttling
   - Memory pressure
   - I/O bottlenecks

## Mitigation

### If LLM Is Slow

1. Check model load:
   ```promql
   sum(rate(rag_llm_requests_total[1m])) by (model)
   ```

2. Consider switching to faster model:
   ```bash
   # Update model routing config
   kubectl edit configmap llm-gateway-config -n rag-pipeline
   ```

3. Reduce max output tokens if appropriate

4. Scale LLM inference pods if using vLLM

### If Retrieval Is Slow

Follow [retrieval-latency runbook](./retrieval-latency.md)

### If Queue Buildup

1. Scale orchestrator horizontally:
   ```bash
   kubectl scale deployment orchestrator -n rag-pipeline --replicas=3
   ```

2. Implement request shedding for non-critical queries

### If Network Issues

1. Check inter-pod latency
2. Review network policies
3. Check DNS resolution times

### Emergency: Enable Degraded Mode

If latency is critical and affecting users:

1. Disable reranking (saves ~200ms)
2. Reduce retrieval top-k
3. Use smaller/faster LLM model
4. Enable aggressive response caching

## Escalation

| Condition | Action |
|-----------|--------|
| p95 > 3s for 15 min | Page on-call SRE |
| p95 > 5s for 5 min | Declare incident |
| Widespread timeouts | Immediate incident |

## Recovery Verification

- [ ] p95 E2E latency returns to < 2000ms
- [ ] Burn rate drops below 1x
- [ ] All pipeline components healthy
- [ ] No client-side timeout errors
- [ ] LLM response times normal
