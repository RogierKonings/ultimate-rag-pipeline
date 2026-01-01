# US-6.2: Prometheus Metrics

> **Story ID:** US-6.2  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-6.1 (OpenTelemetry Integration)

## User Story

**As a** SRE  
**I want** metrics collection  
**So that** I can monitor system health

## Context

Prometheus is the de-facto standard for metrics collection in Kubernetes environments. Combined with the OTEL Collector's Prometheus exporter, we get unified metrics from all services. This story focuses on deploying Prometheus with proper service discovery, configuring scrape jobs, and setting up recording rules for efficient aggregation.

Metrics will be used for:
- Real-time dashboards (US-6.4)
- Alerting rules (US-6.8)
- SLA/SLO tracking
- Capacity planning

## Technical Requirements

### Directory Structure

```
observability/
├── prometheus/
│   ├── prometheus.yaml                # Main Prometheus config
│   ├── recording-rules.yaml          # Recording rules for aggregations
│   ├── alerting-rules.yaml           # Alerting rules (US-6.8)
│   └── service-monitors/
│       ├── ingestion-service.yaml
│       ├── retrieval-service.yaml
│       ├── orchestrator-service.yaml
│       └── llm-service.yaml
├── metrics/
│   ├── __init__.py
│   ├── registry.py                   # Prometheus registry setup
│   ├── collectors.py                 # Custom collectors
│   ├── middleware.py                 # FastAPI metrics middleware
│   └── exporters.py                  # /metrics endpoint
└── k8s/
    ├── prometheus-operator.yaml
    ├── prometheus-instance.yaml
    └── service-monitors.yaml
```

### Prometheus Server Configuration

```yaml
# prometheus.yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: rag-pipeline
    environment: ${ENVIRONMENT}

# Alertmanager configuration
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093
      scheme: http
      timeout: 10s
      api_version: v2

# Rule files
rule_files:
  - /etc/prometheus/recording-rules.yaml
  - /etc/prometheus/alerting-rules.yaml

# Scrape configurations
scrape_configs:
  # Prometheus self-monitoring
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
  
  # OTEL Collector metrics
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: otel-collector
  
  # Kubernetes service discovery for pods
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - rag-pipeline
    relabel_configs:
      # Only scrape pods with prometheus.io/scrape annotation
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      # Use custom port if specified
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}
      # Use custom path if specified
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      # Add pod labels
      - action: labelmap
        regex: __meta_kubernetes_pod_label_(.+)
      # Add namespace label
      - source_labels: [__meta_kubernetes_namespace]
        action: replace
        target_label: namespace
      # Add pod name label
      - source_labels: [__meta_kubernetes_pod_name]
        action: replace
        target_label: pod
      # Add service name from app label
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: replace
        target_label: service
  
  # Kubernetes service endpoints
  - job_name: 'kubernetes-service-endpoints'
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names:
            - rag-pipeline
            - observability
    relabel_configs:
      - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_scheme]
        action: replace
        target_label: __scheme__
        regex: (https?)
      - source_labels: [__meta_kubernetes_service_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_service_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
      - action: labelmap
        regex: __meta_kubernetes_service_label_(.+)
      - source_labels: [__meta_kubernetes_namespace]
        action: replace
        target_label: namespace
      - source_labels: [__meta_kubernetes_service_name]
        action: replace
        target_label: service

# Remote write for long-term storage (optional)
remote_write:
  - url: http://mimir:9009/api/v1/push
    queue_config:
      max_samples_per_send: 1000
      max_shards: 10
      capacity: 2500
```

### Recording Rules

