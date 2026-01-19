"""Integration tests for trace hierarchy."""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


# Global provider/exporter for tests - avoids TracerProvider override issues
_test_provider = None
_test_exporter = None


def _get_test_tracer_setup():
    """Get or create test tracer setup (singleton to avoid provider override)."""
    global _test_provider, _test_exporter
    if _test_provider is None:
        _test_provider = TracerProvider()
        _test_exporter = InMemorySpanExporter()
        _test_provider.add_span_processor(SimpleSpanProcessor(_test_exporter))
        trace.set_tracer_provider(_test_provider)
    return _test_provider, _test_exporter


class TestTraceHierarchy:
    """Tests for proper span parent-child relationships."""

    @pytest.fixture
    def tracer_provider(self):
        """Create test tracer provider with in-memory exporter."""
        provider, exporter = _get_test_tracer_setup()
        exporter.clear()  # Clear any previous spans
        yield provider, exporter
        exporter.clear()

    def test_nested_spans_have_correct_parent_child(self, tracer_provider):
        """Test that nested spans form correct hierarchy."""
        provider, exporter = tracer_provider
        tracer = trace.get_tracer("test")

        with tracer.start_as_current_span("parent") as parent_span:
            with tracer.start_as_current_span("child") as child_span:
                pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 2

        child = next(s for s in spans if s.name == "child")
        parent = next(s for s in spans if s.name == "parent")

        # Child's parent should be parent's span_id
        assert child.parent.span_id == parent.context.span_id

    def test_span_names_class_values(self):
        """Test SpanNames has expected values for hierarchy."""
        from shared.observability.otel.span_names import SpanNames

        # Verify hierarchy levels exist
        assert "orchestrator" in SpanNames.ORCHESTRATOR_QUERY
        assert "retrieval" in SpanNames.RETRIEVAL_SEARCH
        assert "qdrant" in SpanNames.QDRANT_QUERY
        assert "opensearch" in SpanNames.OPENSEARCH_QUERY

    @pytest.mark.asyncio
    async def test_traced_client_creates_child_span(self, tracer_provider):
        """Test TracedQdrantClient creates span as child of current."""
        provider, exporter = tracer_provider

        with patch("qdrant_client.AsyncQdrantClient"):
            from shared.observability.clients.traced_qdrant import TracedQdrantClient

            mock_client = MagicMock()

            # Create async mock that returns immediately
            async def mock_query(*args, **kwargs):
                return MagicMock(points=[])

            mock_client.query_points = mock_query

            traced = TracedQdrantClient(mock_client, "test_collection")

            # Create parent span and call traced client
            tracer = trace.get_tracer("test")
            with tracer.start_as_current_span("parent_operation"):
                await traced.query_points(query=[0.1, 0.2], limit=10)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "parent_operation" in span_names
        assert "qdrant.query.search" in span_names

        # Verify parent-child relationship
        qdrant_span = next(s for s in spans if s.name == "qdrant.query.search")
        parent_span = next(s for s in spans if s.name == "parent_operation")
        assert qdrant_span.parent.span_id == parent_span.context.span_id
