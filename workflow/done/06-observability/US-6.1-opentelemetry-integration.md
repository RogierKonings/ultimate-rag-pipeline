# US-6.1: OpenTelemetry Integration

> **Story ID:** US-6.1  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Epic 1 (Infrastructure Setup)

## User Story

**As a** developer  
**I want** distributed tracing across services  
**So that** I can debug request flows and understand system behavior

## Context

Distributed tracing is essential for understanding request flows in a microservices architecture. OpenTelemetry (OTEL) provides vendor-neutral instrumentation for traces, metrics, and logs. For the RAG pipeline, tracing is critical to understand:

- End-to-end query latency breakdown
- Embedding generation time
- Vector search duration
- LLM inference time
- Inter-service communication patterns

The OTEL Collector acts as a central telemetry hub, receiving data from all services and exporting to backends (Jaeger/Tempo for traces, Prometheus for metrics, Loki for logs).

## Technical Requirements

### Directory Structure

```
observability/
├── otel/
│   ├── __init__.py
│   ├── tracer.py              # Tracer configuration
│   ├── context.py             # Context propagation utilities
│   ├── spans.py               # Span helpers and decorators
│   ├── attributes.py          # Semantic attributes for RAG
│   ├── exporters.py           # Exporter configuration
│   └── middleware/
│       ├── __init__.py
│       ├── fastapi.py         # FastAPI instrumentation
│       ├── grpc.py            # gRPC instrumentation
│       └── celery.py          # Celery task instrumentation
├── docker/
│   ├── otel-collector-config.yaml
│   └── jaeger-config.yaml
└── k8s/
    ├── otel-collector.yaml
    ├── jaeger.yaml
    └── tempo.yaml
```

### OTEL Collector Configuration

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  
  # Prometheus scraping for metrics
  prometheus:
    config:
      scrape_configs:
        - job_name: 'otel-collector'
          scrape_interval: 15s
          static_configs:
            - targets: ['localhost:8888']

processors:
  # Batch processing for efficiency
  batch:
    timeout: 5s
    send_batch_size: 1000
    send_batch_max_size: 1500
  
  # Memory limiter to prevent OOM
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
  
  # Add resource attributes
  resource:
    attributes:
      - key: deployment.environment
        value: ${ENVIRONMENT}
        action: upsert
      - key: service.namespace
        value: rag-pipeline
        action: upsert
  
  # Tail-based sampling for traces
  tail_sampling:
    decision_wait: 10s
    num_traces: 100
    policies:
      # Always sample errors
      - name: error-policy
        type: status_code
        status_code:
          status_codes: [ERROR]
      # Always sample slow traces (>5s)
      - name: latency-policy
        type: latency
        latency:
          threshold_ms: 5000
      # Sample 10% of successful traces
      - name: probabilistic-policy
        type: probabilistic
        probabilistic:
          sampling_percentage: 10
      # Always sample LLM calls
      - name: llm-policy
        type: string_attribute
        string_attribute:
          key: rag.operation
          values: [llm_inference, embedding_generation]

exporters:
  # Jaeger for traces (development)
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true
  
  # Tempo for traces (production)
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
  
  # Prometheus for metrics
  prometheus:
    endpoint: 0.0.0.0:8889
    namespace: rag
    send_timestamps: true
    metric_expiration: 5m
    resource_to_telemetry_conversion:
      enabled: true
  
  # Loki for logs
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
    labels:
      resource:
        service.name: "service_name"
        service.namespace: "service_namespace"
      attributes:
        level: ""
        rag.operation: ""

  # Debug exporter for development
  logging:
    loglevel: debug

extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  
  zpages:
    endpoint: 0.0.0.0:55679
  
  pprof:
    endpoint: 0.0.0.0:1777

service:
  extensions: [health_check, zpages, pprof]
  
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resource, tail_sampling, batch]
      exporters: [jaeger, otlp/tempo]
    
    metrics:
      receivers: [otlp, prometheus]
      processors: [memory_limiter, resource, batch]
      exporters: [prometheus]
    
    logs:
      receivers: [otlp]
      processors: [memory_limiter, resource, batch]
      exporters: [loki]
  
  telemetry:
    logs:
      level: info
    metrics:
      address: 0.0.0.0:8888
