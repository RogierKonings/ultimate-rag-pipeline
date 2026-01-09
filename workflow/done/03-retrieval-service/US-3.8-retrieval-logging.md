# US-3.8: Retrieval Logging

> **Story ID:** US-3.8  
> **Epic:** Retrieval Service  
> **Priority:** High  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** US-3.7 (Retrieval API)

## User Story

**As an** ML engineer  
**I want** retrieval operations logged  
**So that** I can analyze and improve retrieval quality

## Context

Comprehensive logging and metrics are essential for understanding retrieval performance, debugging issues, and improving the system over time. Per the architecture, the system uses OpenTelemetry for distributed tracing and Prometheus for metrics. Structured logging captures query details, results, and latency for offline analysis.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── logging/
    ├── __init__.py
    ├── retrieval_logger.py  # Structured logging
    ├── metrics.py           # Prometheus metrics
    ├── tracing.py           # OpenTelemetry setup
    └── middleware.py        # FastAPI middleware
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class RetrievalLogEntry(BaseModel):
    """Structured log entry for retrieval operations."""
    # Identifiers
    query_id: UUID
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    
    # Request info
    query: str
    query_type: Optional[str] = None
    mode: str  # hybrid, semantic, keyword
    
    # User context (anonymized)
    tenant_id: UUID
    user_id_hash: Optional[str] = None  # Hashed for privacy
    
    # Results
    result_count: int
    top_scores: list[float] = []  # Top-k scores
    
    # Timing
    total_ms: float
    preprocessing_ms: float
    search_ms: float
    rerank_ms: Optional[float] = None
    
    # Components used
    used_semantic: bool = False
    used_keyword: bool = False
    used_reranking: bool = False
    
    # Timestamps
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Error info
    error: Optional[str] = None
    error_type: Optional[str] = None
```

### Structured Logger

```python
import json
import logging
import hashlib
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
import structlog
from structlog.types import Processor

class RetrievalLogger:
    """
    Structured logger for retrieval operations.
    
    Outputs JSON-formatted logs suitable for log aggregation
    systems like ELK, Loki, or CloudWatch.
    """
    
    def __init__(
        self,
        service_name: str = "retrieval-service",
        log_level: str = "INFO",
        output_format: str = "json"  # "json" or "console"
    ):
        self.service_name = service_name
        self.log_level = log_level
        self.output_format = output_format
        
        self._configure_structlog()
        self._logger = structlog.get_logger()
    
    def _configure_structlog(self):
        """Configure structlog with appropriate processors."""
        processors: list[Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]
        
        if self.output_format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())
        
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, self.log_level.upper())
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    
    def log_retrieval(
        self,
        query_id: UUID,
        query: str,
        mode: str,
        tenant_id: UUID,
        user_id: Optional[UUID],
        result_count: int,
        top_scores: list[float],
        total_ms: float,
        preprocessing_ms: float,
        search_ms: float,
        rerank_ms: Optional[float] = None,
        used_semantic: bool = False,
        used_keyword: bool = False,
        used_reranking: bool = False,
        error: Optional[str] = None,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        extra: Optional[dict] = None
    ):
        """
        Log a retrieval operation.
        
        Args:
            query_id: Unique identifier for this query
            query: The search query text
            mode: Search mode (hybrid, semantic, keyword)
            tenant_id: Tenant identifier
            user_id: User identifier (will be hashed)
            result_count: Number of results returned
            top_scores: List of top result scores
            total_ms: Total request time in milliseconds
            preprocessing_ms: Query preprocessing time
            search_ms: Search execution time
            rerank_ms: Reranking time (if used)
            used_semantic: Whether semantic search was used
            used_keyword: Whether keyword search was used
            used_reranking: Whether reranking was used
            error: Error message if failed
            trace_id: OpenTelemetry trace ID
            span_id: OpenTelemetry span ID
            extra: Additional context
        """
        # Hash user_id for privacy
        user_id_hash = None
        if user_id:
            user_id_hash = hashlib.sha256(str(user_id).encode()).hexdigest()[:16]
        
        log_data = {
            "event": "retrieval",
            "service": self.service_name,
            "query_id": str(query_id),
            "query_length": len(query),
            "query_word_count": len(query.split()),
            "mode": mode,
            "tenant_id": str(tenant_id),
            "user_id_hash": user_id_hash,
            "result_count": result_count,
            "top_score": top_scores[0] if top_scores else None,
            "avg_score": sum(top_scores) / len(top_scores) if top_scores else None,
            "total_ms": round(total_ms, 2),
            "preprocessing_ms": round(preprocessing_ms, 2),
            "search_ms": round(search_ms, 2),
            "rerank_ms": round(rerank_ms, 2) if rerank_ms else None,
            "used_semantic": used_semantic,
            "used_keyword": used_keyword,
            "used_reranking": used_reranking,
        }
        
        if trace_id:
            log_data["trace_id"] = trace_id
        if span_id:
            log_data["span_id"] = span_id
        if extra:
            log_data.update(extra)
        
        if error:
            log_data["error"] = error
            self._logger.error(**log_data)
        else:
            self._logger.info(**log_data)
    
    def log_query_expansion(
        self,
        query_id: UUID,
        original_query: str,
        expanded_queries: list[str],
        method: str,  # "synonym", "llm", "hyde"
        duration_ms: float
    ):
        """Log query expansion operation."""
        self._logger.info(
            event="query_expansion",
            query_id=str(query_id),
            original_length=len(original_query),
            expansion_count=len(expanded_queries),
            method=method,
            duration_ms=round(duration_ms, 2)
        )
    
    def log_cache_operation(
        self,
        operation: str,  # "hit", "miss", "set"
        cache_type: str,  # "query", "embedding", "rerank"
        key_prefix: str,
        duration_ms: float
    ):
        """Log cache operation."""
        self._logger.debug(
            event="cache_operation",
            operation=operation,
            cache_type=cache_type,
            key_prefix=key_prefix,
            duration_ms=round(duration_ms, 2)
        )
    
    def log_error(
        self,
        error: Exception,
        context: dict,
        query_id: Optional[UUID] = None
    ):
        """Log error with context."""
        self._logger.error(
            event="error",
            query_id=str(query_id) if query_id else None,
            error_type=type(error).__name__,
            error_message=str(error),
            **context
        )