```yaml
# recording-rules.yaml
groups:
  - name: rag_request_rates
    interval: 30s
    rules:
      # Request rate by service
      - record: rag:request_rate:5m
        expr: sum(rate(rag_query_total[5m])) by (service)
      
      # Error rate by service
      - record: rag:error_rate:5m
        expr: |
          sum(rate(rag_query_total{status="error"}[5m])) by (service)
          / sum(rate(rag_query_total[5m])) by (service)
      
      # Request latency percentiles
      - record: rag:latency_p50:5m
        expr: histogram_quantile(0.50, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, service))
      
      - record: rag:latency_p95:5m
        expr: histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, service))
      
      - record: rag:latency_p99:5m
        expr: histogram_quantile(0.99, sum(rate(rag_query_duration_seconds_bucket[5m])) by (le, service))

  - name: rag_retrieval_metrics
    interval: 30s
    rules:
      # Retrieval latency percentiles
      - record: rag:retrieval_latency_p50:5m
        expr: histogram_quantile(0.50, sum(rate(rag_retrieval_duration_seconds_bucket[5m])) by (le, strategy))
      
      - record: rag:retrieval_latency_p95:5m
        expr: histogram_quantile(0.95, sum(rate(rag_retrieval_duration_seconds_bucket[5m])) by (le, strategy))
      
      # Average results per query
      - record: rag:avg_results_per_query:5m
        expr: |
          sum(rate(rag_retrieval_result_count_sum[5m])) by (strategy)
          / sum(rate(rag_retrieval_result_count_count[5m])) by (strategy)
      
      # Cache hit ratio
      - record: rag:cache_hit_ratio:5m
        expr: |
          sum(rate(rag_cache_hits_total[5m])) by (cache_type)
          / (sum(rate(rag_cache_hits_total[5m])) by (cache_type)
             + sum(rate(rag_cache_misses_total[5m])) by (cache_type))

  - name: rag_llm_metrics
    interval: 30s
    rules:
      # Token throughput
      - record: rag:llm_tokens_per_second:5m
        expr: sum(rate(rag_llm_tokens_total[5m])) by (model, token_type)
      
      # LLM latency percentiles
      - record: rag:llm_latency_p50:5m
        expr: histogram_quantile(0.50, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le, model))
      
      - record: rag:llm_latency_p95:5m
        expr: histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le, model))
      
      # Time to first token
      - record: rag:llm_ttft_p50:5m
        expr: histogram_quantile(0.50, sum(rate(rag_llm_time_to_first_token_seconds_bucket[5m])) by (le, model))
      
      # Cost estimation (tokens * cost per token)
      - record: rag:estimated_cost_per_hour:1h
        expr: |
          sum(increase(rag_llm_tokens_total{token_type="input"}[1h])) * 0.00001
          + sum(increase(rag_llm_tokens_total{token_type="output"}[1h])) * 0.00003

  - name: rag_ingestion_metrics
    interval: 30s
    rules:
      # Ingestion rate
      - record: rag:ingestion_rate:5m
        expr: sum(rate(rag_documents_ingested_total[5m])) by (source_type)
      
      # Average document size
      - record: rag:avg_document_size:5m
        expr: |
          sum(rate(rag_document_bytes_total[5m])) by (source_type)
          / sum(rate(rag_documents_ingested_total[5m])) by (source_type)
      
      # Queue depth (if using message queues)
      - record: rag:ingestion_queue_depth:1m
        expr: sum(rag_ingestion_queue_size) by (queue)

  - name: rag_slos
    interval: 1m
    rules:
      # SLO: 99% of queries < 2s
      - record: rag:slo_query_latency:30d
        expr: |
          sum(rate(rag_query_duration_seconds_bucket{le="2"}[30d]))
          / sum(rate(rag_query_duration_seconds_count[30d]))
      
      # SLO: 99.9% availability
      - record: rag:slo_availability:30d
        expr: |
          1 - (sum(increase(rag_query_total{status="error"}[30d]))
               / sum(increase(rag_query_total[30d])))
      
      # Error budget remaining
      - record: rag:error_budget_remaining:30d
        expr: |
          1 - (
            (1 - rag:slo_availability:30d)
            / (1 - 0.999)
          )
```

### Python Metrics Registry

