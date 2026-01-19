# Ingestion Rate Limiting

> **Status:** Production
> **Last Updated:** January 2026

This document describes the per-tenant rate limiting system for ingestion jobs, which prevents noisy tenants from starving others and ensures fair resource allocation.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Priority Queues](#priority-queues)
- [Prometheus Metrics](#prometheus-metrics)
- [Operational Guide](#operational-guide)

---

## Overview

The ingestion rate limiting system provides:

1. **Per-tenant concurrency limits** - Configurable max concurrent jobs per tenant
2. **Soft and hard limits** - Queue jobs when at capacity (soft) or reject with error (hard)
3. **Priority queues** - High, normal, and low priority queues for different tenant tiers
4. **Redis-based coordination** - Distributed state management across Celery workers
5. **Automatic dispatch** - Queued jobs are dispatched when slots become available

### Problem Solved

Without rate limiting:
- A tenant with many jobs can monopolize workers
- Other tenants experience delays or starvation
- No mechanism to prioritize important workloads
- Difficult to guarantee SLAs per tenant tier

With rate limiting:
- Fair resource allocation across tenants
- Predictable job processing times
- Tiered service levels via priority queues
- Protected system capacity for all users

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Ingestion API                                      │
│                                                                              │
│  POST /api/v1/ingest/sync                                                   │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                     IngestionRateLimiter                                 │ │
│  │                                                                          │ │
│  │   ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │   │                    try_acquire_slot()                           │   │ │
│  │   │                                                                 │   │ │
│  │   │   1. Get tenant limits from Redis                               │   │ │
│  │   │   2. Check current active jobs count                            │   │ │
│  │   │   3. If < limit: atomically add job to active set               │   │ │
│  │   │   4. If >= limit: return False                                  │   │ │
│  │   └─────────────────────────────────────────────────────────────────┘   │ │
│  │                            │                                             │ │
│  │                 ┌──────────┴──────────┐                                  │ │
│  │                 │                     │                                  │ │
│  │          slot acquired           at capacity                            │ │
│  │                 │                     │                                  │ │
│  │                 ▼                     ▼                                  │ │
│  │   ┌─────────────────────┐   ┌─────────────────────┐                     │ │
│  │   │  Process Document   │   │  Check hard_limit   │                     │ │
│  │   │                     │   │                     │                     │ │
│  │   │  ┌───────────────┐  │   │  hard=true: reject  │                     │ │
│  │   │  │ Celery Worker │  │   │  hard=false: queue  │                     │ │
│  │   │  └───────────────┘  │   └─────────────────────┘                     │ │
│  │   │         │           │             │                                  │ │
│  │   │         ▼           │             ▼                                  │ │
│  │   │  release_slot()     │   ┌─────────────────────┐                     │ │
│  │   │         │           │   │    Redis Queue      │                     │ │
│  │   │         ▼           │   │    (FIFO)           │                     │ │
│  │   │  process_queued()   │   └─────────────────────┘                     │ │
│  │   └─────────────────────┘                                               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│                                  Redis                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                        │  │
│  │  ingestion:rate_limit:active:{tenant_id}  → SET of job_ids            │  │
│  │  ingestion:rate_limit:limits:{tenant_id}  → HASH {max, priority, ...} │  │
│  │  ingestion:rate_limit:queued:{tenant_id}  → LIST of queued jobs       │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Tenant Limits Model

```python
@dataclass
class TenantLimits:
    """Rate limit configuration for a tenant."""

    max_concurrent_jobs: int = 10      # Max parallel jobs
    priority: Literal["high", "normal", "low"] = "normal"  # Queue priority
    hard_limit: bool = False           # True = reject, False = queue
```

### Default Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `max_concurrent_jobs` | 10 | Maximum simultaneous jobs per tenant |
| `priority` | `normal` | Queue routing (`high`, `normal`, `low`) |
| `hard_limit` | `false` | When at capacity: queue (false) or reject (true) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_DEFAULT_MAX_CONCURRENT` | 10 | Default max concurrent jobs |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |

---

## API Reference

### Get Tenant Rate Limits

```
GET /admin/tenants/{tenant_id}/rate-limits
```

**Response:**

```json
{
  "tenant_id": "tenant-123",
  "active_jobs": 5,
  "queued_jobs": 2,
  "max_concurrent": 10,
  "priority": "normal"
}
```

### Update Tenant Rate Limits

```
PUT /admin/tenants/{tenant_id}/rate-limits
```

**Request:**

```json
{
  "max_concurrent_jobs": 20,
  "priority": "high",
  "hard_limit": false
}
```

**Response:**

```json
{
  "status": "updated",
  "tenant_id": "tenant-123",
  "limits": {
    "max_concurrent_jobs": 20,
    "priority": "high",
    "hard_limit": false
  }
}
```

### Get Rate Limits Overview

```
GET /admin/rate-limits/overview
```

**Response:**

```json
{
  "total_active_tenants": 15,
  "tenants": [
    {
      "tenant_id": "tenant-123",
      "active_jobs": 8,
      "queued_jobs": 0,
      "max_concurrent": 10,
      "priority": "normal"
    },
    {
      "tenant_id": "tenant-456",
      "active_jobs": 20,
      "queued_jobs": 5,
      "max_concurrent": 20,
      "priority": "high"
    }
  ]
}
```

### Clear Tenant Queue

```
POST /admin/tenants/{tenant_id}/clear-queue
```

Emergency operation to clear all queued jobs for a tenant.

**Response:**

```json
{
  "status": "cleared",
  "jobs_removed": 12
}
```

---

## Priority Queues

The system uses three Celery queues with different priorities:

| Queue | Priority | Processing | Use Case |
|-------|----------|------------|----------|
| `ingestion_high` | 1 (highest) | Workers process first | Premium tenants, urgent jobs |
| `ingestion_normal` | 2 | Default processing | Standard tenants |
| `ingestion_low` | 3 (lowest) | Workers process last | Batch/background jobs |

### Celery Configuration

```python
# services/ingestion/celery_config.py

from kombu import Queue

app.conf.task_queues = [
    Queue("ingestion_high", routing_key="ingestion.high"),
    Queue("ingestion_normal", routing_key="ingestion.normal"),
    Queue("ingestion_low", routing_key="ingestion.low"),
]

app.conf.task_default_queue = "ingestion_normal"

# Workers prefetch 1 task at a time for fair scheduling
app.conf.worker_prefetch_multiplier = 1
```

### Worker Deployment

Deploy workers to consume from specific queues:

```bash
# High-priority workers (dedicated)
celery -A tasks worker -Q ingestion_high -c 4

# Normal-priority workers
celery -A tasks worker -Q ingestion_normal,ingestion_low -c 8

# All queues (default)
celery -A tasks worker -Q ingestion_high,ingestion_normal,ingestion_low -c 8
```

**Kubernetes Worker Configuration:**

```yaml
# High-priority workers
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingestion-worker-high
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: worker
          command: ["celery", "-A", "tasks", "worker", "-Q", "ingestion_high", "-c", "4"]

# Normal-priority workers
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingestion-worker-normal
spec:
  replicas: 4
  template:
    spec:
      containers:
        - name: worker
          command: ["celery", "-A", "tasks", "worker", "-Q", "ingestion_normal,ingestion_low", "-c", "8"]
```

---

## Prometheus Metrics

### Available Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `ingestion_active_jobs` | Gauge | `tenant_id` | Current active jobs per tenant |
| `ingestion_queued_jobs` | Gauge | `tenant_id` | Jobs waiting in queue per tenant |
| `ingestion_rate_limited_total` | Counter | `tenant_id`, `action` | Rate limit events (action: `queued` or `rejected`) |

### Example Queries

```promql
# Active jobs by tenant (top 10)
topk(10, ingestion_active_jobs)

# Rate limit hits per tenant (last hour)
sum(increase(ingestion_rate_limited_total[1h])) by (tenant_id, action)

# Tenants at or near capacity
ingestion_active_jobs / on(tenant_id) group_left max_concurrent_jobs >= 0.9

# Queue depth across all tenants
sum(ingestion_queued_jobs)
```

### Grafana Dashboard Panels

**Recommended panels:**

1. **Active Jobs Heatmap** - Active jobs by tenant over time
2. **Queue Depth** - Total queued jobs across system
3. **Rate Limit Events** - Stacked bar chart of queued vs rejected
4. **Top Tenants** - Table of highest resource consumers

---

## Operational Guide

### Monitoring

**Key indicators:**

- `ingestion_active_jobs` approaching limits consistently
- `ingestion_queued_jobs > 0` for extended periods
- `ingestion_rate_limited_total` with action=`rejected` increasing

**Alerts (recommended):**

```yaml
groups:
  - name: ingestion-rate-limiting
    rules:
      - alert: HighQueueDepth
        expr: sum(ingestion_queued_jobs) > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High ingestion queue depth"

      - alert: TenantRateRejections
        expr: rate(ingestion_rate_limited_total{action="rejected"}[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Tenant {{ $labels.tenant_id }} jobs being rejected"
```

### Troubleshooting

**Jobs stuck in queue:**

1. Check worker health: `celery -A tasks inspect active`
2. Verify Redis connectivity: `redis-cli ping`
3. Check for slot leaks: Compare active jobs in Redis vs actual running tasks
4. Consider clearing stale slots (see below)

**Slot leaks (jobs completed but slots not released):**

```python
# Manual slot cleanup script
import redis

r = redis.Redis.from_url("redis://localhost:6379")

# Get all active jobs for a tenant
active_key = "ingestion:rate_limit:active:tenant-123"
job_ids = r.smembers(active_key)

# Manually remove stale job IDs
for job_id in job_ids:
    # Check if job is actually running in Celery
    # If not, remove from active set
    r.srem(active_key, job_id)
```

**Emergency: Clear all limits for a tenant:**

```bash
# Via API
curl -X POST http://localhost:8001/admin/tenants/tenant-123/clear-queue

# Or directly in Redis
redis-cli DEL "ingestion:rate_limit:active:tenant-123"
redis-cli DEL "ingestion:rate_limit:queued:tenant-123"
```

### Capacity Planning

| Tenant Tier | Recommended `max_concurrent_jobs` | Priority |
|-------------|-----------------------------------|----------|
| Enterprise | 50-100 | `high` |
| Professional | 20-50 | `normal` |
| Starter | 5-10 | `normal` |
| Free | 2-5 | `low` |

**Total worker capacity formula:**

```
Total Capacity = (High Workers × Concurrency) + (Normal Workers × Concurrency)

Example:
- 2 high-priority workers with concurrency 4 = 8 high slots
- 4 normal workers with concurrency 8 = 32 normal/low slots
- Total system capacity = ~40 concurrent jobs
```

### Best Practices

1. **Set appropriate limits per tier** - Don't give all tenants the same limit
2. **Use soft limits (queue)** - Prefer queueing over rejection for better UX
3. **Monitor queue depth** - If consistently > 0, consider increasing capacity
4. **Review limits periodically** - Adjust based on actual usage patterns
5. **Use TTL on Redis keys** - The 24h TTL prevents slot leaks from crashes

---

## Related Documentation

- [Ingestion Service Overview](README.md)
- [Multi-Store Indexing](multi-store-indexing.md)
- [Resilience & Degradation](../resilience-degradation.md)
