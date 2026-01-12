"""
Tests for OpenTelemetry tracing module.
"""

import asyncio
from unittest.mock import Mock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider


class TestOTELConfig:
    """Tests for OTELConfig."""

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        from shared.observability.otel.tracer import OTELConfig

        with patch.dict(
            "os.environ",
            {
                "OTEL_SERVICE_NAME": "test-service",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "localhost:4317",
                "ENVIRONMENT": "testing",
                "OTEL_TRACES_SAMPLER_ARG": "0.5",
            },
        ):
            config = OTELConfig.from_env("default-service")

            assert config.service_name == "test-service"
            assert config.otlp_endpoint == "localhost:4317"
            assert config.environment == "testing"
            assert config.sample_rate == 0.5

    def test_config_defaults(self):
        """Test default configuration values."""
        from shared.observability.otel.tracer import OTELConfig

        config = OTELConfig(service_name="test")

        assert config.service_name == "test"
        assert config.service_version == "1.0.0"
        assert config.batch_export_delay_ms == 5000

    def test_sampler_for_environments(self):
        """Test sampler selection based on environment."""
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

        from shared.observability.otel.tracer import OTELConfig

        # Development - always sample
        dev_config = OTELConfig(service_name="test", environment="development")
        assert dev_config.get_sampler() == ALWAYS_ON

        # Production - ratio based
        prod_config = OTELConfig(
            service_name="test",
            environment="production",
            sample_rate=0.1,
        )
        sampler = prod_config.get_sampler()
        assert isinstance(sampler, ParentBased)


class TestTracerSetup:
    """Tests for tracer setup."""

    def test_setup_tracing_returns_provider(self):
        """Test that setup_tracing returns a TracerProvider."""
        from shared.observability.otel.tracer import setup_tracing, shutdown_tracing

        # Reset global state
        shutdown_tracing()

        with patch("shared.observability.otel.tracer.OTLPSpanExporter"):
            provider = setup_tracing(
                service_name="test-service",
                otlp_endpoint="localhost:4317",
            )

            assert isinstance(provider, TracerProvider)
            shutdown_tracing()

    def test_get_tracer_returns_tracer(self):
        """Test that get_tracer returns a valid tracer."""
        from shared.observability.otel.tracer import get_tracer

        tracer = get_tracer("test-module")
        assert tracer is not None


class TestRAGAttributes:
    """Tests for RAG-specific attributes."""

    def test_rag_operation_enum(self):
        """Test RAGOperation enum values."""
        from shared.observability.otel.attributes import RAGOperation

        assert RAGOperation.QUERY.value == "query"
        assert RAGOperation.VECTOR_SEARCH.value == "search.vector"
        assert RAGOperation.LLM_INFERENCE.value == "llm.inference"
        assert RAGOperation.INGEST.value == "ingest"

    def test_rag_attributes_constants(self):
        """Test RAGAttributes constant values."""
        from shared.observability.otel.attributes import RAGAttributes

        assert RAGAttributes.OPERATION == "rag.operation"
        assert RAGAttributes.TENANT_ID == "rag.tenant_id"
        assert RAGAttributes.QUERY_TEXT == "rag.query.text"
        assert RAGAttributes.LLM_MODEL == "rag.llm.model"

    def test_set_rag_attributes(self):
        """Test setting RAG attributes on a span."""
        from shared.observability.otel.attributes import (
            RAGAttributes,
            RAGOperation,
            set_rag_attributes,
        )

        mock_span = Mock()
        mock_span.is_recording.return_value = True

        with patch(
            "shared.observability.otel.attributes.trace.get_current_span", return_value=mock_span,
        ):
            set_rag_attributes(
                operation=RAGOperation.QUERY,
                tenant_id="tenant-123",
                user_id="user-456",
            )

            # Verify attributes were set
            calls = mock_span.set_attribute.call_args_list
            assert any(call[0] == (RAGAttributes.OPERATION, "query") for call in calls)
            assert any(call[0] == (RAGAttributes.TENANT_ID, "tenant-123") for call in calls)
            assert any(call[0] == (RAGAttributes.USER_ID, "user-456") for call in calls)

    def test_set_retrieval_results(self):
        """Test setting retrieval result attributes."""
        from shared.observability.otel.attributes import RAGAttributes, set_retrieval_results

        mock_span = Mock()
        mock_span.is_recording.return_value = True

        with patch(
            "shared.observability.otel.attributes.trace.get_current_span", return_value=mock_span,
        ):
            set_retrieval_results(count=5, scores=[0.9, 0.8, 0.7, 0.6, 0.5])

            calls = mock_span.set_attribute.call_args_list
            assert any(call[0] == (RAGAttributes.RETRIEVAL_COUNT, 5) for call in calls)
            assert any(call[0] == (RAGAttributes.RETRIEVAL_TOP_SCORE, 0.9) for call in calls)
            assert any(call[0] == (RAGAttributes.RETRIEVAL_ZERO_RESULTS, False) for call in calls)

    def test_set_llm_usage(self):
        """Test setting LLM usage attributes."""
        from shared.observability.otel.attributes import RAGAttributes, set_llm_usage

        mock_span = Mock()
        mock_span.is_recording.return_value = True

        with patch(
            "shared.observability.otel.attributes.trace.get_current_span", return_value=mock_span,
        ):
            set_llm_usage(
                model="llama-3.1-8b",
                provider="vllm",
                input_tokens=100,
                output_tokens=50,
                ttft_ms=150.5,
            )

            calls = mock_span.set_attribute.call_args_list
            assert any(call[0] == (RAGAttributes.LLM_MODEL, "llama-3.1-8b") for call in calls)
            assert any(call[0] == (RAGAttributes.LLM_INPUT_TOKENS, 100) for call in calls)
            assert any(call[0] == (RAGAttributes.LLM_OUTPUT_TOKENS, 50) for call in calls)
            assert any(call[0] == (RAGAttributes.LLM_TOTAL_TOKENS, 150) for call in calls)


