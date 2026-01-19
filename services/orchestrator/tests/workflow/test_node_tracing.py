"""Tests for tracing instrumentation on workflow nodes."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared.observability.otel.span_names import SpanNames
from workflow.nodes import retrieval_node, routing_node, generation_node
from workflow.state import create_initial_state


# Module-level span exporter to avoid TracerProvider override issues
_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))


@pytest.fixture(scope="module", autouse=True)
def setup_tracer_provider():
    """Set up the tracer provider once for the module."""
    trace.set_tracer_provider(_provider)
    yield
    _exporter.clear()


@pytest.fixture(autouse=True)
def clear_spans():
    """Clear spans before each test."""
    _exporter.clear()
    yield


class TestRetrievalNodeTracing:
    """Tests for tracing in retrieval_node."""

    @pytest.mark.asyncio
    async def test_retrieval_node_creates_span_with_correct_name(self):
        """Test that retrieval_node creates a span with the correct name."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
            tenant_id="tenant-123",
        )

        # Mock the httpx client to avoid actual HTTP calls
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "content": "Python is a programming language.",
                    "score": 0.95,
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "metadata": {"source_uri": "https://example.com/python"},
                }
            ],
            "degradation_mode": "hybrid_full",
            "components_used": ["semantic", "keyword"],
            "components_skipped": [],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await retrieval_node(state)

        # Verify span was created
        spans = _exporter.get_finished_spans()
        assert len(spans) >= 1

        # Find the retrieval span
        retrieval_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_RETRIEVAL]
        assert len(retrieval_spans) == 1

        retrieval_span = retrieval_spans[0]
        assert retrieval_span.name == SpanNames.ORCHESTRATOR_RETRIEVAL

    @pytest.mark.asyncio
    async def test_retrieval_node_sets_span_attributes(self):
        """Test that retrieval_node sets expected span attributes."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python programming?",
            tenant_id="tenant-456",
        )

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "content": "Python is a high-level programming language.",
                    "score": 0.92,
                    "chunk_id": "chunk-2",
                    "document_id": "doc-2",
                    "metadata": {},
                }
            ],
            "degradation_mode": "hybrid_full",
            "components_used": ["semantic", "keyword"],
            "components_skipped": [],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("workflow.nodes.retrieval.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await retrieval_node(state)

        spans = _exporter.get_finished_spans()
        retrieval_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_RETRIEVAL]
        assert len(retrieval_spans) == 1

        retrieval_span = retrieval_spans[0]
        attributes = dict(retrieval_span.attributes)

        # Check expected attributes
        assert "orchestrator.query_length" in attributes
        assert attributes["orchestrator.query_length"] == len("What is Python programming?")
        assert "orchestrator.tenant_id" in attributes
        assert attributes["orchestrator.tenant_id"] == "tenant-456"
        assert "orchestrator.documents_retrieved" in attributes
        assert attributes["orchestrator.documents_retrieved"] == 1
        assert "orchestrator.context_quality" in attributes
        assert attributes["orchestrator.context_quality"] == "full"


class TestRoutingNodeTracing:
    """Tests for tracing in routing_node."""

    @pytest.mark.asyncio
    async def test_routing_node_creates_span_with_correct_name(self):
        """Test that routing_node creates a span with the correct name."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
            tenant_id="tenant-123",
        )

        result = await routing_node(state)

        spans = _exporter.get_finished_spans()
        routing_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_ROUTING]
        assert len(routing_spans) == 1

        routing_span = routing_spans[0]
        assert routing_span.name == SpanNames.ORCHESTRATOR_ROUTING

    @pytest.mark.asyncio
    async def test_routing_node_sets_strategy_attribute(self):
        """Test that routing_node sets the strategy attribute."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and JavaScript",
            tenant_id="tenant-789",
        )

        result = await routing_node(state)

        spans = _exporter.get_finished_spans()
        routing_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_ROUTING]
        assert len(routing_spans) == 1

        routing_span = routing_spans[0]
        attributes = dict(routing_span.attributes)

        assert "orchestrator.strategy" in attributes
        assert attributes["orchestrator.strategy"] == "complex"  # "compare" triggers complex


class TestGenerationNodeTracing:
    """Tests for tracing in generation_node."""

    @pytest.fixture
    def mock_llm_response(self):
        """Create a mock LLM response."""
        from datetime import UTC, datetime

        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": int(datetime.now(tz=UTC).timestamp()),
            "model": "meta-llama/Llama-3.1-8B-Instruct",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "This is a test response."},
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        }

    @pytest.mark.asyncio
    async def test_generation_node_creates_span_with_correct_name(self, mock_llm_response):
        """Test that generation_node creates a span with the correct name."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
            tenant_id="tenant-123",
        )
        state["messages"] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is Python?"},
        ]
        state["strategy"] = "simple"

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_llm_response
        mock_response.raise_for_status = MagicMock()

        with patch("workflow.nodes.generation.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await generation_node(state)

        spans = _exporter.get_finished_spans()
        generation_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_GENERATION]
        assert len(generation_spans) == 1

        generation_span = generation_spans[0]
        assert generation_span.name == SpanNames.ORCHESTRATOR_GENERATION

    @pytest.mark.asyncio
    async def test_generation_node_sets_tokens_attribute(self, mock_llm_response):
        """Test that generation_node sets the tokens_used attribute."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
            tenant_id="tenant-456",
        )
        state["messages"] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is Python?"},
        ]
        state["strategy"] = "simple"

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_llm_response
        mock_response.raise_for_status = MagicMock()

        with patch("workflow.nodes.generation.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await generation_node(state)

        spans = _exporter.get_finished_spans()
        generation_spans = [s for s in spans if s.name == SpanNames.ORCHESTRATOR_GENERATION]
        assert len(generation_spans) == 1

        generation_span = generation_spans[0]
        attributes = dict(generation_span.attributes)

        assert "orchestrator.tokens_used" in attributes
        assert attributes["orchestrator.tokens_used"] == 18  # From mock_llm_response
        assert "orchestrator.model" in attributes