```

### Tracer Configuration

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.b3 import B3MultiFormat
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from pydantic import BaseModel
from typing import Optional
import os


class OTELConfig(BaseModel):
    """OpenTelemetry configuration."""
    # Service identification
    service_name: str
    service_version: str = "1.0.0"
    environment: str = "development"
    
    # OTEL Collector endpoint
    collector_endpoint: str = "http://otel-collector:4317"
    
    # Sampling
    sampling_ratio: float = 1.0  # 1.0 = 100% sampling
    
    # Exporter settings
    export_timeout_millis: int = 30000
    max_export_batch_size: int = 512
    max_queue_size: int = 2048
    
    # Feature flags
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_logs: bool = True
    
    # Auto-instrumentation
    instrument_fastapi: bool = True
    instrument_httpx: bool = True
    instrument_redis: bool = True
    instrument_sqlalchemy: bool = True
    
    @classmethod
    def from_env(cls, service_name: str) -> "OTELConfig":
        """Create config from environment variables."""
        return cls(
            service_name=service_name,
            service_version=os.getenv("SERVICE_VERSION", "1.0.0"),
            environment=os.getenv("ENVIRONMENT", "development"),
            collector_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://otel-collector:4317"
            ),
            sampling_ratio=float(os.getenv("OTEL_SAMPLING_RATIO", "1.0")),
        )


class OTELProvider:
    """
    OpenTelemetry provider for the RAG pipeline.
    
    Manages tracer provider, span processors, and exporters.
    Provides auto-instrumentation for common libraries.
    """
    
    def __init__(self, config: OTELConfig):
        self.config = config
        self._tracer_provider: Optional[TracerProvider] = None
        self._initialized = False
    
    def initialize(self) -> None:
        """
        Initialize OpenTelemetry.
        
        Sets up:
        1. Resource attributes (service name, version, environment)
        2. Tracer provider with sampling
        3. OTLP exporter to collector
        4. Context propagation (B3 for compatibility)
        5. Auto-instrumentation for libraries
        """
        if self._initialized:
            return
        
        # Create resource with service attributes
        resource = Resource.create({
            SERVICE_NAME: self.config.service_name,
            SERVICE_VERSION: self.config.service_version,
            "deployment.environment": self.config.environment,
            "service.namespace": "rag-pipeline",
        })
        
        # Create tracer provider
        self._tracer_provider = TracerProvider(
            resource=resource,
            sampler=self._create_sampler(),
        )
        
        # Add OTLP exporter
        if self.config.enable_traces:
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.config.collector_endpoint,
                timeout=self.config.export_timeout_millis,
            )
            
            span_processor = BatchSpanProcessor(
                otlp_exporter,
                max_export_batch_size=self.config.max_export_batch_size,
                max_queue_size=self.config.max_queue_size,
            )
            
            self._tracer_provider.add_span_processor(span_processor)
        
        # Set global tracer provider
        trace.set_tracer_provider(self._tracer_provider)
        
        # Set up context propagation (B3 for cross-service compatibility)
        set_global_textmap(B3MultiFormat())
        
        # Auto-instrument libraries
        self._instrument_libraries()
        
        self._initialized = True
    
    def _create_sampler(self):
        """Create sampler based on configuration."""
        from opentelemetry.sdk.trace.sampling import (
            TraceIdRatioBased,
            ParentBased,
        )
        
        # ParentBased respects parent decision, falls back to ratio-based
        root_sampler = TraceIdRatioBased(self.config.sampling_ratio)
        return ParentBased(root=root_sampler)
    
    def _instrument_libraries(self) -> None:
        """Auto-instrument common libraries."""
        if self.config.instrument_httpx:
            HTTPXClientInstrumentor().instrument()
        
        if self.config.instrument_redis:
            RedisInstrumentor().instrument()
    
    def instrument_fastapi(self, app) -> None:
        """Instrument FastAPI application."""
        if self.config.instrument_fastapi:
            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="health,ready,metrics",
            )
    
    def instrument_sqlalchemy(self, engine) -> None:
        """Instrument SQLAlchemy engine."""
        if self.config.instrument_sqlalchemy:
            SQLAlchemyInstrumentor().instrument(engine=engine)
    
    def get_tracer(self, name: str = None) -> trace.Tracer:
        """Get a tracer instance."""
        if not self._initialized:
            self.initialize()
        
        tracer_name = name or self.config.service_name
        return trace.get_tracer(tracer_name, self.config.service_version)
    
    def shutdown(self) -> None:
        """Gracefully shutdown the tracer provider."""
        if self._tracer_provider:
            self._tracer_provider.shutdown()


# Global provider instance
_provider: Optional[OTELProvider] = None


def init_otel(config: OTELConfig) -> OTELProvider:
    """Initialize OpenTelemetry with the given configuration."""
    global _provider
    _provider = OTELProvider(config)
    _provider.initialize()
    return _provider


def get_tracer(name: str = None) -> trace.Tracer:
    """Get the global tracer."""
    if _provider is None:
        raise RuntimeError("OpenTelemetry not initialized. Call init_otel() first.")
    return _provider.get_tracer(name)
```

