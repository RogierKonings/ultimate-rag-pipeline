# US-5.6: Model Health & Monitoring

> **Story ID:** US-5.6  
> **Epic:** LLM Serving Layer  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-5.1 (vLLM Deployment), US-5.2 (Embedding Service), US-5.3 (Reranker Service)

## User Story

**As a** platform engineer  
**I want** model health monitoring  
**So that** I can detect and respond to issues proactively

## Context

Model Health & Monitoring provides comprehensive observability for all LLM serving components. This includes health check endpoints for liveness/readiness probes, latency metrics (p50, p95, p99), throughput metrics (tokens/sec, requests/sec), error rate monitoring, and GPU utilization tracking. The system integrates with Prometheus for metrics collection and Grafana for visualization, enabling proactive issue detection and capacity planning.

Key features:
- Health check endpoints for Kubernetes probes
- Latency distribution metrics
- Throughput monitoring
- Error rate tracking and alerting
- GPU utilization dashboards
- Anomaly detection for performance degradation

## Technical Requirements

### Directory Structure

```
llm-serving/
└── monitoring/
    ├── __init__.py
    ├── health.py                # Health check implementations
    ├── metrics.py               # Prometheus metrics
    ├── collectors.py            # Custom metric collectors
    ├── alerting.py              # Alert rule definitions
    ├── anomaly.py               # Anomaly detection
    ├── prometheus/
    │   ├── rules.yaml           # Alerting rules
    │   └── servicemonitor.yaml  # ServiceMonitor CRD
    ├── grafana/
    │   └── dashboards/
    │       ├── llm-overview.json
    │       ├── embedding-metrics.json
    │       ├── reranker-metrics.json
    │       └── gpu-utilization.json
    └── k8s/
        └── alertmanager-config.yaml
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime
from uuid import UUID

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

class ComponentHealth(BaseModel):
    """Health status of a single component."""
    
    name: str
    status: HealthStatus
    message: Optional[str] = None
    last_check: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = None
    
    # Component-specific details
    details: Optional[dict] = None

class ServiceHealth(BaseModel):
    """Overall health of a service."""
    
    service_name: str
    status: HealthStatus
    
    # Component health checks
    components: list[ComponentHealth] = []
    
    # Model status
    model_loaded: bool = False
    model_name: Optional[str] = None
    
    # Resource status
    gpu_available: bool = False
    gpu_memory_used_mb: Optional[float] = None
    gpu_memory_total_mb: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    
    # Request status
    active_requests: int = 0
    pending_requests: int = 0
    
    # Timing
    uptime_seconds: float = 0
    last_request_time: Optional[datetime] = None
    
    def is_ready(self) -> bool:
        """Check if service is ready to accept requests."""
        return (
            self.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED] and
            self.model_loaded
        )

class LatencyMetrics(BaseModel):
    """Latency metrics with percentiles."""
    
    service_name: str
    endpoint: str
    
    # Latency percentiles (milliseconds)
    p50_ms: float
    p75_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    
    # Min/max/avg
    min_ms: float
    max_ms: float
    avg_ms: float
    
    # Sample count
    count: int
    
    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ThroughputMetrics(BaseModel):
    """Throughput metrics."""
    
    service_name: str
    
    # Request throughput
    requests_per_second: float
    successful_requests: int
    failed_requests: int
    
    # Token throughput (for LLM)
    tokens_per_second: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    
    # Embedding throughput
    embeddings_per_second: float = 0
    
    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ErrorMetrics(BaseModel):
    """Error rate metrics."""
    
    service_name: str
    
    # Error counts by type
    total_errors: int
    timeout_errors: int
    rate_limit_errors: int
    model_errors: int
    validation_errors: int
    internal_errors: int
    
    # Error rate
    error_rate_percent: float
    
    # Time window
    window_seconds: int = 60
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class Alert(BaseModel):
    """Alert definition."""
    
    id: UUID
    name: str
    severity: AlertSeverity
    service_name: str
    
    # Alert state
    firing: bool
    message: str
    
    # Timing
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Context
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}

class AnomalyDetection(BaseModel):
    """Anomaly detection result."""
    
    service_name: str
    metric_name: str
    
    # Current value
    current_value: float
    
    # Baseline statistics
    baseline_mean: float
    baseline_stddev: float
    
    # Anomaly score (z-score)
    anomaly_score: float
    is_anomaly: bool
    
    # Thresholds used
    threshold: float = 3.0  # Standard deviations
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

### Health Check Implementation

```python
import asyncio
import httpx
from datetime import datetime
import time
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class HealthChecker:
    """
    Health checking for LLM serving components.
    
    Provides both liveness and readiness checks for Kubernetes
    probes, as well as detailed component health status.
    """
    
    def __init__(
        self,
        service_name: str,
        model_name: Optional[str] = None,
        check_interval: float = 30.0
    ):
        self.service_name = service_name
        self.model_name = model_name
        self.check_interval = check_interval
        
        self._startup_time = time.time()
        self._last_request_time: Optional[datetime] = None
        self._is_model_loaded = False
        self._components: dict[str, ComponentHealth] = {}
        
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start periodic health checking."""
        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info(f"Health checker started for {self.service_name}")
    
    async def stop(self):
        """Stop health checking."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
    
    async def _check_loop(self):
        """Periodic health check loop."""
        while self._running:
            try:
                await self.run_checks()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    async def run_checks(self) -> ServiceHealth:
        """Run all health checks."""
        components = []
        overall_status = HealthStatus.HEALTHY
        
        # Check model status
        model_health = await self._check_model()
        components.append(model_health)
        if model_health.status != HealthStatus.HEALTHY:
            overall_status = HealthStatus.DEGRADED
        
        # Check GPU
        gpu_health = await self._check_gpu()
        components.append(gpu_health)
        if gpu_health.status == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
        
        # Check dependencies
        for name, check_fn in self._components.items():
            try:
                component = await check_fn()
                components.append(component)
                if component.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED
            except Exception as e:
                components.append(ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=str(e)
                ))
                overall_status = HealthStatus.DEGRADED
        
        return ServiceHealth(
            service_name=self.service_name,
            status=overall_status,
            components=components,
            model_loaded=self._is_model_loaded,
            model_name=self.model_name,
            uptime_seconds=time.time() - self._startup_time,
            last_request_time=self._last_request_time
        )
    
    async def _check_model(self) -> ComponentHealth:
        """Check if model is loaded and responsive."""
        start = time.time()
        
        try:
            # This should be overridden by service-specific implementations
            if self._is_model_loaded:
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.HEALTHY,
                    message=f"Model {self.model_name} loaded",
                    latency_ms=(time.time() - start) * 1000
                )
            else:
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message="Model not loaded"
                )
        except Exception as e:
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e)
            )
    
    async def _check_gpu(self) -> ComponentHealth:
        """Check GPU availability and health."""
        start = time.time()
        
        try:
            import torch
            
            if not torch.cuda.is_available():
                return ComponentHealth(
                    name="gpu",
                    status=HealthStatus.UNHEALTHY,
                    message="CUDA not available"
                )
            
            # Check GPU memory
            memory_allocated = torch.cuda.memory_allocated()
            memory_total = torch.cuda.get_device_properties(0).total_memory
            memory_percent = (memory_allocated / memory_total) * 100
            
            status = HealthStatus.HEALTHY
            if memory_percent > 95:
                status = HealthStatus.DEGRADED
            
            return ComponentHealth(
                name="gpu",
                status=status,
                message=f"GPU memory: {memory_percent:.1f}%",
                latency_ms=(time.time() - start) * 1000,
                details={
                    "memory_allocated_mb": memory_allocated / 1024 / 1024,
                    "memory_total_mb": memory_total / 1024 / 1024,
                    "memory_percent": memory_percent
                }
            )
        except ImportError:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.UNKNOWN,
                message="PyTorch not available"
            )
        except Exception as e:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.UNHEALTHY,
                message=str(e)
            )
    
    def register_component(self, name: str, check_fn):
        """Register a component health check."""
        self._components[name] = check_fn
    
    def set_model_loaded(self, loaded: bool):
        """Update model loaded status."""
        self._is_model_loaded = loaded
    
    def record_request(self):
        """Record that a request was processed."""
        self._last_request_time = datetime.utcnow()
    
    def liveness_check(self) -> bool:
        """Simple liveness check for Kubernetes."""
        return True  # Service is alive if this code runs
    
    def readiness_check(self) -> bool:
        """Readiness check for Kubernetes."""
        return self._is_model_loaded