```

### Prometheus Metrics

```python
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST
)
from functools import wraps
import time

class RetrievalMetrics:
    """
    Prometheus metrics for retrieval operations.
    
    Exposes metrics at /metrics endpoint for Prometheus scraping.
    """
    
    def __init__(self, service_name: str = "retrieval_service"):
        self.service_name = service_name
        
        # Request counters
        self.requests_total = Counter(
            f"{service_name}_requests_total",
            "Total number of retrieval requests",
            ["mode", "status"]
        )
        
        # Result counters
        self.results_total = Counter(
            f"{service_name}_results_total",
            "Total number of results returned",
            ["mode"]
        )
        
        # Latency histograms
        self.request_duration = Histogram(
            f"{service_name}_request_duration_seconds",
            "Request duration in seconds",
            ["mode", "component"],
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0]
        )
        
        self.preprocessing_duration = Histogram(
            f"{service_name}_preprocessing_duration_seconds",
            "Query preprocessing duration in seconds",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2]
        )
        
        self.search_duration = Histogram(
            f"{service_name}_search_duration_seconds",
            "Search execution duration in seconds",
            ["search_type"],  # semantic, keyword
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2]
        )
        
        self.rerank_duration = Histogram(
            f"{service_name}_rerank_duration_seconds",
            "Reranking duration in seconds",
            ["doc_count_bucket"],  # "1-10", "11-20", "21-50"
            buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2]
        )
        
        # Score histograms
        self.top_score = Histogram(
            f"{service_name}_top_score",
            "Top result score distribution",
            ["mode"],
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )
        
        # Result count histogram
        self.result_count = Histogram(
            f"{service_name}_result_count",
            "Number of results per query",
            ["mode"],
            buckets=[0, 1, 2, 5, 10, 20, 50, 100]
        )
        
        # Cache metrics
        self.cache_hits = Counter(
            f"{service_name}_cache_hits_total",
            "Cache hit count",
            ["cache_type"]
        )
        
        self.cache_misses = Counter(
            f"{service_name}_cache_misses_total",
            "Cache miss count",
            ["cache_type"]
        )
        
        # Current state
        self.active_requests = Gauge(
            f"{service_name}_active_requests",
            "Number of currently active requests"
        )
        
        # Component health
        self.component_health = Gauge(
            f"{service_name}_component_health",
            "Component health status (1=healthy, 0=unhealthy)",
            ["component"]
        )
        
        # Service info
        self.service_info = Info(
            f"{service_name}_info",
            "Service information"
        )
    
    def record_request(
        self,
        mode: str,
        status: str,  # "success", "error"
        duration_seconds: float,
        result_count: int,
        top_score: Optional[float] = None
    ):
        """Record a retrieval request."""
        self.requests_total.labels(mode=mode, status=status).inc()
        self.request_duration.labels(mode=mode, component="total").observe(duration_seconds)
        self.result_count.labels(mode=mode).observe(result_count)
        self.results_total.labels(mode=mode).inc(result_count)
        
        if top_score is not None:
            self.top_score.labels(mode=mode).observe(top_score)
    
    def record_preprocessing(self, duration_seconds: float):
        """Record preprocessing duration."""
        self.preprocessing_duration.observe(duration_seconds)
    
    def record_search(self, search_type: str, duration_seconds: float):
        """Record search duration."""
        self.search_duration.labels(search_type=search_type).observe(duration_seconds)
    
    def record_rerank(self, doc_count: int, duration_seconds: float):
        """Record reranking duration."""
        if doc_count <= 10:
            bucket = "1-10"
        elif doc_count <= 20:
            bucket = "11-20"
        else:
            bucket = "21-50"
        
        self.rerank_duration.labels(doc_count_bucket=bucket).observe(duration_seconds)
    
    def record_cache(self, cache_type: str, hit: bool):
        """Record cache hit/miss."""
        if hit:
            self.cache_hits.labels(cache_type=cache_type).inc()
        else:
            self.cache_misses.labels(cache_type=cache_type).inc()
    
    def set_component_health(self, component: str, healthy: bool):
        """Set component health status."""
        self.component_health.labels(component=component).set(1 if healthy else 0)
    
    def set_service_info(self, version: str, **extra):
        """Set service info."""
        self.service_info.info({
            "version": version,
            **extra
        })
    
    def request_tracking(self, mode: str = "hybrid"):
        """Decorator for tracking request metrics."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                self.active_requests.inc()
                start_time = time.time()
                status = "success"
                
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    raise
                finally:
                    duration = time.time() - start_time
                    self.active_requests.dec()
                    self.request_duration.labels(mode=mode, component="total").observe(duration)
            
            return wrapper
        return decorator


# Global metrics instance
metrics = RetrievalMetrics()
```

### OpenTelemetry Tracing

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes
from typing import Optional
from functools import wraps

class TracingSetup:
    """
    OpenTelemetry tracing configuration.
    
    Sets up distributed tracing with OTLP export to Jaeger.
    """
    
    def __init__(
        self,
        service_name: str = "retrieval-service",
        otlp_endpoint: str = "http://localhost:4317",
        enable_console_export: bool = False
    ):
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint
        self.tracer: Optional[trace.Tracer] = None
        
        self._setup_tracing(enable_console_export)
    
    def _setup_tracing(self, enable_console: bool):
        """Configure OpenTelemetry tracing."""
        resource = Resource.create({
            ResourceAttributes.SERVICE_NAME: self.service_name,
            ResourceAttributes.SERVICE_VERSION: "1.0.0"
        })
        
        provider = TracerProvider(resource=resource)
        
        # OTLP exporter for Jaeger
        otlp_exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        
        # Console exporter for debugging
        if enable_console:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(self.service_name)
    
    def instrument_app(self, app):
        """Instrument FastAPI application."""
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
    
    def get_tracer(self) -> trace.Tracer:
        """Get the configured tracer."""
        return self.tracer
    
    def span(self, name: str):
        """Decorator to create a span for a function."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                with self.tracer.start_as_current_span(name) as span:
                    try:
                        result = await func(*args, **kwargs)
                        return result
                    except Exception as e:
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        raise
            return wrapper
        return decorator
    
    @staticmethod
    def get_current_trace_id() -> Optional[str]:
        """Get current trace ID if in a span."""
        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.trace_id, '032x')
        return None
    
    @staticmethod
    def get_current_span_id() -> Optional[str]:
        """Get current span ID if in a span."""
        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.span_id, '016x')
        return None