```python
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Summary,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    multiprocess,
    REGISTRY,
)
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily
from typing import Optional, List
from pydantic import BaseModel
import os


class MetricsConfig(BaseModel):
    """Configuration for Prometheus metrics."""
    # Namespace for all metrics
    namespace: str = "rag"
    
    # Subsystem (service name)
    subsystem: str = ""
    
    # Enable multiprocess mode for gunicorn
    multiprocess_mode: bool = False
    multiprocess_dir: Optional[str] = None
    
    # Default buckets for histograms
    latency_buckets: tuple = (
        0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5,
        0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf")
    )
    
    # Token count buckets
    token_buckets: tuple = (
        10, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, float("inf")
    )
    
    # Result count buckets
    result_buckets: tuple = (
        0, 1, 2, 3, 5, 10, 15, 20, 50, 100, float("inf")
    )


class RAGMetrics:
    """
    Prometheus metrics for the RAG pipeline.
    
    Provides standardized metrics across all services:
    - Query/request metrics
    - Latency histograms
    - Error counters
    - Token usage
    - Cache statistics
    """
    
    def __init__(self, config: MetricsConfig = MetricsConfig()):
        self.config = config
        self._registry = REGISTRY
        
        # Set up multiprocess mode if needed
        if config.multiprocess_mode:
            self._setup_multiprocess()
        
        # Initialize metrics
        self._init_query_metrics()
        self._init_retrieval_metrics()
        self._init_embedding_metrics()
        self._init_llm_metrics()
        self._init_ingestion_metrics()
        self._init_cache_metrics()
        self._init_system_metrics()
    
    def _setup_multiprocess(self) -> None:
        """Configure multiprocess mode for gunicorn workers."""
        if self.config.multiprocess_dir:
            os.environ['prometheus_multiproc_dir'] = self.config.multiprocess_dir
    
    def _init_query_metrics(self) -> None:
        """Initialize query/request metrics."""
        labels = ["service", "endpoint", "method", "status"]
        
        # Total queries counter
        self.query_total = Counter(
            "query_total",
            "Total number of queries",
            labels,
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Query duration histogram
        self.query_duration = Histogram(
            "query_duration_seconds",
            "Query duration in seconds",
            labels,
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.latency_buckets,
        )
        
        # Active queries gauge
        self.active_queries = Gauge(
            "active_queries",
            "Number of currently active queries",
            ["service"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
    
    def _init_retrieval_metrics(self) -> None:
        """Initialize retrieval-specific metrics."""
        # Retrieval duration by strategy
        self.retrieval_duration = Histogram(
            "retrieval_duration_seconds",
            "Retrieval duration in seconds",
            ["strategy", "index"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.latency_buckets,
        )
        
        # Number of results returned
        self.retrieval_result_count = Histogram(
            "retrieval_result_count",
            "Number of documents returned per query",
            ["strategy"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.result_buckets,
        )
        
        # Retrieval score distribution
        self.retrieval_score = Summary(
            "retrieval_score",
            "Score distribution of retrieved documents",
            ["strategy"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Reranking metrics
        self.reranking_duration = Histogram(
            "reranking_duration_seconds",
            "Reranking duration in seconds",
            ["model"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.latency_buckets,
        )
    
    def _init_embedding_metrics(self) -> None:
        """Initialize embedding generation metrics."""
        # Embedding generation duration
        self.embedding_duration = Histogram(
            "embedding_duration_seconds",
            "Embedding generation duration in seconds",
            ["model", "batch_size"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.latency_buckets,
        )
        
        # Embedding tokens processed
        self.embedding_tokens = Counter(
            "embedding_tokens_total",
            "Total tokens processed for embeddings",
            ["model"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Embedding requests
        self.embedding_requests = Counter(
            "embedding_requests_total",
            "Total embedding requests",
            ["model", "status"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
    
    def _init_llm_metrics(self) -> None:
        """Initialize LLM-specific metrics."""
        # LLM request duration
        self.llm_duration = Histogram(
            "llm_duration_seconds",
            "LLM inference duration in seconds",
            ["model", "provider"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")),
        )
        
        # Time to first token
        self.llm_ttft = Histogram(
            "llm_time_to_first_token_seconds",
            "Time to first token in seconds",
            ["model", "provider"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, float("inf")),
        )
        
        # Token usage
        self.llm_tokens = Counter(
            "llm_tokens_total",
            "Total LLM tokens used",
            ["model", "provider", "token_type"],  # token_type: input/output
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # LLM requests
        self.llm_requests = Counter(
            "llm_requests_total",
            "Total LLM requests",
            ["model", "provider", "status"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Token histogram for request size analysis
        self.llm_prompt_tokens = Histogram(
            "llm_prompt_tokens",
            "Prompt token count distribution",
            ["model"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.token_buckets,
        )
        
        self.llm_completion_tokens = Histogram(
            "llm_completion_tokens",
            "Completion token count distribution",
            ["model"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=self.config.token_buckets,
        )
    
    def _init_ingestion_metrics(self) -> None:
        """Initialize document ingestion metrics."""
        # Documents ingested
        self.documents_ingested = Counter(
            "documents_ingested_total",
            "Total documents ingested",
            ["source_type", "status"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Bytes processed
        self.document_bytes = Counter(
            "document_bytes_total",
            "Total bytes processed during ingestion",
            ["source_type"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Chunks created
        self.chunks_created = Counter(
            "chunks_created_total",
            "Total chunks created",
            ["chunking_strategy"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Ingestion duration
        self.ingestion_duration = Histogram(
            "ingestion_duration_seconds",
            "Document ingestion duration in seconds",
            ["source_type"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
        )
        
        # Queue metrics
        self.ingestion_queue_size = Gauge(
            "ingestion_queue_size",
            "Current ingestion queue depth",
            ["queue"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
    
    def _init_cache_metrics(self) -> None:
        """Initialize cache metrics."""
        # Cache hits/misses
        self.cache_hits = Counter(
            "cache_hits_total",
            "Total cache hits",
            ["cache_type", "key_prefix"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        self.cache_misses = Counter(
            "cache_misses_total",
            "Total cache misses",
            ["cache_type", "key_prefix"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Cache size
        self.cache_size = Gauge(
            "cache_size_bytes",
            "Current cache size in bytes",
            ["cache_type"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Cache latency
        self.cache_latency = Histogram(
            "cache_latency_seconds",
            "Cache operation latency",
            ["cache_type", "operation"],  # operation: get/set/delete
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
            buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, float("inf")),
        )
    
    def _init_system_metrics(self) -> None:
        """Initialize system/resource metrics."""
        # Connection pool metrics
        self.db_connections_active = Gauge(
            "db_connections_active",
            "Active database connections",
            ["database"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        self.db_connections_idle = Gauge(
            "db_connections_idle",
            "Idle database connections",
            ["database"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        # Vector database metrics
        self.vector_db_collections = Gauge(
            "vector_db_collections",
            "Number of vector collections",
            ["database"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
        
        self.vector_db_points = Gauge(
            "vector_db_points",
            "Total points in vector database",
            ["database", "collection"],
            namespace=self.config.namespace,
            subsystem=self.config.subsystem,
        )
    
    def generate_metrics(self) -> bytes:
        """Generate Prometheus metrics output."""
        if self.config.multiprocess_mode:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return generate_latest(registry)
        return generate_latest(self._registry)
    
    def get_content_type(self) -> str:
        """Get the content type for metrics response."""
        return CONTENT_TYPE_LATEST


# Singleton metrics instance
_metrics: Optional[RAGMetrics] = None


def init_metrics(config: MetricsConfig = MetricsConfig()) -> RAGMetrics:
    """Initialize the global metrics instance."""
    global _metrics
    _metrics = RAGMetrics(config)
    return _metrics


def get_metrics() -> RAGMetrics:
    """Get the global metrics instance."""
    if _metrics is None:
        raise RuntimeError("Metrics not initialized. Call init_metrics() first.")
    return _metrics
```

