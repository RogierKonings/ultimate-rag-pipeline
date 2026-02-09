"""Tests for degradation handling in retrieval node."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from workflow.nodes.retrieval import retrieval_node
from workflow.state import RAGState


@pytest.fixture
def mock_httpx_response_normal():
    """Mock response with normal degradation."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.9, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "hybrid_full",
        "components_used": ["qdrant", "opensearch", "reranker"],
        "components_skipped": [],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_degraded():
    """Mock response with degraded mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.8, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "semantic_only",
        "components_used": ["qdrant", "reranker"],
        "components_skipped": ["opensearch"],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_minimal():
    """Mock response with minimal mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.7, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "minimal",
        "components_used": ["qdrant"],
        "components_skipped": ["opensearch", "reranker"],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_keyword_only():
    """Mock response with keyword_only degraded mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.75, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "keyword_only",
        "components_used": ["opensearch", "reranker"],
        "components_skipped": ["qdrant"],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_hybrid_no_rerank():
    """Mock response with hybrid_no_rerank degraded mode."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.85, "chunk_id": "1", "document_id": "doc1"}],
        "degradation_mode": "hybrid_no_rerank",
        "components_used": ["qdrant", "opensearch"],
        "components_skipped": ["reranker"],
    }
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def mock_httpx_response_no_degradation_fields():
    """Mock response without degradation fields (backward compatibility)."""
    response = MagicMock()
    response.json.return_value = {
        "results": [{"content": "test", "score": 0.9, "chunk_id": "1", "document_id": "doc1"}],
    }
    response.raise_for_status = MagicMock()
    return response


class TestRetrievalNodeDegradation:
    """Tests for degradation handling in retrieval node."""

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_normal_degradation(self, mock_httpx_response_normal):
        """Retrieval node should parse normal degradation info."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_normal
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "normal"
        assert result["retrieval_quality"]["mode"] == "hybrid_full"
        assert "qdrant" in result["retrieval_quality"]["components_used"]
        assert "opensearch" in result["retrieval_quality"]["components_used"]
        assert "reranker" in result["retrieval_quality"]["components_used"]
        assert result["retrieval_quality"]["components_skipped"] == []
        assert result["context_quality"] == "full"
        # No fallback should be recorded for normal mode
        assert "retrieval:hybrid_full" not in result.get("fallbacks_used", [])

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_degraded_mode(self, mock_httpx_response_degraded):
        """Retrieval node should parse degraded mode and track fallback."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_degraded
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "degraded"
        assert result["retrieval_quality"]["mode"] == "semantic_only"
        assert "qdrant" in result["retrieval_quality"]["components_used"]
        assert "opensearch" in result["retrieval_quality"]["components_skipped"]
        assert result["context_quality"] == "partial"
        assert "retrieval:semantic_only" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_minimal_mode(self, mock_httpx_response_minimal):
        """Retrieval node should parse minimal mode."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_minimal
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "minimal"
        assert result["retrieval_quality"]["mode"] == "minimal"
        assert result["context_quality"] == "minimal"
        assert "retrieval:minimal" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_keyword_only_mode(self, mock_httpx_response_keyword_only):
        """Retrieval node should parse keyword_only as degraded."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_keyword_only
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "degraded"
        assert result["retrieval_quality"]["mode"] == "keyword_only"
        assert result["context_quality"] == "partial"
        assert "retrieval:keyword_only" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_parses_hybrid_no_rerank_mode(
        self, mock_httpx_response_hybrid_no_rerank
    ):
        """Retrieval node should parse hybrid_no_rerank as degraded."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_hybrid_no_rerank
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "degraded"
        assert result["retrieval_quality"]["mode"] == "hybrid_no_rerank"
        assert "reranker" in result["retrieval_quality"]["components_skipped"]
        assert result["context_quality"] == "partial"
        assert "retrieval:hybrid_no_rerank" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_handles_missing_degradation_fields(
        self, mock_httpx_response_no_degradation_fields
    ):
        """Retrieval node should handle missing degradation fields gracefully."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_no_degradation_fields
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        # Should default to normal mode when fields are missing
        assert result["retrieval_quality"]["degradation_level"] == "normal"
        assert result["retrieval_quality"]["mode"] == "hybrid_full"
        assert result["retrieval_quality"]["components_used"] == []
        assert result["retrieval_quality"]["components_skipped"] == []
        assert result["context_quality"] == "full"

    @pytest.mark.asyncio
    async def test_retrieval_node_sets_defaults_on_error(self):
        """Retrieval node should set sensible defaults when retrieval fails."""
        state: RAGState = {"request_id": "test-123", "query": "test query", "timing": {}}

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.ConnectError("Connection refused")
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert result["retrieval_quality"]["degradation_level"] == "unknown"
        assert result["retrieval_quality"]["mode"] == "unknown"
        assert result["retrieval_quality"]["components_used"] == []
        assert result["retrieval_quality"]["components_skipped"] == []
        assert result["context_quality"] == "minimal"

    @pytest.mark.asyncio
    async def test_retrieval_node_preserves_existing_fallbacks(self, mock_httpx_response_degraded):
        """Retrieval node should preserve existing fallbacks and add new ones."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test query",
            "timing": {},
            "fallbacks_used": ["previous_fallback"],
        }

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_degraded
            mock_get_client.return_value = mock_instance

            result = await retrieval_node(state)

        assert "previous_fallback" in result["fallbacks_used"]
        assert "retrieval:semantic_only" in result["fallbacks_used"]

    @pytest.mark.asyncio
    async def test_retrieval_node_rerank_default_disabled_for_simple(
        self, mock_httpx_response_normal
    ):
        """Simple strategy should keep rerank disabled by default."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "what is python",
            "strategy": "simple",
            "intent": "FACTUAL",
            "timing": {},
        }

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_normal
            mock_get_client.return_value = mock_instance

            await retrieval_node(state)

        payload = mock_instance.post.call_args.kwargs["json"]
        assert payload["rerank"] is False

    @pytest.mark.asyncio
    async def test_retrieval_node_rerank_enabled_for_comparison_strategy(
        self, mock_httpx_response_normal
    ):
        """Comparison strategy should enable rerank unless overridden."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "compare python and java",
            "strategy": "comparison",
            "intent": "ANALYTICAL",
            "timing": {},
        }

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_normal
            mock_get_client.return_value = mock_instance

            await retrieval_node(state)

        payload = mock_instance.post.call_args.kwargs["json"]
        assert payload["rerank"] is True

    @pytest.mark.asyncio
    async def test_retrieval_node_rerank_override_respected(self, mock_httpx_response_normal):
        """Explicit rerank option should override strategy-based default."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "compare python and java",
            "strategy": "comparison",
            "intent": "ANALYTICAL",
            "options": {"rerank": False},
            "timing": {},
        }

        with patch("workflow.nodes.retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_httpx_response_normal
            mock_get_client.return_value = mock_instance

            await retrieval_node(state)

        payload = mock_instance.post.call_args.kwargs["json"]
        assert payload["rerank"] is False