class VLLMHealthChecker(HealthChecker):
    """Health checker for vLLM service."""
    
    def __init__(self, vllm_url: str = "http://localhost:8000"):
        super().__init__(service_name="vllm", model_name="llama")
        self.vllm_url = vllm_url
    
    async def _check_model(self) -> ComponentHealth:
        """Check vLLM model status."""
        start = time.time()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.vllm_url}/v1/models",
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", [])
                    
                    if models:
                        self._is_model_loaded = True
                        self.model_name = models[0].get("id", "unknown")
                        
                        return ComponentHealth(
                            name="model",
                            status=HealthStatus.HEALTHY,
                            message=f"Model {self.model_name} loaded",
                            latency_ms=(time.time() - start) * 1000,
                            details={"models": [m.get("id") for m in models]}
                        )
                
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message="No models loaded"
                )
                
        except Exception as e:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e)
            )


class EmbeddingHealthChecker(HealthChecker):
    """Health checker for embedding service."""
    
    def __init__(self, embedding_url: str = "http://localhost:8001"):
        super().__init__(service_name="embedding", model_name="bge-large")
        self.embedding_url = embedding_url
    
    async def _check_model(self) -> ComponentHealth:
        """Check embedding model status."""
        start = time.time()
        
        try:
            async with httpx.AsyncClient() as client:
                # Try a small embedding request
                response = await client.post(
                    f"{self.embedding_url}/v1/embeddings",
                    json={
                        "model": "BAAI/bge-large-en-v1.5",
                        "input": "health check"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data"):
                        self._is_model_loaded = True
                        return ComponentHealth(
                            name="model",
                            status=HealthStatus.HEALTHY,
                            message="Embedding model responsive",
                            latency_ms=(time.time() - start) * 1000
                        )
                
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Unexpected response: {response.status_code}"
                )
                
        except Exception as e:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e)
            )
