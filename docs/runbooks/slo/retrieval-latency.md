# Runbook: Retrieval Latency SLO Breach

## Alert

- **Name:** `SLOretrieval_latency_p95BurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** retrieval_latency_p95
- **Target:** 95% of requests under 250ms

## Impact

Retrieval operations are taking longer than acceptable. Users experience slow query responses. The latency error budget is being consumed faster than sustainable.

## Investigation Steps

### 1. Check Current Latency Percentiles

```promql
histogram_quantile(0.95, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le))
histogram_quantile(0.99, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le))
```

### 2. Identify Slow Component

Check which search type is slow:

```promql
histogram_quantile(0.95, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le, search_type))
```

### 3. Check Vector Store (Qdrant)

```bash
# Health check
curl http://qdrant:6333/health

# Collection info
curl http://qdrant:6333/collections/documents

# Check cluster status
curl http://qdrant:6333/cluster
```

Look for:
- High memory usage
- Slow HNSW index
- Network latency

### 4. Check Keyword Store (OpenSearch)

```bash
# Cluster health
curl http://opensearch:9200/_cluster/health

# Node stats
curl http://opensearch:9200/_nodes/stats

# Index stats
curl http://opensearch:9200/documents/_stats
```

Look for:
- GC pressure
- Slow queries
- Index fragmentation

### 5. Check Embedding Service

```promql
histogram_quantile(0.95, sum(rate(rag_embedding_duration_seconds_bucket[5m])) by (le))
```

```bash
curl http://embedding:8080/health
```

### 6. Check Reranker Performance

```promql
histogram_quantile(0.95, sum(rate(rag_rerank_duration_seconds_bucket[5m])) by (le))
```

### 7. Review Query Patterns

```promql
# Query rate by mode
sum(rate(rag_query_total[5m])) by (mode)

# Result counts
histogram_quantile(0.5, sum(rate(rag_retrieval_result_count_bucket[5m])) by (le))
```

## Mitigation

### If Qdrant Slow

1. Check HNSW index parameters:
   ```bash
   curl http://qdrant:6333/collections/documents | jq '.result.config.hnsw_config'
   ```

2. Consider reducing `ef` search parameter temporarily
3. Scale Qdrant replicas if capacity issue

### If OpenSearch Slow

1. Force merge to reduce segments:
   ```bash
   curl -X POST "http://opensearch:9200/documents/_forcemerge?max_num_segments=1"
   ```

2. Clear field data cache:
   ```bash
   curl -X POST "http://opensearch:9200/documents/_cache/clear"
   ```

3. Scale nodes if capacity issue

### If Embedding Service Slow

1. Check batch sizes - reduce if needed
2. Check GPU memory usage
3. Scale embedding service replicas

### If Reranker Slow

1. Reduce rerank batch size
2. Reduce top-k for reranking
3. Consider disabling reranking temporarily (quality tradeoff)

### If Query Volume Spike

1. Enable query caching more aggressively
2. Implement rate limiting per tenant
3. Scale retrieval service horizontally

## Escalation

| Condition | Action |
|-----------|--------|
| p95 > 500ms for 10 min | Page on-call SRE |
| p95 > 1s for 5 min | Declare incident |
| Complete timeout failures | Immediate incident |

## Recovery Verification

- [ ] p95 latency returns to < 250ms
- [ ] Burn rate drops below 1x
- [ ] No new alerts for 15 min
- [ ] All backend services healthy
