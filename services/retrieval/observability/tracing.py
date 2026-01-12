"""OpenTelemetry tracing for the Retrieval Service."""

from collections.abc import Callable
from functools import wraps
from typing import Any

# Try to import OpenTelemetry, provide stubs if not available
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.semconv.resource import ResourceAttributes

    HAS_OPENTELEMETRY = True
except ImportError:
    HAS_OPENTELEMETRY = False
    trace = None  # type: ignore


class TracingSetup:
    """
    OpenTelemetry tracing configuration.

    Sets up distributed tracing with OTLP export to Jaeger.
    """

    def __init__(
        self,
        service_name: str = "retrieval-service",
        otlp_endpoint: str = "http://localhost:4317",
        enable_console_export: bool = False,
    ):
        """
        Initialize tracing setup.

        Args:
            service_name: Name of the service for traces
            otlp_endpoint: OTLP collector endpoint
            enable_console_export: Whether to also export to console
        """
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint
        self.tracer: Any | None = None
        self._enabled = HAS_OPENTELEMETRY

        if self._enabled:
            self._setup_tracing(enable_console_export)

    def _setup_tracing(self, enable_console: bool) -> None:
        """Configure OpenTelemetry tracing."""
        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: self.service_name,
                ResourceAttributes.SERVICE_VERSION: "1.0.0",
            },
        )

        provider = TracerProvider(resource=resource)

        # OTLP exporter for Jaeger
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.otlp_endpoint,
                insecure=True,
            )
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except Exception:  # noqa: S110
            # Silently fail if OTLP endpoint not available
            pass

        # Console exporter for debugging
        if enable_console:
            try:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            except ImportError:
                pass

        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(self.service_name)

    def instrument_app(self, app: Any) -> None:
        """
        Instrument FastAPI application.

        Args:
            app: FastAPI application instance
        """
        if not self._enabled:
            return

        try:
            FastAPIInstrumentor.instrument_app(app)
            HTTPXClientInstrumentor().instrument()
        except Exception:  # noqa: S110
            # Silently fail if instrumentation fails
            pass

    def get_tracer(self) -> Any | None:
        """
        Get the configured tracer.

        Returns:
            OpenTelemetry tracer or None if not enabled
        """
        return self.tracer

    def span(self, name: str) -> Callable:
        """
        Decorator to create a span for a function.

        Args:
            name: Name for the span

        Returns:
            Decorator function
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                if not self._enabled or not self.tracer:
                    return await func(*args, **kwargs)

                with self.tracer.start_as_current_span(name) as span:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        span.set_status(
                            trace.Status(trace.StatusCode.ERROR, str(e)),
                        )
                        span.record_exception(e)
                        raise

            return wrapper

        return decorator

    @staticmethod
    def get_current_trace_id() -> str | None:
        """
        Get current trace ID if in a span.

        Returns:
            Trace ID as hex string or None
        """
        if not HAS_OPENTELEMETRY:
            return None

        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.trace_id, "032x")
        return None

    @staticmethod
    def get_current_span_id() -> str | None:
        """
        Get current span ID if in a span.

        Returns:
            Span ID as hex string or None
        """
        if not HAS_OPENTELEMETRY:
            return None

        span = trace.get_current_span()
        if span:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.span_id, "016x")
        return None


def traced_retrieval(tracer: Any | None) -> Callable:
    """
    Decorator to trace retrieval operations with custom attributes.

    Args:
        tracer: OpenTelemetry tracer instance

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not HAS_OPENTELEMETRY or tracer is None:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span("retrieval") as span:
                # Extract request from args/kwargs
                request = kwargs.get("body") or (args[1] if len(args) > 1 else None)

                if request:
                    span.set_attribute("retrieval.query_length", len(request.query))
                    span.set_attribute("retrieval.mode", request.mode.value)
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