### RAG-Specific Semantic Attributes

```python
from opentelemetry.trace import Span
from typing import Optional, List, Any
from enum import Enum


class RAGOperation(str, Enum):
    """Standard RAG operation types for tracing."""
    QUERY = "query"
    EMBEDDING_GENERATION = "embedding_generation"
    VECTOR_SEARCH = "vector_search"
    HYBRID_SEARCH = "hybrid_search"
    RERANKING = "reranking"
    LLM_INFERENCE = "llm_inference"
    DOCUMENT_INGESTION = "document_ingestion"
    CHUNKING = "chunking"
    CACHE_LOOKUP = "cache_lookup"


class RAGAttributes:
    """
    Semantic attributes for RAG operations.
    
    Follows OpenTelemetry semantic conventions pattern
    with RAG-specific extensions.
    """
    # Operation identification
    OPERATION = "rag.operation"
    QUERY_ID = "rag.query.id"
    
    # Query attributes
    QUERY_TEXT = "rag.query.text"
    QUERY_TOKENS = "rag.query.tokens"
    
    # Embedding attributes
    EMBEDDING_MODEL = "rag.embedding.model"
    EMBEDDING_DIMENSIONS = "rag.embedding.dimensions"
    EMBEDDING_TOKENS = "rag.embedding.tokens"
    
    # Retrieval attributes
    RETRIEVAL_STRATEGY = "rag.retrieval.strategy"
    RETRIEVAL_TOP_K = "rag.retrieval.top_k"
    RETRIEVAL_RESULTS_COUNT = "rag.retrieval.results_count"
    RETRIEVAL_MIN_SCORE = "rag.retrieval.min_score"
    RETRIEVAL_MAX_SCORE = "rag.retrieval.max_score"
    
    # Reranking attributes
    RERANKER_MODEL = "rag.reranker.model"
    RERANKER_INPUT_COUNT = "rag.reranker.input_count"
    RERANKER_OUTPUT_COUNT = "rag.reranker.output_count"
    
    # LLM attributes
    LLM_MODEL = "rag.llm.model"
    LLM_PROVIDER = "rag.llm.provider"
    LLM_PROMPT_TOKENS = "rag.llm.prompt_tokens"
    LLM_COMPLETION_TOKENS = "rag.llm.completion_tokens"
    LLM_TOTAL_TOKENS = "rag.llm.total_tokens"
    LLM_TEMPERATURE = "rag.llm.temperature"
    LLM_MAX_TOKENS = "rag.llm.max_tokens"
    LLM_STOP_REASON = "rag.llm.stop_reason"
    
    # Document attributes
    DOCUMENT_ID = "rag.document.id"
    DOCUMENT_SOURCE = "rag.document.source"
    DOCUMENT_TYPE = "rag.document.type"
    DOCUMENT_SIZE_BYTES = "rag.document.size_bytes"
    
    # Chunk attributes
    CHUNK_COUNT = "rag.chunk.count"
    CHUNK_STRATEGY = "rag.chunk.strategy"
    CHUNK_SIZE = "rag.chunk.size"
    CHUNK_OVERLAP = "rag.chunk.overlap"
    
    # Cache attributes
    CACHE_HIT = "rag.cache.hit"
    CACHE_KEY = "rag.cache.key"
    CACHE_TTL = "rag.cache.ttl"
    
    # Tenant/user context
    TENANT_ID = "rag.tenant.id"
    USER_ID = "rag.user.id"


def set_rag_attributes(
    span: Span,
    operation: RAGOperation,
    **kwargs
) -> None:
    """
    Set RAG-specific attributes on a span.
    
    Args:
        span: The span to set attributes on
        operation: The RAG operation type
        **kwargs: Additional attributes to set
    
    Example:
        set_rag_attributes(
            span,
            RAGOperation.VECTOR_SEARCH,
            query_id="q-123",
            top_k=10,
            results_count=8,
        )
    """
    span.set_attribute(RAGAttributes.OPERATION, operation.value)
    
    # Map common kwargs to attributes
    attr_mapping = {
        "query_id": RAGAttributes.QUERY_ID,
        "query_text": RAGAttributes.QUERY_TEXT,
        "query_tokens": RAGAttributes.QUERY_TOKENS,
        "embedding_model": RAGAttributes.EMBEDDING_MODEL,
        "embedding_dimensions": RAGAttributes.EMBEDDING_DIMENSIONS,
        "embedding_tokens": RAGAttributes.EMBEDDING_TOKENS,
        "retrieval_strategy": RAGAttributes.RETRIEVAL_STRATEGY,
        "top_k": RAGAttributes.RETRIEVAL_TOP_K,
        "results_count": RAGAttributes.RETRIEVAL_RESULTS_COUNT,
        "min_score": RAGAttributes.RETRIEVAL_MIN_SCORE,
        "max_score": RAGAttributes.RETRIEVAL_MAX_SCORE,
        "reranker_model": RAGAttributes.RERANKER_MODEL,
        "llm_model": RAGAttributes.LLM_MODEL,
        "llm_provider": RAGAttributes.LLM_PROVIDER,
        "prompt_tokens": RAGAttributes.LLM_PROMPT_TOKENS,
        "completion_tokens": RAGAttributes.LLM_COMPLETION_TOKENS,
        "total_tokens": RAGAttributes.LLM_TOTAL_TOKENS,
        "temperature": RAGAttributes.LLM_TEMPERATURE,
        "max_tokens": RAGAttributes.LLM_MAX_TOKENS,
        "stop_reason": RAGAttributes.LLM_STOP_REASON,
        "document_id": RAGAttributes.DOCUMENT_ID,
        "document_source": RAGAttributes.DOCUMENT_SOURCE,
        "document_type": RAGAttributes.DOCUMENT_TYPE,
        "document_size_bytes": RAGAttributes.DOCUMENT_SIZE_BYTES,
        "chunk_count": RAGAttributes.CHUNK_COUNT,
        "chunk_strategy": RAGAttributes.CHUNK_STRATEGY,
        "chunk_size": RAGAttributes.CHUNK_SIZE,
        "chunk_overlap": RAGAttributes.CHUNK_OVERLAP,
        "cache_hit": RAGAttributes.CACHE_HIT,
        "cache_key": RAGAttributes.CACHE_KEY,
        "cache_ttl": RAGAttributes.CACHE_TTL,
        "tenant_id": RAGAttributes.TENANT_ID,
        "user_id": RAGAttributes.USER_ID,
    }
    
    for key, value in kwargs.items():
        if key in attr_mapping and value is not None:
            span.set_attribute(attr_mapping[key], value)


def set_retrieval_results(
    span: Span,
    results: List[Any],
    score_field: str = "score"
) -> None:
    """Set retrieval result attributes on a span."""
    span.set_attribute(RAGAttributes.RETRIEVAL_RESULTS_COUNT, len(results))
    
    if results:
        scores = [getattr(r, score_field, r.get(score_field, 0)) for r in results]
        span.set_attribute(RAGAttributes.RETRIEVAL_MIN_SCORE, min(scores))
        span.set_attribute(RAGAttributes.RETRIEVAL_MAX_SCORE, max(scores))


def set_llm_usage(
    span: Span,
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    provider: str = "unknown",
    stop_reason: Optional[str] = None
) -> None:
    """Set LLM usage attributes on a span."""
    span.set_attribute(RAGAttributes.LLM_MODEL, model)
    span.set_attribute(RAGAttributes.LLM_PROVIDER, provider)
    span.set_attribute(RAGAttributes.LLM_PROMPT_TOKENS, prompt_tokens)
    span.set_attribute(RAGAttributes.LLM_COMPLETION_TOKENS, completion_tokens)
    span.set_attribute(RAGAttributes.LLM_TOTAL_TOKENS, prompt_tokens + completion_tokens)
    
    if stop_reason:
        span.set_attribute(RAGAttributes.LLM_STOP_REASON, stop_reason)
```