### FastAPI Metrics Middleware

```python
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Match
from typing import Callable
import time


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect HTTP request metrics.
    
    Tracks:
    - Request count by endpoint, method, status
    - Request duration histogram
    - Active request count
    """
    
    def __init__(
        self,
        app: FastAPI,
        service_name: str,
        metrics: RAGMetrics,
        excluded_paths: list = None,
    ):
        super().__init__(app)
        self.service_name = service_name
        self.metrics = metrics
        self.excluded_paths = excluded_paths or ["/health", "/ready", "/metrics"]
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # Skip excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # Get matched route for consistent endpoint labeling
        endpoint = self._get_endpoint(request)
        method = request.method
        
        # Track active requests
        self.metrics.active_queries.labels(service=self.service_name).inc()
        
        start_time = time.perf_counter()
        status = "success"
        
        try:
            response = await call_next(request)
            
            if response.status_code >= 400:
                status = "error" if response.status_code >= 500 else "client_error"
            
            return response
        
        except Exception as e:
            status = "error"
            raise
        
        finally:
            duration = time.perf_counter() - start_time
            
            # Record metrics
            labels = {
                "service": self.service_name,
                "endpoint": endpoint,
                "method": method,
                "status": status,
            }
            
            self.metrics.query_total.labels(**labels).inc()
            self.metrics.query_duration.labels(**labels).observe(duration)
            self.metrics.active_queries.labels(service=self.service_name).dec()
    
    def _get_endpoint(self, request: Request) -> str:
        """Get the route pattern for the request."""
        # Try to get the matched route pattern
        for route in request.app.routes:
            match, scope = route.matches(request.scope)
            if match == Match.FULL:
                return route.path
        
        # Fallback to path
        return request.url.path


def add_metrics_endpoint(app: FastAPI, metrics: RAGMetrics) -> None:
    """
    Add /metrics endpoint to FastAPI application.
    
    Example:
        app = FastAPI()
        metrics = init_metrics()
        add_metrics_endpoint(app, metrics)
    """
    @app.get("/metrics", include_in_schema=False)
    async def get_metrics():
        return Response(
            content=metrics.generate_metrics(),
            media_type=metrics.get_content_type(),
        )


def setup_prometheus(
    app: FastAPI,
    service_name: str,
    config: MetricsConfig = MetricsConfig(),
) -> RAGMetrics:
    """
    Set up Prometheus metrics for FastAPI application.
    
    Args:
        app: FastAPI application
        service_name: Name of the service for labeling
        config: Metrics configuration
    
    Returns:
        Initialized RAGMetrics instance
    """
    metrics = init_metrics(config)
    
    # Add middleware
    app.add_middleware(
        PrometheusMiddleware,
        service_name=service_name,
        metrics=metrics,
    )
    
    # Add /metrics endpoint
    add_metrics_endpoint(app, metrics)
    
    return metrics
```