def traced_retrieval(tracer: trace.Tracer):
    """
    Decorator to trace retrieval operations with custom attributes.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            with tracer.start_as_current_span("retrieval") as span:
                # Extract request from args/kwargs
                request = kwargs.get('body') or (args[1] if len(args) > 1 else None)
                
                if request:
                    span.set_attribute("retrieval.query_length", len(request.query))
                    span.set_attribute("retrieval.mode", request.mode)
                    span.set_attribute("retrieval.top_k", request.top_k)
                    span.set_attribute("retrieval.rerank", request.rerank)
                
                try:
                    result = await func(*args, **kwargs)
                    
                    # Add result attributes
                    span.set_attribute("retrieval.result_count", len(result.results))
                    span.set_attribute("retrieval.total_ms", result.metrics.total_ms)
                    
                    return result
                except Exception as e:
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise
        
        return wrapper
    return decorator
```

### FastAPI Middleware Integration

```python
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import time

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic request/response logging.
    """
    
    def __init__(self, app: FastAPI, logger: RetrievalLogger, metrics: RetrievalMetrics):
        super().__init__(app)
        self.logger = logger
        self.metrics = metrics
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Track active requests
        self.metrics.active_requests.inc()
        
        try:
            response = await call_next(request)
            
            # Log request completion
            duration = time.time() - start_time
            
            self.logger._logger.info(
                event="http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2)
            )
            
            return response
        except Exception as e:
            duration = time.time() - start_time
            
            self.logger._logger.error(
                event="http_request_error",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=round(duration * 1000, 2)
            )
            raise
        finally:
            self.metrics.active_requests.dec()