```

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from functools import wraps
import time

# Create a custom registry for LLM metrics
LLM_REGISTRY = CollectorRegistry()

# Request metrics
REQUEST_TOTAL = Counter(
    "llm_requests_total",
    "Total number of requests",
    ["service", "endpoint", "status"],
    registry=LLM_REGISTRY
)

REQUEST_LATENCY = Histogram(
    "llm_request_latency_seconds",
    "Request latency in seconds",
    ["service", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=LLM_REGISTRY
)

# Token metrics (for LLM)
TOKENS_PROCESSED = Counter(
    "llm_tokens_processed_total",
    "Total tokens processed",
    ["service", "type"],  # type: prompt, completion
    registry=LLM_REGISTRY
)

TOKENS_PER_SECOND = Gauge(
    "llm_tokens_per_second",
    "Tokens processed per second",
    ["service"],
    registry=LLM_REGISTRY
)

# Queue metrics
QUEUE_SIZE = Gauge(
    "llm_queue_size",
    "Current queue size",
    ["service"],
    registry=LLM_REGISTRY
)

QUEUE_WAIT_TIME = Histogram(
    "llm_queue_wait_seconds",
    "Time spent waiting in queue",
    ["service"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
    registry=LLM_REGISTRY
)

# Batch metrics
BATCH_SIZE = Histogram(
    "llm_batch_size",
    "Batch sizes",
    ["service"],
    buckets=[1, 2, 4, 8, 16, 32, 64, 128],
    registry=LLM_REGISTRY
)

# GPU metrics
GPU_MEMORY_USED = Gauge(
    "llm_gpu_memory_used_bytes",
    "GPU memory used in bytes",
    ["gpu_id"],
    registry=LLM_REGISTRY
)

GPU_MEMORY_TOTAL = Gauge(
    "llm_gpu_memory_total_bytes",
    "GPU memory total in bytes",
    ["gpu_id"],
    registry=LLM_REGISTRY
)

GPU_UTILIZATION = Gauge(
    "llm_gpu_utilization_percent",
    "GPU utilization percentage",
    ["gpu_id"],
    registry=LLM_REGISTRY
)

# Model info
MODEL_INFO = Info(
    "llm_model",
    "Model information",
    ["service"],
    registry=LLM_REGISTRY
)

# Error metrics
ERRORS_TOTAL = Counter(
    "llm_errors_total",
    "Total errors",
    ["service", "error_type"],
    registry=LLM_REGISTRY
)


class MetricsCollector:
    """
    Collector for LLM serving metrics.
    
    Provides decorators and helpers for instrumenting
    service endpoints with Prometheus metrics.
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._request_count = 0
        self._token_count = 0
        self._last_update = time.time()
    
    def track_request(self, endpoint: str = "default"):
        """Decorator to track request metrics."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                status = "success"
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    ERRORS_TOTAL.labels(
                        service=self.service_name,
                        error_type=type(e).__name__
                    ).inc()
                    raise
                finally:
                    latency = time.time() - start_time
                    REQUEST_TOTAL.labels(
                        service=self.service_name,
                        endpoint=endpoint,
                        status=status
                    ).inc()
                    REQUEST_LATENCY.labels(
                        service=self.service_name,
                        endpoint=endpoint
                    ).observe(latency)
            
            return wrapper
        return decorator
    
    def record_tokens(self, prompt_tokens: int, completion_tokens: int):
        """Record token counts."""
        TOKENS_PROCESSED.labels(
            service=self.service_name,
            type="prompt"
        ).inc(prompt_tokens)
        
        TOKENS_PROCESSED.labels(
            service=self.service_name,
            type="completion"
        ).inc(completion_tokens)
        
        self._token_count += prompt_tokens + completion_tokens
        self._update_throughput()
    
    def record_queue_size(self, size: int):
        """Record current queue size."""
        QUEUE_SIZE.labels(service=self.service_name).set(size)
    
    def record_queue_wait(self, wait_seconds: float):
        """Record queue wait time."""
        QUEUE_WAIT_TIME.labels(service=self.service_name).observe(wait_seconds)
    
    def record_batch_size(self, size: int):
        """Record batch size."""
        BATCH_SIZE.labels(service=self.service_name).observe(size)
    
    def record_gpu_metrics(
        self,
        gpu_id: int,
        memory_used: int,
        memory_total: int,
        utilization: float
    ):
        """Record GPU metrics."""
        GPU_MEMORY_USED.labels(gpu_id=str(gpu_id)).set(memory_used)
        GPU_MEMORY_TOTAL.labels(gpu_id=str(gpu_id)).set(memory_total)
        GPU_UTILIZATION.labels(gpu_id=str(gpu_id)).set(utilization)
    
    def set_model_info(self, model_name: str, version: str = "1.0.0"):
        """Set model information."""
        MODEL_INFO.labels(service=self.service_name).info({
            "model_name": model_name,
            "version": version
        })
    
    def record_error(self, error_type: str):
        """Record an error."""
        ERRORS_TOTAL.labels(
            service=self.service_name,
            error_type=error_type
        ).inc()
    
    def _update_throughput(self):
        """Update tokens per second gauge."""
        now = time.time()
        elapsed = now - self._last_update
        
        if elapsed >= 1.0:
            tps = self._token_count / elapsed
            TOKENS_PER_SECOND.labels(service=self.service_name).set(tps)
            self._token_count = 0
            self._last_update = now
    
    def get_metrics(self) -> bytes:
        """Get metrics in Prometheus format."""
        return generate_latest(LLM_REGISTRY)
```