### Custom Collectors

```python
from prometheus_client.core import (
    GaugeMetricFamily,
    CounterMetricFamily,
    REGISTRY,
)
from typing import Iterator, Any
import asyncio


class VectorDatabaseCollector:
    """
    Custom collector for vector database metrics.
    
    Collects metrics directly from Qdrant/other vector DBs
    on each scrape.
    """
    
    def __init__(self, qdrant_client, collection_names: list = None):
        self.qdrant_client = qdrant_client
        self.collection_names = collection_names or []
    
    def describe(self):
        """Describe metrics for Prometheus."""
        return []
    
    def collect(self) -> Iterator[Any]:
        """Collect metrics from vector database."""
        # Collection count
        collections_metric = GaugeMetricFamily(
            "rag_vector_db_collections",
            "Number of vector collections",
            labels=["database"],
        )
        
        try:
            collections = self.qdrant_client.get_collections()
            collections_metric.add_metric(
                ["qdrant"],
                len(collections.collections),
            )
        except Exception:
            pass
        
        yield collections_metric
        
        # Points per collection
        points_metric = GaugeMetricFamily(
            "rag_vector_db_points",
            "Total points in collection",
            labels=["database", "collection"],
        )
        
        for collection_name in self.collection_names:
            try:
                info = self.qdrant_client.get_collection(collection_name)
                points_metric.add_metric(
                    ["qdrant", collection_name],
                    info.points_count,
                )
            except Exception:
                pass
        
        yield points_metric


class PostgreSQLCollector:
    """
    Custom collector for PostgreSQL connection pool metrics.
    """
    
    def __init__(self, pool):
        self.pool = pool
    
    def describe(self):
        return []
    
    def collect(self) -> Iterator[Any]:
        """Collect connection pool metrics."""
        active = GaugeMetricFamily(
            "rag_db_connections_active",
            "Active database connections",
            labels=["database"],
        )
        
        idle = GaugeMetricFamily(
            "rag_db_connections_idle",
            "Idle database connections",
            labels=["database"],
        )
        
        try:
            active.add_metric(["postgresql"], self.pool.size - self.pool.freesize)
            idle.add_metric(["postgresql"], self.pool.freesize)
        except Exception:
            pass
        
        yield active
        yield idle


def register_custom_collectors(
    qdrant_client=None,
    pg_pool=None,
    collections: list = None,
) -> None:
    """Register custom collectors with Prometheus."""
    if qdrant_client:
        REGISTRY.register(VectorDatabaseCollector(qdrant_client, collections))
    
    if pg_pool:
        REGISTRY.register(PostgreSQLCollector(pg_pool))
```

