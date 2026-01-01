# Health Check Specification

> **Applies to:** All Services  
> **Priority:** Critical for Production  
> **Cross-Reference:** US-1.6 (Kubernetes), All service APIs

## Overview

This document defines standardized health check endpoints and monitoring patterns for all services in the Ultimate RAG Pipeline. Consistent health checks enable reliable Kubernetes deployments, load balancer integration, and operational monitoring.

## Health Check Endpoints

All services MUST implement the following endpoints:

| Endpoint | Purpose | Response Time |
|----------|---------|---------------|
| `GET /health` | Basic liveness check | < 100ms |
| `GET /health/ready` | Readiness check with dependencies | < 500ms |
| `GET /health/live` | Kubernetes liveness probe | < 50ms |
| `GET /health/startup` | Startup probe for slow-starting services | < 1s |

## Response Schemas

### Basic Health Response

```python
from pydantic import BaseModel
from typing import Optional, Dict, Literal
from datetime import datetime

class HealthStatus(BaseModel):
    """Basic health response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    
class DetailedHealthResponse(BaseModel):
    """Detailed health response with dependency status."""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    uptime_seconds: float
    
    dependencies: Dict[str, "DependencyHealth"]
    
    # Optional degradation info
    degradation_level: Optional[str] = None
    active_fallbacks: Optional[list[str]] = None

class DependencyHealth(BaseModel):
    """Health status of a dependency."""
    name: str
    status: Literal["healthy", "unhealthy", "unknown"]
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    last_check: datetime
```

### Example Responses

**Healthy:**
```json
{
  "status": "healthy",
  "version": "1.2.3",
  "timestamp": "2025-12-18T12:00:00Z",
  "uptime_seconds": 86400.5,
  "dependencies": {
    "postgres": {
      "name": "PostgreSQL",
      "status": "healthy",
      "latency_ms": 2.5,
      "last_check": "2025-12-18T12:00:00Z"
    },
    "qdrant": {
      "name": "Qdrant Vector DB",
      "status": "healthy",
      "latency_ms": 5.1,
      "last_check": "2025-12-18T12:00:00Z"
    },
    "redis": {
      "name": "Redis Cache",
      "status": "healthy",
      "latency_ms": 1.2,
      "last_check": "2025-12-18T12:00:00Z"
    }
  }
}
```

**Degraded:**
```json
{
  "status": "degraded",
  "version": "1.2.3",
  "timestamp": "2025-12-18T12:00:00Z",
  "uptime_seconds": 86400.5,
  "degradation_level": "partial",
  "active_fallbacks": ["reranker", "embedding_cache"],
  "dependencies": {
    "postgres": {
      "name": "PostgreSQL",
      "status": "healthy",
      "latency_ms": 2.5,
      "last_check": "2025-12-18T12:00:00Z"
    },
    "embedding_service": {
      "name": "Embedding Service",
      "status": "unhealthy",
      "error": "Connection timeout after 5000ms",
      "last_check": "2025-12-18T11:59:55Z"
    }
  }
}
```

## Implementation

### FastAPI Health Router

