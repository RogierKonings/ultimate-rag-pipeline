"""
OpenTelemetry Tracing Module.

Provides distributed tracing capabilities with:
- Automatic instrumentation for FastAPI and Celery
- RAG-specific span attributes
- Context propagation across services
- Configurable sampling strategies

Usage:
    from shared.observability.otel import setup_tracing, get_tracer

    # At startup
    setup_tracing(service_name="my-service")

    # Get tracer for manual span creation
    tracer = get_tracer()
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("key", "value")
"""

from .tracer import (
    OTELConfig,
    setup_tracing,
    get_tracer,
    get_tracer_provider,
    shutdown_tracing,
)
from .spans import traced, rag_span, get_current_span, add_span_event, set_span_error
from .attributes import RAGOperation, RAGAttributes, set_rag_attributes
from .context import (
    TraceContextPropagator,
    inject_trace_context,
    extract_trace_context,
    get_current_trace_id,
    get_current_span_id,
)

__all__ = [
    # Configuration
    "OTELConfig",
    "setup_tracing",
    "get_tracer",
    "get_tracer_provider",
    "shutdown_tracing",
    # Spans
    "traced",
    "rag_span",
    "get_current_span",
    "add_span_event",
    "set_span_error",
    # Attributes
    "RAGOperation",
    "RAGAttributes",
    "set_rag_attributes",
    # Context
    "TraceContextPropagator",
    "inject_trace_context",
    "extract_trace_context",
    "get_current_trace_id",
    "get_current_span_id",
]