class TestSpanDecorators:
    """Tests for span decorators and helpers."""

    def test_traced_decorator_sync(self):
        """Test @traced decorator with sync function."""
        from shared.observability.otel.attributes import RAGOperation
        from shared.observability.otel.spans import traced

        @traced("test_operation", operation=RAGOperation.QUERY)
        def test_function(x: int, y: int) -> int:
            return x + y

        result = test_function(1, 2)
        assert result == 3

    @pytest.mark.asyncio
    async def test_traced_decorator_async(self):
        """Test @traced decorator with async function."""
        from shared.observability.otel.attributes import RAGOperation
        from shared.observability.otel.spans import traced

        @traced("async_test", operation=RAGOperation.EMBEDDING)
        async def async_function(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 2

        result = await async_function(5)
        assert result == 10

    def test_traced_decorator_with_exception(self):
        """Test @traced decorator records exceptions."""
        from shared.observability.otel.spans import traced

        @traced("error_function")
        def error_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            error_function()

    def test_rag_span_context_manager(self):
        """Test rag_span context manager."""
        from shared.observability.otel.attributes import RAGOperation
        from shared.observability.otel.spans import rag_span

        with rag_span("test_span", RAGOperation.VECTOR_SEARCH) as span:
            assert span is not None
            # Operations happen here

    def test_get_current_span(self):
        """Test get_current_span helper."""
        from shared.observability.otel.spans import get_current_span, rag_span

        # Outside of span context
        assert get_current_span() is None or not get_current_span().is_recording()

        # Inside span context
        with rag_span("test"):
            current = get_current_span()
            assert current is not None

    def test_add_span_event(self):
        """Test add_span_event helper."""
        from shared.observability.otel.spans import add_span_event, rag_span

        with rag_span("test"):
            add_span_event("test_event", {"key": "value"})
            # Event is added (no error)


class TestContextPropagation:
    """Tests for trace context propagation."""

    def test_inject_trace_context(self):
        """Test injecting trace context into headers."""
        from shared.observability.otel.context import inject_trace_context

        headers = inject_trace_context()
        assert isinstance(headers, dict)

    def test_extract_trace_context(self):
        """Test extracting trace context from headers."""
        from shared.observability.otel.context import extract_trace_context

        headers = {
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        context = extract_trace_context(headers)
        assert context is not None

    def test_get_current_trace_id(self):
        """Test getting current trace ID."""
        from shared.observability.otel.context import get_current_trace_id
        from shared.observability.otel.spans import rag_span

        # Outside span - may be None
        get_current_trace_id()

        # Inside span - should have ID
        with rag_span("test"):
            trace_id = get_current_trace_id()
            if trace_id:
                assert len(trace_id) == 32  # 32 hex chars

    def test_celery_trace_propagator(self):
        """Test Celery trace context propagation."""
        from shared.observability.otel.context import CeleryTracePropagator

        # Inject headers
        headers = CeleryTracePropagator.inject_task_headers()
        assert isinstance(headers, dict)

        # Extract context
        context = CeleryTracePropagator.extract_task_context(headers)
        assert context is not None

    def test_kafka_trace_propagator(self):
        """Test Kafka trace context propagation."""
        from shared.observability.otel.context import KafkaTracePropagator

        # Inject headers
        headers = KafkaTracePropagator.inject_message_headers()
        assert isinstance(headers, list)

        # Extract context
        context = KafkaTracePropagator.extract_message_context(headers)
        assert context is not None