```python
# services/shared/api/health.py
from fastapi import APIRouter, Response
from datetime import datetime
import time
import asyncio
from typing import Dict

router = APIRouter(tags=["health"])

# Track startup time
_startup_time = time.time()
_version = "1.0.0"  # Load from env or package

class HealthChecker:
    """Centralized health checking for all dependencies."""
    
    def __init__(self):
        self.checks: Dict[str, callable] = {}
        self._cache: Dict[str, DependencyHealth] = {}
        self._cache_ttl = 5.0  # seconds
        self._last_check = 0.0
    
    def register(self, name: str, check_fn: callable):
        """Register a health check function."""
        self.checks[name] = check_fn
    
    async def check_all(self, use_cache: bool = True) -> Dict[str, DependencyHealth]:
        """Run all health checks."""
        now = time.time()
        
        if use_cache and (now - self._last_check) < self._cache_ttl:
            return self._cache
        
        results = {}
        
        # Run checks concurrently with timeout
        tasks = {
            name: asyncio.create_task(
                asyncio.wait_for(check(), timeout=5.0)
            )
            for name, check in self.checks.items()
        }
        
        for name, task in tasks.items():
            try:
                start = time.time()
                await task
                latency = (time.time() - start) * 1000
                
                results[name] = DependencyHealth(
                    name=name,
                    status="healthy",
                    latency_ms=latency,
                    last_check=datetime.utcnow()
                )
            except asyncio.TimeoutError:
                results[name] = DependencyHealth(
                    name=name,
                    status="unhealthy",
                    error="Health check timed out",
                    last_check=datetime.utcnow()
                )
            except Exception as e:
                results[name] = DependencyHealth(
                    name=name,
                    status="unhealthy",
                    error=str(e),
                    last_check=datetime.utcnow()
                )
        
        self._cache = results
        self._last_check = now
        return results

# Global health checker instance
health_checker = HealthChecker()

@router.get("/health")
async def health():
    """Basic health check - always returns quickly."""
    return HealthStatus(
        status="healthy",
        version=_version,
        timestamp=datetime.utcnow()
    )

@router.get("/health/live")
async def liveness():
    """
    Kubernetes liveness probe.
    
    Returns 200 if the service is alive.
    Returns 503 if the service should be restarted.
    """
    return Response(status_code=200, content="OK")

@router.get("/health/ready")
async def readiness(response: Response):
    """
    Kubernetes readiness probe.
    
    Checks all dependencies and returns overall status.
    Returns 200 if ready to receive traffic.
    Returns 503 if not ready (still starting up or dependencies failing).
    """
    dependencies = await health_checker.check_all()
    
    # Determine overall status
    unhealthy_count = sum(1 for d in dependencies.values() if d.status == "unhealthy")
    total = len(dependencies)
    
    if unhealthy_count == 0:
        status = "healthy"
    elif unhealthy_count < total:
        status = "degraded"
    else:
        status = "unhealthy"
    
    result = DetailedHealthResponse(
        status=status,
        version=_version,
        timestamp=datetime.utcnow(),
        uptime_seconds=time.time() - _startup_time,
        dependencies=dependencies
    )
    
    # Set response code based on status
    if status == "unhealthy":
        response.status_code = 503
    
    return result

@router.get("/health/startup")
async def startup_probe(response: Response):
    """
    Kubernetes startup probe.
    
    For services that need time to initialize (e.g., loading models).
    Returns 200 when startup is complete.
    Returns 503 while still starting.
    """
    # Check critical dependencies only
    critical_deps = ["postgres"]  # Add service-specific critical deps
    
    dependencies = await health_checker.check_all()
    
    for dep_name in critical_deps:
        if dep_name in dependencies:
            if dependencies[dep_name].status == "unhealthy":
                response.status_code = 503
                return {"status": "starting", "waiting_for": dep_name}
    
    return {"status": "ready"}
```

### Dependency Health Checks

```python
# services/shared/api/health_checks.py
from qdrant_client import QdrantClient
from opensearchpy import AsyncOpenSearch
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text

async def check_postgres(engine: AsyncEngine) -> None:
    """Check PostgreSQL connection."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

async def check_qdrant(client: QdrantClient) -> None:
    """Check Qdrant connection."""
    collections = await client.get_collections()
    # Just confirming connection works

async def check_opensearch(client: AsyncOpenSearch) -> None:
    """Check OpenSearch connection."""
    await client.cluster.health()

async def check_redis(client: Redis) -> None:
    """Check Redis connection."""
    await client.ping()

async def check_embedding_service(url: str) -> None:
    """Check embedding service availability."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{url}/health", timeout=5.0)
        response.raise_for_status()

async def check_llm_service(url: str) -> None:
    """Check LLM service availability."""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{url}/health", timeout=5.0)
        response.raise_for_status()


def register_all_checks(
    health_checker: HealthChecker,
    db_engine: AsyncEngine,
    qdrant_client: QdrantClient,
    opensearch_client: AsyncOpenSearch,
    redis_client: Redis,
    config: dict
):
    """Register all health checks for a service."""
    
    health_checker.register("postgres", lambda: check_postgres(db_engine))
    health_checker.register("qdrant", lambda: check_qdrant(qdrant_client))
    health_checker.register("opensearch", lambda: check_opensearch(opensearch_client))
    health_checker.register("redis", lambda: check_redis(redis_client))
    
    if config.get("EMBEDDING_SERVICE_URL"):
        health_checker.register(
            "embedding_service",
            lambda: check_embedding_service(config["EMBEDDING_SERVICE_URL"])
        )
    
    if config.get("LLM_SERVICE_URL"):
        health_checker.register(
            "llm_service",
            lambda: check_llm_service(config["LLM_SERVICE_URL"])
        )
```