def setup_observability(app: FastAPI, config):
    """
    Set up all observability components for FastAPI app.
    """
    # Logger
    logger = RetrievalLogger(
        service_name=config.service_name,
        log_level=config.log_level
    )
    
    # Metrics
    metrics = RetrievalMetrics(config.service_name)
    metrics.set_service_info(version="1.0.0")
    
    # Tracing
    tracing = TracingSetup(
        service_name=config.service_name,
        otlp_endpoint=config.otlp_endpoint
    )
    tracing.instrument_app(app)
    
    # Add middleware
    app.add_middleware(LoggingMiddleware, logger=logger, metrics=metrics)
    
    # Metrics endpoint
    from fastapi import Response
    
    @app.get("/metrics")
    async def get_metrics():
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    
    # Store in app state
    app.state.logger = logger
    app.state.metrics = metrics
    app.state.tracing = tracing
    
    return logger, metrics, tracing
```

## Acceptance Criteria

- [ ] Structured JSON logging for all retrieval operations
- [ ] Log entries include query_id, timing, result counts
- [ ] User IDs hashed for privacy
- [ ] Prometheus metrics exposed at /metrics
- [ ] Request latency histogram with appropriate buckets
- [ ] Result count and score histograms
- [ ] Cache hit/miss counters
- [ ] Component health gauges
- [ ] OpenTelemetry tracing configured
- [ ] Trace IDs propagated through pipeline
- [ ] Spans created for major operations
- [ ] FastAPI middleware auto-logs requests
- [ ] Error logging with stack traces

## Testing Requirements

```python
import pytest
from uuid import uuid4
from datetime import datetime

@pytest.fixture
def logger():
    return RetrievalLogger(output_format="json")

@pytest.fixture
def metrics():
    return RetrievalMetrics()

def test_structured_logging(logger, capsys):
    """Test that logs are structured JSON."""
    logger.log_retrieval(
        query_id=uuid4(),
        query="test query",
        mode="hybrid",
        tenant_id=uuid4(),
        user_id=uuid4(),
        result_count=5,
        top_scores=[0.9, 0.8, 0.7],
        total_ms=150.5,
        preprocessing_ms=20.0,
        search_ms=100.0,
        rerank_ms=30.5,
        used_semantic=True,
        used_keyword=True,
        used_reranking=True
    )
    
    captured = capsys.readouterr()
    import json
    log_entry = json.loads(captured.out)
    
    assert log_entry["event"] == "retrieval"
    assert log_entry["mode"] == "hybrid"
    assert log_entry["result_count"] == 5

def test_user_id_hashed(logger, capsys):
    """Test that user IDs are hashed."""
    user_id = uuid4()
    
    logger.log_retrieval(
        query_id=uuid4(),
        query="test",
        mode="hybrid",
        tenant_id=uuid4(),
        user_id=user_id,
        result_count=0,
        top_scores=[],
        total_ms=10,
        preprocessing_ms=5,
        search_ms=5
    )
    
    captured = capsys.readouterr()
    import json
    log_entry = json.loads(captured.out)
    
    # Should have hash, not original UUID
    assert log_entry["user_id_hash"] is not None
    assert str(user_id) not in captured.out