### Span Decorators and Context Managers

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, Span
from functools import wraps
from typing import Callable, Optional, Any
from contextlib import contextmanager
import asyncio


def traced(
    name: Optional[str] = None,
    operation: Optional[RAGOperation] = None,
    attributes: Optional[dict] = None,
    record_exception: bool = True,
) -> Callable:
    """
    Decorator to trace a function.
    
    Args:
        name: Span name (defaults to function name)
        operation: RAG operation type
        attributes: Static attributes to set
        record_exception: Whether to record exceptions
    
    Example:
        @traced(operation=RAGOperation.VECTOR_SEARCH)
        async def search_vectors(query: str, top_k: int):
            ...
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__
        
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)
                
                with tracer.start_as_current_span(span_name) as span:
                    if operation:
                        span.set_attribute(RAGAttributes.OPERATION, operation.value)
                    
                    if attributes:
                        for key, value in attributes.items():
                            span.set_attribute(key, value)
                    
                    try:
                        result = await func(*args, **kwargs)
                        span.set_status(Status(StatusCode.OK))
                        return result
                    except Exception as e:
                        if record_exception:
                            span.record_exception(e)
                            span.set_status(
                                Status(StatusCode.ERROR, str(e))
                            )
                        raise
            
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                tracer = trace.get_tracer(__name__)
                
                with tracer.start_as_current_span(span_name) as span:
                    if operation:
                        span.set_attribute(RAGAttributes.OPERATION, operation.value)
                    
                    if attributes:
                        for key, value in attributes.items():
                            span.set_attribute(key, value)
                    
                    try:
                        result = func(*args, **kwargs)
                        span.set_status(Status(StatusCode.OK))
                        return result
                    except Exception as e:
                        if record_exception:
                            span.record_exception(e)
                            span.set_status(
                                Status(StatusCode.ERROR, str(e))
                            )
                        raise
            
            return sync_wrapper
    
    return decorator


@contextmanager
def rag_span(
    name: str,
    operation: RAGOperation,
    **attributes
):
    """
    Context manager for RAG operation spans.
    
    Example:
        with rag_span("search", RAGOperation.VECTOR_SEARCH, top_k=10) as span:
            results = search(query)
            span.set_attribute("results_count", len(results))
    """
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span(name) as span:
        set_rag_attributes(span, operation, **attributes)
        
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


def get_current_span() -> Span:
    """Get the current active span."""
    return trace.get_current_span()


def add_span_event(name: str, attributes: Optional[dict] = None) -> None:
    """Add an event to the current span."""
    span = get_current_span()
    span.add_event(name, attributes=attributes or {})


def set_span_error(error: Exception, message: Optional[str] = None) -> None:
    """Mark the current span as error."""
    span = get_current_span()
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, message or str(error)))
```

### Context Propagation

```python
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from typing import Dict, Any, Optional
from starlette.requests import Request


class TraceContextPropagator:
    """
    Utilities for propagating trace context across services.
    
    Supports:
    - HTTP headers (W3C Trace Context, B3)
    - Message queue headers (Kafka, RabbitMQ)
    - gRPC metadata
    """
    
    def __init__(self):
        self.propagator = TraceContextTextMapPropagator()
    
    def extract_from_headers(
        self,
        headers: Dict[str, str]
    ) -> trace.Context:
        """
        Extract trace context from HTTP headers.
        
        Args:
            headers: HTTP request headers
        
        Returns:
            OpenTelemetry context
        """
        return extract(headers)
    
    def inject_to_headers(
        self,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        Inject current trace context into headers.
        
        Args:
            headers: Existing headers to add to (optional)
        
        Returns:
            Headers with trace context
        """
        headers = headers or {}
        inject(headers)
        return headers
    
    def extract_from_request(self, request: Request) -> trace.Context:
        """Extract trace context from a FastAPI/Starlette request."""
        return self.extract_from_headers(dict(request.headers))
    
    def inject_to_kafka(self, headers: Optional[list] = None) -> list:
        """
        Inject trace context into Kafka message headers.
        
        Kafka expects headers as list of tuples.
        """
        http_headers = self.inject_to_headers()
        kafka_headers = headers or []
        
        for key, value in http_headers.items():
            kafka_headers.append((key, value.encode('utf-8')))
        
        return kafka_headers
    
    def extract_from_kafka(self, headers: list) -> trace.Context:
        """Extract trace context from Kafka message headers."""
        http_headers = {}
        
        for key, value in headers or []:
            if isinstance(value, bytes):
                http_headers[key] = value.decode('utf-8')
            else:
                http_headers[key] = value
        
        return self.extract_from_headers(http_headers)
    
    def get_trace_id(self) -> Optional[str]:
        """Get current trace ID as hex string."""
        span = trace.get_current_span()
        ctx = span.get_span_context()
        
        if ctx.is_valid:
            return format(ctx.trace_id, '032x')
        return None
    
    def get_span_id(self) -> Optional[str]:
        """Get current span ID as hex string."""
        span = trace.get_current_span()
        ctx = span.get_span_context()
        
        if ctx.is_valid:
            return format(ctx.span_id, '016x')
        return None