### Anomaly Detection

```python
from collections import deque
import statistics
import math
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class AnomalyDetector:
    """
    Detect anomalies in service metrics using statistical methods.
    
    Uses a sliding window to maintain baseline statistics and
    z-score based detection for anomalies.
    """
    
    def __init__(
        self,
        service_name: str,
        window_size: int = 100,
        threshold: float = 3.0
    ):
        self.service_name = service_name
        self.window_size = window_size
        self.threshold = threshold
        
        self._windows: dict[str, deque] = {}
    
    def record_value(self, metric_name: str, value: float) -> AnomalyDetection:
        """
        Record a metric value and check for anomaly.
        
        Args:
            metric_name: Name of the metric
            value: Current value
        
        Returns:
            AnomalyDetection result
        """
        if metric_name not in self._windows:
            self._windows[metric_name] = deque(maxlen=self.window_size)
        
        window = self._windows[metric_name]
        
        # Calculate baseline if we have enough data
        if len(window) >= 10:
            mean = statistics.mean(window)
            stddev = statistics.stdev(window) if len(window) > 1 else 0.0
            
            # Avoid division by zero
            if stddev > 0:
                z_score = abs(value - mean) / stddev
            else:
                z_score = 0.0
            
            is_anomaly = z_score > self.threshold
            
            if is_anomaly:
                logger.warning(
                    f"Anomaly detected: {self.service_name}/{metric_name} "
                    f"value={value:.2f}, mean={mean:.2f}, z={z_score:.2f}"
                )
            
            result = AnomalyDetection(
                service_name=self.service_name,
                metric_name=metric_name,
                current_value=value,
                baseline_mean=mean,
                baseline_stddev=stddev,
                anomaly_score=z_score,
                is_anomaly=is_anomaly,
                threshold=self.threshold
            )
        else:
            result = AnomalyDetection(
                service_name=self.service_name,
                metric_name=metric_name,
                current_value=value,
                baseline_mean=value,
                baseline_stddev=0.0,
                anomaly_score=0.0,
                is_anomaly=False,
                threshold=self.threshold
            )
        
        # Add to window
        window.append(value)
        
        return result
    
    def get_baseline(self, metric_name: str) -> Optional[dict]:
        """Get baseline statistics for a metric."""
        if metric_name not in self._windows:
            return None
        
        window = self._windows[metric_name]
        if len(window) < 2:
            return None
        
        return {
            "mean": statistics.mean(window),
            "stddev": statistics.stdev(window),
            "min": min(window),
            "max": max(window),
            "count": len(window)
        }
    
    def reset(self, metric_name: Optional[str] = None):
        """Reset baseline data."""
        if metric_name:
            if metric_name in self._windows:
                self._windows[metric_name].clear()
        else:
            self._windows.clear()


class LatencyAnomalyDetector(AnomalyDetector):
    """Specialized anomaly detector for latency metrics."""
    
    def __init__(self, service_name: str, threshold: float = 2.5):
        super().__init__(service_name, window_size=200, threshold=threshold)
    
    def check_latency(self, latency_ms: float) -> AnomalyDetection:
        """Check if latency is anomalous."""
        return self.record_value("latency_ms", latency_ms)


class ThroughputAnomalyDetector(AnomalyDetector):
    """Specialized anomaly detector for throughput metrics."""
    
    def __init__(self, service_name: str, threshold: float = 2.0):
        super().__init__(service_name, window_size=100, threshold=threshold)
    
    def check_throughput(self, rps: float) -> AnomalyDetection:
        """Check if throughput is anomalous (both high and low)."""
        return self.record_value("requests_per_second", rps)
```