### Kubernetes Deployment

```yaml
# prometheus-operator.yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: rag-prometheus
  namespace: observability
spec:
  replicas: 2
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      team: rag-pipeline
  ruleSelector:
    matchLabels:
      team: rag-pipeline
  resources:
    requests:
      memory: 1Gi
      cpu: 500m
    limits:
      memory: 2Gi
      cpu: 1000m
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 50Gi
  retention: 30d
  retentionSize: 45GB
  enableAdminAPI: false
  alerting:
    alertmanagers:
      - namespace: observability
        name: alertmanager
        port: web
---
# ServiceMonitor for RAG services
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: rag-services
  namespace: observability
  labels:
    team: rag-pipeline
spec:
  selector:
    matchLabels:
      app.kubernetes.io/part-of: rag-pipeline
  namespaceSelector:
    matchNames:
      - rag-pipeline
  endpoints:
    - port: metrics
      interval: 15s
      path: /metrics
      scrapeTimeout: 10s
---
# PrometheusRule for recording rules
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: rag-recording-rules
  namespace: observability
  labels:
    team: rag-pipeline
spec:
  groups:
    - name: rag_request_rates
      interval: 30s
      rules:
        - record: rag:request_rate:5m
          expr: sum(rate(rag_query_total[5m])) by (service)
        - record: rag:error_rate:5m
          expr: |
            sum(rate(rag_query_total{status="error"}[5m])) by (service)
            / sum(rate(rag_query_total[5m])) by (service)
```

## Unit Tests

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


@pytest.fixture
def metrics_config():
    """Create test metrics configuration."""
    return MetricsConfig(
        namespace="test_rag",
        subsystem="test",
    )


@pytest.fixture
def rag_metrics(metrics_config):
    """Create RAGMetrics instance."""
    # Clear registry to avoid duplicate registration
    collectors = list(REGISTRY._names_to_collectors.values())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass
    
    return RAGMetrics(metrics_config)


def test_query_metrics_increment(rag_metrics):
    """Test query counter increments correctly."""
    labels = {
        "service": "test-service",
        "endpoint": "/query",
        "method": "POST",
        "status": "success",
    }
    
    rag_metrics.query_total.labels(**labels).inc()
    
    # Verify counter value
    value = rag_metrics.query_total.labels(**labels)._value.get()
    assert value == 1


def test_duration_histogram(rag_metrics):
    """Test duration histogram records correctly."""
    labels = {
        "service": "test-service",
        "endpoint": "/query",
        "method": "POST",
        "status": "success",
    }
    
    rag_metrics.query_duration.labels(**labels).observe(0.5)
    
    # Histogram should record the observation


def test_llm_token_counter(rag_metrics):
    """Test LLM token counter."""
    rag_metrics.llm_tokens.labels(
        model="gpt-4",
        provider="openai",
        token_type="input",
    ).inc(100)
    
    rag_metrics.llm_tokens.labels(
        model="gpt-4",
        provider="openai",
        token_type="output",
    ).inc(50)


def test_cache_metrics(rag_metrics):
    """Test cache hit/miss counters."""
    rag_metrics.cache_hits.labels(
        cache_type="embedding",
        key_prefix="query",
    ).inc()
    
    rag_metrics.cache_misses.labels(
        cache_type="embedding",
        key_prefix="query",
    ).inc(3)


def test_metrics_generation(rag_metrics):
    """Test metrics output generation."""
    output = rag_metrics.generate_metrics()
    
    assert isinstance(output, bytes)
    assert b"test_rag" in output