# FastAPI dependency for trace context
async def get_trace_context(request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency to extract and return trace context.
    
    Example:
        @app.get("/query")
        async def query(trace_ctx: dict = Depends(get_trace_context)):
            logger.info("Query", extra={"trace_id": trace_ctx["trace_id"]})
    """
    propagator = TraceContextPropagator()
    
    return {
        "trace_id": propagator.get_trace_id(),
        "span_id": propagator.get_span_id(),
    }
```

### FastAPI Middleware Integration

```python
from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Status, StatusCode, SpanKind
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from typing import Callable, Optional
import time


class OTELMiddleware(BaseHTTPMiddleware):
    """
    OpenTelemetry middleware for FastAPI.
    
    Creates spans for incoming requests with:
    - HTTP method and route
    - Request/response attributes
    - Error recording
    - Duration tracking
    
    Note: Use this in addition to FastAPIInstrumentor for
    custom attribute handling.
    """
    
    def __init__(
        self,
        app: FastAPI,
        service_name: str,
        excluded_paths: Optional[list] = None,
    ):
        super().__init__(app)
        self.service_name = service_name
        self.excluded_paths = excluded_paths or [
            "/health",
            "/ready",
            "/metrics",
        ]
        self.tracer = trace.get_tracer(service_name)
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable
    ) -> Response:
        # Skip excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # Extract trace context from incoming request
        ctx = extract(dict(request.headers))
        
        # Create span name from method and route
        route = request.scope.get("route")
        route_path = route.path if route else request.url.path
        span_name = f"{request.method} {route_path}"
        
        with self.tracer.start_as_current_span(
            span_name,
            context=ctx,
            kind=SpanKind.SERVER,
        ) as span:
            # Set request attributes
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", route_path)
            span.set_attribute("http.scheme", request.url.scheme)
            span.set_attribute("http.host", request.url.hostname or "")
            span.set_attribute("http.user_agent", request.headers.get("user-agent", ""))
            span.set_attribute("http.client_ip", request.client.host if request.client else "")
            
            # Extract tenant/user from headers if available
            if "x-tenant-id" in request.headers:
                span.set_attribute(RAGAttributes.TENANT_ID, request.headers["x-tenant-id"])
            if "x-user-id" in request.headers:
                span.set_attribute(RAGAttributes.USER_ID, request.headers["x-user-id"])
            
            # Track timing
            start_time = time.perf_counter()
            
            try:
                response = await call_next(request)
                
                # Set response attributes
                span.set_attribute("http.status_code", response.status_code)
                
                if response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR))
                else:
                    span.set_status(Status(StatusCode.OK))
                
                return response
                
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            
            finally:
                duration = time.perf_counter() - start_time
                span.set_attribute("http.duration_ms", duration * 1000)


def setup_otel_fastapi(
    app: FastAPI,
    config: OTELConfig,
) -> OTELProvider:
    """
    Set up OpenTelemetry for a FastAPI application.
    
    Args:
        app: FastAPI application instance
        config: OTEL configuration
    
    Returns:
        Initialized OTEL provider
    
    Example:
        app = FastAPI()
        otel = setup_otel_fastapi(app, OTELConfig.from_env("retrieval-service"))
    """
    provider = init_otel(config)
    
    # Add custom middleware
    app.add_middleware(
        OTELMiddleware,
        service_name=config.service_name,
    )
    
    # Auto-instrument FastAPI
    provider.instrument_fastapi(app)
    
    # Add shutdown hook
    @app.on_event("shutdown")
    async def shutdown_otel():
        provider.shutdown()
    
    return provider
```

### Kubernetes Deployment

```yaml
# otel-collector.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: observability
  labels:
    app: otel-collector
spec:
  replicas: 2
  selector:
    matchLabels:
      app: otel-collector
  template:
    metadata:
      labels:
        app: otel-collector
    spec:
      containers:
        - name: otel-collector
          image: otel/opentelemetry-collector-contrib:0.91.0
          args:
            - "--config=/conf/otel-collector-config.yaml"
          ports:
            - containerPort: 4317  # OTLP gRPC
              name: otlp-grpc
            - containerPort: 4318  # OTLP HTTP
              name: otlp-http
            - containerPort: 8888  # Metrics
              name: metrics
            - containerPort: 8889  # Prometheus exporter
              name: prometheus
            - containerPort: 13133  # Health check
              name: health
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 512Mi
              cpu: 500m
          livenessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: 13133
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /conf
          env:
            - name: ENVIRONMENT
              valueFrom:
                configMapKeyRef:
                  name: rag-config
                  key: environment
      volumes:
        - name: config
          configMap:
            name: otel-collector-config
---
apiVersion: v1
kind: Service
metadata:
  name: otel-collector
  namespace: observability
spec:
  selector:
    app: otel-collector
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
    - name: otlp-http
      port: 4318
      targetPort: 4318
    - name: metrics
      port: 8888
      targetPort: 8888
    - name: prometheus
      port: 8889
      targetPort: 8889
  type: ClusterIP
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: observability
data:
  otel-collector-config.yaml: |
    # Contents from otel-collector-config.yaml above
```

```yaml
# jaeger.yaml (development)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: observability
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
    spec:
      containers:
        - name: jaeger
          image: jaegertracing/all-in-one:1.52
          ports:
            - containerPort: 16686  # UI
              name: ui
            - containerPort: 14250  # gRPC
              name: grpc
            - containerPort: 14268  # HTTP
              name: http
          env:
            - name: COLLECTOR_OTLP_ENABLED
              value: "true"
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 512Mi
              cpu: 500m
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger
  namespace: observability
spec:
  selector:
    app: jaeger
  ports:
    - name: ui
      port: 16686
      targetPort: 16686
    - name: grpc
      port: 14250
      targetPort: 14250
    - name: http
      port: 14268
      targetPort: 14268
  type: ClusterIP
```

## Unit Tests

```python
import pytest
from uuid import uuid4
from unittest.mock import Mock, patch, MagicMock
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def in_memory_exporter():
    """Create in-memory span exporter for testing."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        trace.get_tracer_provider().get_tracer(__name__)
    )
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def otel_config():
    """Create test OTEL configuration."""
    return OTELConfig(
        service_name="test-service",
        service_version="1.0.0",
        environment="test",
        collector_endpoint="http://localhost:4317",
        sampling_ratio=1.0,
    )