def test_metrics_request_recording(metrics):
    """Test Prometheus metrics recording."""
    metrics.record_request(
        mode="hybrid",
        status="success",
        duration_seconds=0.15,
        result_count=10,
        top_score=0.92
    )
    
    # Verify counter incremented
    assert metrics.requests_total.labels(mode="hybrid", status="success")._value._value == 1

def test_metrics_latency_buckets(metrics):
    """Test that latency falls into correct buckets."""
    metrics.record_request(
        mode="semantic",
        status="success",
        duration_seconds=0.05,  # 50ms
        result_count=5,
        top_score=0.85
    )
    
    # Check histogram
    histogram = metrics.request_duration.labels(mode="semantic", component="total")
    # 50ms should fall in bucket after 0.05 seconds
    assert histogram._sum._value > 0

def test_cache_metrics(metrics):
    """Test cache hit/miss tracking."""
    metrics.record_cache("query", hit=True)
    metrics.record_cache("query", hit=False)
    metrics.record_cache("embedding", hit=True)
    
    assert metrics.cache_hits.labels(cache_type="query")._value._value == 1
    assert metrics.cache_misses.labels(cache_type="query")._value._value == 1
    assert metrics.cache_hits.labels(cache_type="embedding")._value._value == 1

def test_component_health(metrics):
    """Test component health gauge."""
    metrics.set_component_health("qdrant", True)
    metrics.set_component_health("opensearch", False)
    
    assert metrics.component_health.labels(component="qdrant")._value._value == 1
    assert metrics.component_health.labels(component="opensearch")._value._value == 0

def test_tracing_setup():
    """Test OpenTelemetry tracing setup."""
    tracing = TracingSetup(enable_console_export=False)
    
    tracer = tracing.get_tracer()
    assert tracer is not None
    
    # Test span creation
    with tracer.start_as_current_span("test_span") as span:
        trace_id = tracing.get_current_trace_id()
        span_id = tracing.get_current_span_id()
        
        assert trace_id is not None
        assert span_id is not None
        assert len(trace_id) == 32  # 128-bit hex
        assert len(span_id) == 16   # 64-bit hex

def test_error_logging(logger, capsys):
    """Test error logging with context."""
    try:
        raise ValueError("Test error")
    except Exception as e:
        logger.log_error(
            error=e,
            context={"operation": "search"},
            query_id=uuid4()
        )
    
    captured = capsys.readouterr()
    assert "ValueError" in captured.out
    assert "Test error" in captured.out
```

## Integration Test

```python
@pytest.mark.integration
def test_observability_with_real_services():
    """Integration test with real observability stack."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    
    class MockConfig:
        service_name = "test-retrieval"
        log_level = "INFO"
        otlp_endpoint = "http://localhost:4317"
    
    logger, metrics, tracing = setup_observability(app, MockConfig())
    
    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}
    
    client = TestClient(app)
    
    # Make request
    response = client.get("/test")
    assert response.status_code == 200
    
    # Check metrics endpoint
    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert "retrieval" in metrics_response.text or "http" in metrics_response.text
```

## Dependencies

- `structlog>=23.2.0`
- `prometheus-client>=0.19.0`
- `opentelemetry-api>=1.21.0`
- `opentelemetry-sdk>=1.21.0`
- `opentelemetry-instrumentation-fastapi>=0.42b0`
- `opentelemetry-instrumentation-httpx>=0.42b0`
- `opentelemetry-exporter-otlp>=1.21.0`

## Definition of Done

- [ ] RetrievalLogger outputs structured JSON
- [ ] All retrieval operations logged with timing
- [ ] User privacy protected (ID hashing)
- [ ] Prometheus metrics exposed at /metrics
- [ ] Latency histograms with correct buckets
- [ ] Cache metrics tracked
- [ ] Component health gauges
- [ ] OpenTelemetry tracing configured
- [ ] Spans created for major operations
- [ ] Trace context propagated
- [ ] FastAPI middleware integrated
- [ ] Error logging with context
- [ ] >90% test coverage
- [ ] Integration test passes
- [ ] Docstrings complete
- [ ] Type hints validated with mypy