def test_metrics_endpoint():
    """Test /metrics endpoint returns Prometheus format."""
    app = FastAPI()
    config = MetricsConfig(namespace="test")
    metrics = setup_prometheus(app, "test-service", config)
    
    client = TestClient(app)
    response = client.get("/metrics")
    
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_middleware_records_metrics():
    """Test middleware records request metrics."""
    app = FastAPI()
    config = MetricsConfig(namespace="middleware_test")
    metrics = setup_prometheus(app, "test-service", config)
    
    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}
    
    client = TestClient(app)
    
    # Make request
    response = client.get("/test")
    assert response.status_code == 200
    
    # Check metrics were recorded
    metrics_output = client.get("/metrics")
    assert b"middleware_test_query_total" in metrics_output.content


def test_middleware_excludes_paths():
    """Test middleware excludes health endpoints."""
    app = FastAPI()
    config = MetricsConfig(namespace="exclude_test")
    metrics = setup_prometheus(app, "test-service", config)
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    client = TestClient(app)
    
    # Health endpoint should not be recorded
    client.get("/health")
    
    metrics_output = client.get("/metrics")
    assert b'endpoint="/health"' not in metrics_output.content


def test_retrieval_metrics(rag_metrics):
    """Test retrieval-specific metrics."""
    rag_metrics.retrieval_duration.labels(
        strategy="hybrid",
        index="documents",
    ).observe(0.15)
    
    rag_metrics.retrieval_result_count.labels(
        strategy="hybrid",
    ).observe(5)


def test_ingestion_metrics(rag_metrics):
    """Test ingestion metrics."""
    rag_metrics.documents_ingested.labels(
        source_type="pdf",
        status="success",
    ).inc()
    
    rag_metrics.document_bytes.labels(
        source_type="pdf",
    ).inc(1024 * 1024)  # 1 MB
    
    rag_metrics.chunks_created.labels(
        chunking_strategy="semantic",
    ).inc(10)


def test_embedding_metrics(rag_metrics):
    """Test embedding metrics."""
    rag_metrics.embedding_duration.labels(
        model="text-embedding-3-small",
        batch_size="32",
    ).observe(0.25)
    
    rag_metrics.embedding_tokens.labels(
        model="text-embedding-3-small",
    ).inc(512)
```

## Integration Tests

```python
@pytest.mark.integration
def test_prometheus_scrape():
    """Test Prometheus can scrape metrics endpoint."""
    import requests
    
    # Assuming service is running
    response = requests.get("http://localhost:8000/metrics")
    
    assert response.status_code == 200
    assert "rag_query_total" in response.text


@pytest.mark.integration
def test_custom_collector_qdrant():
    """Test Qdrant custom collector."""
    from qdrant_client import QdrantClient
    
    client = QdrantClient(host="localhost", port=6333)
    collector = VectorDatabaseCollector(client, ["documents"])
    
    # Collect metrics
    metrics = list(collector.collect())
    
    assert len(metrics) >= 2  # collections and points


@pytest.mark.integration
def test_recording_rules():
    """Test recording rules produce expected metrics."""
    import requests
    
    # Query Prometheus for recording rule results
    response = requests.get(
        "http://prometheus:9090/api/v1/query",
        params={"query": "rag:request_rate:5m"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
```

## Dependencies

```
prometheus-client>=0.19.0
fastapi>=0.104.0
starlette>=0.27.0
```

## Definition of Done

- [ ] MetricsConfig with customizable buckets and namespace
- [ ] RAGMetrics with all metric types (Counter, Histogram, Gauge, Summary)
- [ ] Query/request metrics (total, duration, active)
- [ ] Retrieval metrics (duration, result count, score)
- [ ] Embedding metrics (duration, tokens, requests)
- [ ] LLM metrics (duration, TTFT, tokens, requests)
- [ ] Ingestion metrics (documents, bytes, chunks, queue)
- [ ] Cache metrics (hits, misses, size, latency)
- [ ] System metrics (connections, vector DB stats)
- [ ] PrometheusMiddleware for FastAPI
- [ ] /metrics endpoint configured
- [ ] Custom collectors for Qdrant and PostgreSQL
- [ ] Prometheus server configuration with service discovery
- [ ] Recording rules for aggregations and SLOs
- [ ] Kubernetes manifests (Prometheus Operator, ServiceMonitor)
- [ ] Multiprocess mode support for gunicorn
- [ ] >90% test coverage
- [ ] Documentation complete
