# SLO Runbooks

> **Status:** Production Ready
> **Implemented:** US-10.3.4
> **Last Updated:** January 2026

## Overview

This directory contains runbooks for responding to SLO-related alerts. Each runbook provides investigation steps, mitigation actions, and escalation procedures.

## Available Runbooks

| Alert | Runbook | Description |
|-------|---------|-------------|
| `RAGErrorBudgetBurn_Critical` | [rag-error-budget-burn.md](./rag-error-budget-burn.md) | Error budget burning faster than sustainable |
| `RetrievalLatencySLO_Critical` | [retrieval-latency.md](./retrieval-latency.md) | Retrieval p95 latency exceeding 250ms target |
| `RAGE2ELatencySLO_Critical` | [rag-e2e-latency.md](./rag-e2e-latency.md) | End-to-end RAG latency exceeding 2s target |
| `ServiceAvailability_Critical` | [service-availability.md](./service-availability.md) | Service availability below 99.9% target |

## SLO Definitions

| SLO | Target | Window | Error Budget |
|-----|--------|--------|--------------|
| Retrieval Latency p95 | 95% < 250ms | 30 days | 5% |
| RAG E2E Latency p95 | 95% < 2000ms | 30 days | 5% |
| RAG Error Rate | < 1% per tenant | 30 days | 1% |
| Service Availability | > 99.9% | 30 days | 0.1% (~43 min/month) |

## Burn Rate Alert Thresholds

| Severity | Burn Rate | Explanation | Response Time |
|----------|-----------|-------------|---------------|
| Critical | 14.4x | 100% budget consumed in ~2 hours | Immediate |
| Critical | 6.0x | 100% budget consumed in ~5 hours | Within 30 min |
| Warning | 1.0x | Sustainable rate | Create ticket |

## Quick Reference

### Check Current SLO Status

```bash
# Query error budget remaining
curl -s "http://prometheus:9090/api/v1/query?query=slo:rag_error_rate:error_budget_remaining" | jq

# Query current burn rate
curl -s "http://prometheus:9090/api/v1/query?query=slo:rag_error_rate:burn_rate_1h" | jq

# Check retrieval latency SLI
curl -s "http://prometheus:9090/api/v1/query?query=sli:retrieval_latency:ratio_rate5m" | jq
```

### Service Health Checks

```bash
# Check all service health endpoints
curl -s http://orchestrator:8003/health | jq
curl -s http://retrieval:8002/health | jq
curl -s http://ingestion:8001/health | jq

# Check infrastructure health
curl -s http://qdrant:6333/health
curl -s http://opensearch:9200/_cluster/health | jq
```

### Recent Deployments

```bash
# Kubernetes
kubectl rollout history deployment/orchestrator -n rag-pipeline
kubectl rollout history deployment/retrieval -n rag-pipeline

# Recent changes
kubectl get events -n rag-pipeline --sort-by='.lastTimestamp' | tail -20
```

## Escalation Path

1. **On-call SRE**: First responder for all alerts
2. **Platform Team Lead**: If issue persists > 30 minutes
3. **Incident Commander**: For P1 incidents affecting multiple tenants

## Related Documentation

- [Observability Overview](../../observability/README.md)
- [SLO Definitions](../../../services/shared/observability/metrics/definitions/slo.py)
- [Correlation ID Propagation](../../observability/correlation-id-propagation.md) - For tracing requests
- [Trace Hierarchy](../../observability/trace-hierarchy.md) - For debugging with Jaeger
