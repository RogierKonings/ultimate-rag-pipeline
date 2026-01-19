"""Integration tests for trace hierarchy."""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


class TestTraceHierarchy:
    """Tests for proper span parent-child relationships."""

    @pytest.fixture
    def tracer_with_exporter(self):
        """Create a fresh tracer provider with in-memory exporter for this test.

        Uses a fresh TracerProvider with its own exporter, getting a tracer
        directly from it rather than relying on the global provider.
        """
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test")
        yield provider, tracer, exporter
        exporter.clear()

    def test_nested_spans_have_correct_parent_child(self, tracer_with_exporter):
        """Test that nested spans form correct hierarchy."""
        provider, tracer, exporter = tracer_with_exporter

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
    async def test_traced_client_creates_child_span(self, tracer_with_exporter):
        """Test TracedQdrantClient creates span as child of current."""
        provider, tracer, exporter = tracer_with_exporter

        # Set this provider as global for the duration of the test
        # so that TracedQdrantClient uses it
        original_provider = trace.get_tracer_provider()
        trace.set_tracer_provider(provider)

        try:
            with patch("qdrant_client.AsyncQdrantClient"):
                from shared.observability.clients.traced_qdrant import TracedQdrantClient

                mock_client = MagicMock()

                # Create async mock that returns immediately
                async def mock_query(*args, **kwargs):
                    return MagicMock(points=[])

                mock_client.query_points = mock_query

                traced = TracedQdrantClient(mock_client, "test_collection")

                # Create parent span and call traced client
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
        finally:
            # Restore original provider (if possible - may fail if already set)
            try:
                trace.set_tracer_provider(original_provider)
            except Exception:
                pass  # Ignore if we can't reset