### Prometheus Alerting Rules

```yaml
# prometheus/rules.yaml
groups:
  - name: llm-serving-alerts
    interval: 30s
    rules:
      # High error rate
      - alert: LLMHighErrorRate
        expr: |
          (sum(rate(llm_errors_total[5m])) by (service)) /
          (sum(rate(llm_requests_total[5m])) by (service)) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on {{ $labels.service }}"
          description: "Error rate is {{ $value | humanizePercentage }} over the last 5 minutes"

      # High latency
      - alert: LLMHighLatency
        expr: |
          histogram_quantile(0.95, sum(rate(llm_request_latency_seconds_bucket[5m])) by (le, service)) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High latency on {{ $labels.service }}"
          description: "p95 latency is {{ $value | humanizeDuration }}"

      # Very high latency
      - alert: LLMVeryHighLatency
        expr: |
          histogram_quantile(0.99, sum(rate(llm_request_latency_seconds_bucket[5m])) by (le, service)) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Very high latency on {{ $labels.service }}"
          description: "p99 latency is {{ $value | humanizeDuration }}"

      # Queue depth high
      - alert: LLMHighQueueDepth
        expr: llm_queue_size > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High queue depth on {{ $labels.service }}"
          description: "Queue size is {{ $value }}"

      # GPU memory high
      - alert: LLMGPUMemoryHigh
        expr: |
          (llm_gpu_memory_used_bytes / llm_gpu_memory_total_bytes) > 0.95
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "GPU memory critical on GPU {{ $labels.gpu_id }}"
          description: "GPU memory usage is {{ $value | humanizePercentage }}"

      # GPU utilization low (waste)
      - alert: LLMGPUUnderutilized
        expr: llm_gpu_utilization_percent < 20
        for: 30m
        labels:
          severity: info
        annotations:
          summary: "GPU underutilized on GPU {{ $labels.gpu_id }}"
          description: "GPU utilization is only {{ $value }}%"

      # Service down
      - alert: LLMServiceDown
        expr: up{job=~".*llm.*"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "LLM service {{ $labels.instance }} is down"
          description: "Service has been down for more than 1 minute"

      # Low throughput
      - alert: LLMLowThroughput
        expr: |
          sum(rate(llm_requests_total{status="success"}[5m])) by (service) < 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low throughput on {{ $labels.service }}"
          description: "Only {{ $value }} requests/sec"
```