def test_otel_config_from_env(monkeypatch):
    """Test configuration from environment."""
    monkeypatch.setenv("SERVICE_VERSION", "2.0.0")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    
    config = OTELConfig.from_env("my-service")
    
    assert config.service_name == "my-service"
    assert config.service_version == "2.0.0"
    assert config.environment == "staging"
    assert config.collector_endpoint == "http://collector:4317"


def test_otel_provider_initialization(otel_config):
    """Test OTEL provider initializes correctly."""
    provider = OTELProvider(otel_config)
    provider.initialize()
    
    assert provider._initialized is True
    assert provider._tracer_provider is not None


def test_get_tracer(otel_config):
    """Test getting a tracer instance."""
    provider = OTELProvider(otel_config)
    provider.initialize()
    
    tracer = provider.get_tracer()
    
    assert tracer is not None


def test_rag_attributes_set_correctly():
    """Test RAG attributes are set on spans."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("test") as span:
        set_rag_attributes(
            span,
            RAGOperation.VECTOR_SEARCH,
            query_id="q-123",
            top_k=10,
            results_count=8,
            tenant_id="tenant-abc",
        )
        
        # Span attributes are set
        # In real tests, use InMemorySpanExporter to verify


def test_traced_decorator():
    """Test traced decorator creates spans."""
    @traced(operation=RAGOperation.EMBEDDING_GENERATION)
    def generate_embedding(text: str):
        return [0.1, 0.2, 0.3]
    
    result = generate_embedding("test")
    
    assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_traced_decorator_async():
    """Test traced decorator works with async functions."""
    @traced(operation=RAGOperation.VECTOR_SEARCH)
    async def async_search(query: str):
        return {"results": []}
    
    result = await async_search("test query")
    
    assert result == {"results": []}


def test_traced_decorator_records_exception():
    """Test traced decorator records exceptions."""
    @traced(operation=RAGOperation.LLM_INFERENCE, record_exception=True)
    def failing_function():
        raise ValueError("Test error")
    
    with pytest.raises(ValueError):
        failing_function()


def test_rag_span_context_manager():
    """Test rag_span context manager."""
    with rag_span("search", RAGOperation.VECTOR_SEARCH, top_k=10) as span:
        span.set_attribute("custom", "value")
        # Perform operation


def test_context_propagation_headers():
    """Test trace context propagation via headers."""
    propagator = TraceContextPropagator()
    
    # Inject context
    headers = propagator.inject_to_headers()
    
    assert "traceparent" in headers or len(headers) > 0


def test_context_propagation_kafka():
    """Test trace context propagation for Kafka."""
    propagator = TraceContextPropagator()
    
    # Inject to Kafka format
    kafka_headers = propagator.inject_to_kafka()
    
    assert isinstance(kafka_headers, list)


def test_set_retrieval_results():
    """Test setting retrieval result attributes."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    
    results = [
        {"id": "1", "score": 0.95},
        {"id": "2", "score": 0.85},
        {"id": "3", "score": 0.75},
    ]
    
    with tracer.start_as_current_span("test") as span:
        set_retrieval_results(span, results)