## Kubernetes Configuration

### Deployment with Health Probes

```yaml
# k8s/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingestion-service
spec:
  template:
    spec:
      containers:
      - name: ingestion-service
        image: rag-pipeline/ingestion-service:latest
        ports:
        - containerPort: 8001
        
        # Startup probe - allows slow startup
        startupProbe:
          httpGet:
            path: /health/startup
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 30  # 5s * 30 = 150s max startup time
        
        # Liveness probe - restart if unhealthy
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8001
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 3
        
        # Readiness probe - remove from service if not ready
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 5
          failureThreshold: 3
          successThreshold: 1
```

### Service-Specific Configurations

| Service | Startup Failure Threshold | Liveness Period | Readiness Period |
|---------|--------------------------|-----------------|------------------|
| Ingestion | 30 (150s) | 10s | 5s |
| Retrieval | 12 (60s) | 10s | 5s |
| Orchestrator | 12 (60s) | 10s | 5s |
| Embedding (GPU) | 60 (300s) | 15s | 10s |
| LLM Gateway (GPU) | 120 (600s) | 15s | 10s |

## Monitoring Integration

### Prometheus Metrics

```python
# services/shared/api/metrics.py
from prometheus_client import Gauge, Counter, Histogram

# Health status gauge (1 = healthy, 0.5 = degraded, 0 = unhealthy)
health_status = Gauge(
    "service_health_status",
    "Current health status of the service",
    ["service"]
)

# Dependency health gauges
dependency_health = Gauge(
    "dependency_health_status",
    "Health status of dependencies",
    ["service", "dependency"]
)

dependency_latency = Histogram(
    "dependency_health_check_latency_seconds",
    "Latency of health checks",
    ["service", "dependency"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

# Health check counters
health_check_total = Counter(
    "health_check_total",
    "Total health checks performed",
    ["service", "endpoint", "status"]
)
```

### Grafana Dashboard Queries

```promql
# Overall service health
avg(service_health_status{service=~"$service"})

# Dependency health matrix
dependency_health_status{service=~"$service"}

# Health check latency P95
histogram_quantile(0.95, 
  rate(dependency_health_check_latency_seconds_bucket[5m])
)

# Failed health checks rate
rate(health_check_total{status="failed"}[5m])
```

## Alerting Rules

```yaml
# prometheus/alerts/health.yml
groups:
  - name: service_health
    rules:
      - alert: ServiceUnhealthy
        expr: service_health_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.service }} is unhealthy"
          
      - alert: ServiceDegraded
        expr: service_health_status == 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Service {{ $labels.service }} is degraded"
          
      - alert: DependencyUnhealthy
        expr: dependency_health_status == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Dependency {{ $labels.dependency }} unhealthy for {{ $labels.service }}"
          
      - alert: HealthCheckLatencyHigh
        expr: histogram_quantile(0.95, rate(dependency_health_check_latency_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Health check latency high for {{ $labels.dependency }}"
```

## Best Practices

1. **Keep liveness probes simple** - Only check if the process is alive, not dependencies
2. **Use readiness probes for dependencies** - Don't serve traffic if critical deps are down
3. **Cache health check results** - Avoid hammering dependencies on every probe
4. **Set appropriate timeouts** - Match probe timeouts to realistic response times
5. **Use startup probes for slow services** - GPU services need longer startup times
6. **Expose metrics** - Make health data available for dashboards and alerts
7. **Log health changes** - Track when services transition between health states