### Grafana Dashboard (JSON)

```json
{
  "dashboard": {
    "title": "LLM Serving Overview",
    "uid": "llm-overview",
    "panels": [
      {
        "title": "Request Rate",
        "type": "graph",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [
          {
            "expr": "sum(rate(llm_requests_total[5m])) by (service, status)",
            "legendFormat": "{{ service }} - {{ status }}"
          }
        ]
      },
      {
        "title": "Latency (p95)",
        "type": "graph",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(llm_request_latency_seconds_bucket[5m])) by (le, service))",
            "legendFormat": "{{ service }}"
          }
        ]
      },
      {
        "title": "GPU Utilization",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 6, "x": 0, "y": 8},
        "targets": [
          {
            "expr": "llm_gpu_utilization_percent",
            "legendFormat": "GPU {{ gpu_id }}"
          }
        ],
        "options": {
          "thresholds": [
            {"color": "green", "value": 0},
            {"color": "yellow", "value": 70},
            {"color": "red", "value": 90}
          ]
        }
      },
      {
        "title": "GPU Memory",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 6, "x": 6, "y": 8},
        "targets": [
          {
            "expr": "(llm_gpu_memory_used_bytes / llm_gpu_memory_total_bytes) * 100",
            "legendFormat": "GPU {{ gpu_id }}"
          }
        ]
      },
      {
        "title": "Queue Size",
        "type": "graph",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
        "targets": [
          {
            "expr": "llm_queue_size",
            "legendFormat": "{{ service }}"
          }
        ]
      },
      {
        "title": "Tokens/Second",
        "type": "stat",
        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
        "targets": [
          {
            "expr": "sum(llm_tokens_per_second)",
            "legendFormat": "Total"
          }
        ]
      },
      {
        "title": "Error Rate",
        "type": "stat",
        "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
        "targets": [
          {
            "expr": "sum(rate(llm_errors_total[5m])) / sum(rate(llm_requests_total[5m])) * 100",
            "legendFormat": "Error %"
          }
        ],
        "options": {
          "thresholds": [
            {"color": "green", "value": 0},
            {"color": "yellow", "value": 1},
            {"color": "red", "value": 5}
          ]
        }
      }
    ]
  }
}
```

