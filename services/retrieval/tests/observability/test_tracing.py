"""Tests for TracingSetup."""

import pytest
from observability.tracing import TracingSetup, traced_retrieval


class TestTracingSetup:
    """Tests for TracingSetup."""

    @pytest.fixture
    def tracing(self):
        """Create tracing instance."""
        return TracingSetup(
            service_name="test-service",
            otlp_endpoint="http://localhost:4317",
            enable_console_export=False,
        )

    def test_tracing_initialization(self, tracing):
        """Test tracing initializes correctly."""
        assert tracing.service_name == "test-service"
        assert tracing.otlp_endpoint == "http://localhost:4317"

    def test_get_tracer(self, tracing):
        """Test getting tracer instance."""
        tracing.get_tracer()
        # Tracer may be None if OpenTelemetry not installed
        # Just verify method doesn't raise

    def test_span_decorator(self, tracing):
        """Test span decorator."""

        @tracing.span("test_operation")
        async def sample_operation():
            return "result"

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(sample_operation())
        assert result == "result"

    def test_span_decorator_with_error(self, tracing):
        """Test span decorator handles errors."""

        @tracing.span("failing_operation")
        async def failing_operation():
            raise ValueError("Test error")

        import asyncio

        with pytest.raises(ValueError):
            asyncio.get_event_loop().run_until_complete(failing_operation())

    def test_get_current_trace_id(self):
        """Test getting current trace ID."""
        trace_id = TracingSetup.get_current_trace_id()
        # May be None if not in a span
        assert trace_id is None or isinstance(trace_id, str)

    def test_get_current_span_id(self):
        """Test getting current span ID."""
        span_id = TracingSetup.get_current_span_id()
        # May be None if not in a span
        assert span_id is None or isinstance(span_id, str)

    def test_instrument_app(self, tracing):
        """Test instrumenting FastAPI app."""
        from fastapi import FastAPI

        app = FastAPI()
        # Should not raise even if OpenTelemetry not fully configured
        tracing.instrument_app(app)


class TestTracedRetrievalDecorator:
    """Tests for traced_retrieval decorator."""

    def test_traced_retrieval_no_tracer(self):
        """Test traced_retrieval with no tracer."""

        @traced_retrieval(None)
        async def retrieve():
            return {"results": []}

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(retrieve())
        assert result == {"results": []}

    def test_traced_retrieval_with_tracer(self):
        """Test traced_retrieval with tracer (if available)."""
        tracing = TracingSetup(
            service_name="test-service",
            enable_console_export=False,
        )
        tracer = tracing.get_tracer()

        @traced_retrieval(tracer)
        async def retrieve():
            return {"results": []}

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(retrieve())
        assert result == {"results": []}


class TestTracingWithSpans:
    """Tests for tracing with actual spans."""

    def test_trace_id_format(self):
        """Test trace ID format if available."""
        tracing = TracingSetup(
            service_name="test-format",
            enable_console_export=False,
        )
        tracer = tracing.get_tracer()

        if tracer is not None:
            with tracer.start_as_current_span("test_span"):
                trace_id = TracingSetup.get_current_trace_id()
                span_id = TracingSetup.get_current_span_id()

                if trace_id:
                    # Trace ID should be 32 hex characters (128-bit)
                    assert len(trace_id) == 32
                    assert all(c in "0123456789abcdef" for c in trace_id)

                if span_id:
                    # Span ID should be 16 hex characters (64-bit)
                    assert len(span_id) == 16
                    assert all(c in "0123456789abcdef" for c in span_id)

    def test_nested_spans(self):
        """Test nested spans."""
        tracing = TracingSetup(
            service_name="test-nested",
            enable_console_export=False,
        )
        tracer = tracing.get_tracer()

        if tracer is not None:
            with tracer.start_as_current_span("parent_span"):
                parent_trace_id = TracingSetup.get_current_trace_id()

                with tracer.start_as_current_span("child_span"):
                    child_trace_id = TracingSetup.get_current_trace_id()
                    TracingSetup.get_current_span_id()

                    # Should have same trace ID
                    if parent_trace_id and child_trace_id:
                        assert parent_trace_id == child_trace_id


class TestTracingConfigOptions:
    """Tests for tracing configuration options."""

    def test_custom_service_name(self):
        """Test custom service name."""
        tracing = TracingSetup(service_name="custom-retrieval-service")
        assert tracing.service_name == "custom-retrieval-service"

    def test_custom_endpoint(self):
        """Test custom OTLP endpoint."""
        tracing = TracingSetup(otlp_endpoint="http://jaeger:4317")
        assert tracing.otlp_endpoint == "http://jaeger:4317"

    def test_console_export_enabled(self):
        """Test console export option."""
        # Should not raise
        tracing = TracingSetup(
            service_name="test-console",
            enable_console_export=True,
        )
        assert tracing is not None