def test_set_llm_usage():
    """Test setting LLM usage attributes."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("test") as span:
        set_llm_usage(
            span,
            prompt_tokens=100,
            completion_tokens=50,
            model="gpt-4",
            provider="openai",
            stop_reason="stop",
        )


def test_otel_middleware_excludes_paths():
    """Test middleware excludes health endpoints."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    app.add_middleware(
        OTELMiddleware,
        service_name="test",
        excluded_paths=["/health"],
    )
    
    @app.get("/health")
    def health():
        return {"status": "ok"}
    
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200
```

## Integration Test

```python
@pytest.mark.integration
def test_end_to_end_tracing():
    """Test traces flow from service to collector."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    # Setup
    config = OTELConfig(
        service_name="integration-test",
        collector_endpoint="http://localhost:4317",
    )
    
    app = FastAPI()
    setup_otel_fastapi(app, config)
    
    @app.get("/query")
    async def query():
        with rag_span("embedding", RAGOperation.EMBEDDING_GENERATION) as span:
            span.set_attribute("test", "value")
        return {"status": "ok"}
    
    # Execute
    client = TestClient(app)
    response = client.get("/query")
    
    assert response.status_code == 200
    # Verify trace in Jaeger/Tempo manually or via API


@pytest.mark.integration
def test_trace_propagation_between_services():
    """Test trace context propagates between services."""
    propagator = TraceContextPropagator()
    
    # Simulate service A creating a trace
    tracer = trace.get_tracer("service-a")
    
    with tracer.start_as_current_span("service-a-request") as span:
        # Get headers to pass to service B
        headers = propagator.inject_to_headers()
        
        # Simulate service B receiving the request
        ctx = propagator.extract_from_headers(headers)
        
        # Service B should continue the trace
        with tracer.start_as_current_span(
            "service-b-request",
            context=ctx
        ) as child_span:
            # Verify parent-child relationship
            assert child_span.get_span_context().trace_id == span.get_span_context().trace_id
```

## Dependencies

```
opentelemetry-api>=1.22.0
opentelemetry-sdk>=1.22.0
opentelemetry-exporter-otlp>=1.22.0
opentelemetry-instrumentation-fastapi>=0.43b0
opentelemetry-instrumentation-httpx>=0.43b0
opentelemetry-instrumentation-redis>=0.43b0
opentelemetry-instrumentation-sqlalchemy>=0.43b0
opentelemetry-propagator-b3>=1.22.0
```

## Definition of Done

- [ ] OTELConfig with environment variable support
- [ ] OTELProvider with initialization and shutdown
- [ ] Auto-instrumentation for FastAPI, HTTPX, Redis, SQLAlchemy
- [ ] RAG-specific semantic attributes defined
- [ ] Span decorators for sync and async functions
- [ ] rag_span context manager implemented
- [ ] Context propagation utilities (HTTP, Kafka)
- [ ] FastAPI middleware with custom attributes
- [ ] OTEL Collector configuration with sampling
- [ ] Jaeger/Tempo deployment manifests
- [ ] Kubernetes manifests for OTEL Collector
- [ ] Trace context includes tenant_id and user_id
- [ ] Excluded paths for health/metrics endpoints
- [ ] >90% test coverage
- [ ] Integration tests passing
- [ ] Documentation complete