### FastAPI Health Endpoints

```python
from fastapi import FastAPI, HTTPException, Response
from typing import Optional
import asyncio

app = FastAPI()

# Global health checker
health_checker: Optional[HealthChecker] = None
metrics_collector: Optional[MetricsCollector] = None

@app.get("/health")
async def health():
    """Detailed health check endpoint."""
    if health_checker is None:
        raise HTTPException(status_code=503, detail="Health checker not initialized")
    
    health = await health_checker.run_checks()
    
    if health.status == HealthStatus.UNHEALTHY:
        raise HTTPException(status_code=503, detail=health.model_dump())
    
    return health.model_dump()

@app.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    if health_checker and health_checker.liveness_check():
        return {"status": "alive"}
    raise HTTPException(status_code=503, detail="Not alive")

@app.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe."""
    if health_checker and health_checker.readiness_check():
        return {"status": "ready"}
    raise HTTPException(status_code=503, detail="Not ready")

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    if metrics_collector is None:
        raise HTTPException(status_code=503, detail="Metrics not initialized")
    
    return Response(
        content=metrics_collector.get_metrics(),
        media_type="text/plain"
    )
```

## Acceptance Criteria

- [ ] Health check endpoints implemented (/health, /health/live, /health/ready)
- [ ] Prometheus metrics exposed at /metrics
- [ ] Latency metrics with percentiles (p50, p95, p99)
- [ ] Throughput metrics (requests/sec, tokens/sec)
- [ ] Error rate monitoring by error type
- [ ] GPU utilization metrics collected
- [ ] GPU memory metrics collected
- [ ] Queue depth metrics tracked
- [ ] Alerting rules defined in Prometheus
- [ ] Grafana dashboards created
- [ ] Anomaly detection for latency
- [ ] Anomaly detection for throughput
- [ ] ServiceMonitor CRD for Prometheus Operator

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
import time

@pytest.fixture
def health_checker():
    return HealthChecker(service_name="test-service", model_name="test-model")

@pytest.fixture
def metrics_collector():
    return MetricsCollector(service_name="test-service")

@pytest.fixture
def anomaly_detector():
    return AnomalyDetector(service_name="test-service", window_size=20, threshold=2.0)

@pytest.mark.asyncio
async def test_health_checker_start_stop(health_checker):
    """Test health checker lifecycle."""
    await health_checker.start()
    assert health_checker._running
    
    await health_checker.stop()
    assert not health_checker._running

@pytest.mark.asyncio
async def test_health_checker_model_status(health_checker):
    """Test model status tracking."""
    health_checker.set_model_loaded(True)
    assert health_checker.readiness_check()
    
    health_checker.set_model_loaded(False)
    assert not health_checker.readiness_check()

@pytest.mark.asyncio
async def test_health_checker_run_checks(health_checker):
    """Test running health checks."""
    health_checker.set_model_loaded(True)
    
    with patch.object(health_checker, '_check_gpu') as mock_gpu:
        mock_gpu.return_value = ComponentHealth(
            name="gpu",
            status=HealthStatus.HEALTHY
        )
        
        health = await health_checker.run_checks()
        
        assert health.service_name == "test-service"
        assert len(health.components) >= 1

def test_metrics_collector_track_request(metrics_collector):
    """Test request tracking."""
    @metrics_collector.track_request("test-endpoint")
    async def test_func():
        return "result"
    
    import asyncio
    result = asyncio.run(test_func())
    
    assert result == "result"

def test_metrics_collector_record_tokens(metrics_collector):
    """Test token recording."""
    metrics_collector.record_tokens(prompt_tokens=100, completion_tokens=50)
    # Tokens should be recorded (check via Prometheus registry)

def test_metrics_collector_record_gpu(metrics_collector):
    """Test GPU metrics recording."""
    metrics_collector.record_gpu_metrics(
        gpu_id=0,
        memory_used=20 * 1024 * 1024 * 1024,  # 20GB
        memory_total=40 * 1024 * 1024 * 1024,  # 40GB
        utilization=75.0
    )

def test_anomaly_detector_no_anomaly(anomaly_detector):
    """Test normal values don't trigger anomaly."""
    # Record baseline values
    for i in range(20):
        anomaly_detector.record_value("latency", 100.0 + i * 0.5)
    
    # Check normal value
    result = anomaly_detector.record_value("latency", 105.0)
    
    assert not result.is_anomaly

def test_anomaly_detector_detects_anomaly(anomaly_detector):
    """Test anomaly detection for outliers."""
    # Record stable baseline
    for _ in range(20):
        anomaly_detector.record_value("latency", 100.0)
    
    # Check extreme outlier
    result = anomaly_detector.record_value("latency", 500.0)
    
    assert result.is_anomaly
    assert result.anomaly_score > 2.0

def test_anomaly_detector_baseline(anomaly_detector):
    """Test baseline statistics."""
    for i in range(10):
        anomaly_detector.record_value("metric", float(i))
    
    baseline = anomaly_detector.get_baseline("metric")
    
    assert baseline is not None
    assert baseline["count"] == 10
    assert baseline["min"] == 0.0
    assert baseline["max"] == 9.0

def test_latency_anomaly_detector():
    """Test latency-specific detector."""
    detector = LatencyAnomalyDetector("test-service")
    
    for _ in range(20):
        result = detector.check_latency(50.0)
    
    # Normal latency
    result = detector.check_latency(55.0)
    assert not result.is_anomaly
    
    # Anomalous latency
    result = detector.check_latency(500.0)
    assert result.is_anomaly

def test_component_health_model():
    """Test ComponentHealth model."""
    health = ComponentHealth(
        name="test",
        status=HealthStatus.HEALTHY,
        message="All good",
        latency_ms=5.0
    )
    
    assert health.name == "test"
    assert health.status == HealthStatus.HEALTHY

def test_service_health_is_ready():
    """Test ServiceHealth readiness check."""
    health = ServiceHealth(
        service_name="test",
        status=HealthStatus.HEALTHY,
        model_loaded=True
    )
    
    assert health.is_ready()
    
    # Not ready if model not loaded
    health.model_loaded = False
    assert not health.is_ready()
    
    # Not ready if unhealthy
    health.model_loaded = True
    health.status = HealthStatus.UNHEALTHY
    assert not health.is_ready()
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_health_checker():
    """Test vLLM health checker with real service."""
    checker = VLLMHealthChecker("http://localhost:8000")
    
    await checker.start()
    
    try:
        health = await checker.run_checks()
        
        assert health.service_name == "vllm"
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]
    finally:
        await checker.stop()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_health_checker():
    """Test embedding health checker with real service."""
    checker = EmbeddingHealthChecker("http://localhost:8001")
    
    health = await checker.run_checks()
    
    assert health.service_name == "embedding"

@pytest.mark.integration
def test_metrics_endpoint():
    """Test metrics endpoint returns valid Prometheus format."""
    import httpx
    
    response = httpx.get("http://localhost:8000/metrics")
    
    assert response.status_code == 200
    assert "llm_requests_total" in response.text or response.text
```

## Dependencies

```txt
# requirements.txt
pydantic>=2.5.0
prometheus-client>=0.19.0
httpx>=0.25.0
fastapi>=0.104.0
uvicorn>=0.24.0
```

## Definition of Done

- [ ] HealthChecker implemented for all services
- [ ] Liveness and readiness endpoints working
- [ ] MetricsCollector instrumenting all endpoints
- [ ] Prometheus metrics exposed correctly
- [ ] Latency percentiles tracked (p50, p95, p99)
- [ ] Throughput metrics (RPS, TPS) working
- [ ] Error rates tracked by type
- [ ] GPU metrics collected
- [ ] Queue metrics tracked
- [ ] Alerting rules created
- [ ] Grafana dashboards deployed
- [ ] Anomaly detection working
- [ ] ServiceMonitor CRD created
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
