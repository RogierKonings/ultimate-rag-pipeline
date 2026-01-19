"""Integration tests for end-to-end degradation flow (US-10.2.2).

These tests verify that degradation information propagates correctly
through the entire RAG workflow: retrieval → prompt building → response.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workflow.nodes.retrieval import retrieval_node
from workflow.nodes.prompt_building import prompt_building_node, DEGRADATION_DISCLAIMERS


def create_mock_httpx_response(data: dict) -> MagicMock:
    """Create a mock httpx response with the given JSON data."""
    response = MagicMock()
    response.json.return_value = data
    response.raise_for_status = MagicMock()
    return response


def create_mock_httpx_client(response: MagicMock) -> MagicMock:
    """Create a mock httpx AsyncClient."""
    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    mock_instance.post.return_value = response
    return mock_instance


class TestDegradationFlowIntegration:
    """Integration tests for degradation info flow through workflow."""

    @pytest.mark.asyncio
    async def test_semantic_only_degradation_flow(self):
        """Test semantic_only degradation flows through entire workflow.

        Simulates OpenSearch being unavailable, resulting in:
        1. Retrieval returns semantic_only mode
        2. Retrieval node parses degradation and sets retrieval_quality
        3. Prompt building adds appropriate disclaimer
        """
        # Mock response from retrieval service
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Python is a programming language.", "score": 0.9, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        # Initial state
        state = {
            "request_id": "test-123",
            "query": "What is Python?",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        # Step 1: Run retrieval node
        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        # Verify retrieval_quality is set
        assert "retrieval_quality" in retrieval_result
        assert retrieval_result["retrieval_quality"]["mode"] == "semantic_only"
        assert retrieval_result["retrieval_quality"]["degradation_level"] == "degraded"
        assert retrieval_result["context_quality"] == "partial"
        assert "opensearch" in retrieval_result["retrieval_quality"]["components_skipped"]

        # Step 2: Run prompt building node with retrieval results
        prompt_state = {
            **retrieval_result,
            "context": "Python is a programming language.",
        }
        prompt_result = await prompt_building_node(prompt_state)

        # Verify system message contains semantic_only disclaimer
        system_content = prompt_result["messages"][0]["content"]
        assert "keyword" in system_content.lower()
        assert "unavailable" in system_content.lower()

    @pytest.mark.asyncio
    async def test_keyword_only_degradation_flow(self):
        """Test keyword_only degradation flows through entire workflow.

        Simulates Qdrant being unavailable, resulting in:
        1. Retrieval returns keyword_only mode
        2. Retrieval node parses degradation and sets retrieval_quality
        3. Prompt building adds appropriate disclaimer
        """
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Python tutorial content.", "score": 0.85, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "keyword_only",
            "components_used": ["opensearch"],
            "components_skipped": ["qdrant"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-456",
            "query": "Python tutorial",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        assert retrieval_result["retrieval_quality"]["mode"] == "keyword_only"
        assert retrieval_result["retrieval_quality"]["degradation_level"] == "degraded"

        prompt_state = {
            **retrieval_result,
            "context": "Keyword matched content",
        }
        prompt_result = await prompt_building_node(prompt_state)

        system_content = prompt_result["messages"][0]["content"]
        assert "semantic" in system_content.lower()
        assert "unavailable" in system_content.lower()

    @pytest.mark.asyncio
    async def test_minimal_degradation_flow(self):
        """Test minimal degradation flows through entire workflow.

        Simulates severe degradation with strong warning.
        """
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Limited content.", "score": 0.5, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "minimal",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch", "reranker"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-789",
            "query": "Important question",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        assert retrieval_result["retrieval_quality"]["mode"] == "minimal"
        assert retrieval_result["retrieval_quality"]["degradation_level"] == "minimal"
        assert retrieval_result["context_quality"] == "minimal"

        prompt_state = {
            **retrieval_result,
            "context": "Minimal context",
        }
        prompt_result = await prompt_building_node(prompt_state)

        system_content = prompt_result["messages"][0]["content"]
        # Check for strong warning language
        assert "significantly degraded" in system_content.lower() or "incomplete" in system_content.lower()

    @pytest.mark.asyncio
    async def test_normal_operation_no_disclaimer(self):
        """Test that normal operation doesn't add disclaimers.

        When all components are available, no degradation disclaimer
        should be added to the prompt.
        """
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Full content from hybrid search.", "score": 0.95, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "hybrid_full",
            "components_used": ["qdrant", "opensearch", "reranker"],
            "components_skipped": [],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-normal",
            "query": "Normal query",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        assert retrieval_result["retrieval_quality"]["mode"] == "hybrid_full"
        assert retrieval_result["retrieval_quality"]["degradation_level"] == "normal"
        assert retrieval_result["context_quality"] == "full"

        prompt_state = {
            **retrieval_result,
            "context": "Full hybrid search context",
        }
        prompt_result = await prompt_building_node(prompt_state)

        system_content = prompt_result["messages"][0]["content"]
        # Should NOT contain any degradation disclaimers
        for mode, disclaimer in DEGRADATION_DISCLAIMERS.items():
            assert disclaimer.strip() not in system_content

    @pytest.mark.asyncio
    async def test_hybrid_no_rerank_degradation_flow(self):
        """Test hybrid_no_rerank degradation flows correctly."""
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Content without reranking.", "score": 0.8, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "hybrid_no_rerank",
            "components_used": ["qdrant", "opensearch"],
            "components_skipped": ["reranker"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-rerank",
            "query": "Query needing ranking",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        assert retrieval_result["retrieval_quality"]["mode"] == "hybrid_no_rerank"
        assert retrieval_result["retrieval_quality"]["degradation_level"] == "degraded"

        prompt_state = {
            **retrieval_result,
            "context": "Unranked context",
        }
        prompt_result = await prompt_building_node(prompt_state)

        system_content = prompt_result["messages"][0]["content"]
        assert "rerank" in system_content.lower()


class TestDegradationStatePreservation:
    """Tests for state preservation through workflow."""

    @pytest.mark.asyncio
    async def test_retrieval_quality_preserved_through_nodes(self):
        """Test that retrieval_quality is preserved through multiple nodes."""
        initial_quality = {
            "degradation_level": "degraded",
            "mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        }

        state = {
            "request_id": "test-preserve",
            "query": "Test query",
            "context": "Test context",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": initial_quality,
        }

        # Run prompt building
        result = await prompt_building_node(state)

        # retrieval_quality should be preserved in output state
        assert result.get("retrieval_quality") == initial_quality

    @pytest.mark.asyncio
    async def test_context_quality_preserved_through_nodes(self):
        """Test that context_quality is preserved through nodes."""
        state = {
            "request_id": "test-context-quality",
            "query": "Test query",
            "context": "Test context",
            "strategy": "simple",
            "timing": {},
            "context_quality": "partial",
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "semantic_only",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch"],
            },
        }

        result = await prompt_building_node(state)

        # Original state values should be preserved
        assert result.get("context_quality") == "partial"

    @pytest.mark.asyncio
    async def test_fallbacks_used_accumulated(self):
        """Test that fallbacks_used list is accumulated correctly."""
        mock_response = create_mock_httpx_response({
            "results": [],
            "degradation_mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-fallbacks",
            "query": "Test query",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": ["initial_fallback"],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            result = await retrieval_node(state)

        # Should have accumulated fallbacks
        assert "initial_fallback" in result.get("fallbacks_used", [])
        # New degradation-related fallback should be added
        assert "retrieval:semantic_only" in result.get("fallbacks_used", [])


class TestDegradationEdgeCases:
    """Tests for edge cases in degradation handling."""

    @pytest.mark.asyncio
    async def test_missing_degradation_mode_defaults(self):
        """Test handling when retrieval doesn't return degradation_mode."""
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Content", "score": 0.9, "chunk_id": "1", "document_id": "doc1"}
            ],
            # No degradation_mode field - old format
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-missing",
            "query": "Test query",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            result = await retrieval_node(state)

        # Should default to hybrid_full / normal
        assert result.get("retrieval_quality", {}).get("mode", "hybrid_full") == "hybrid_full"
        assert result.get("context_quality", "full") == "full"

    @pytest.mark.asyncio
    async def test_empty_components_lists(self):
        """Test handling of empty component lists."""
        mock_response = create_mock_httpx_response({
            "results": [],
            "degradation_mode": "minimal",
            "components_used": [],
            "components_skipped": ["qdrant", "opensearch", "reranker"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-empty",
            "query": "Test query",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            result = await retrieval_node(state)

        # Should handle empty components_used
        assert result.get("retrieval_quality", {}).get("components_used", []) == []
        assert "context_quality" in result


class TestEndToEndDegradationMetadata:
    """Tests verifying degradation metadata flows to final response."""

    @pytest.mark.asyncio
    async def test_degradation_metadata_available_for_response(self):
        """Test that all degradation metadata is available for building final response."""
        mock_response = create_mock_httpx_response({
            "results": [
                {"content": "Test content", "score": 0.85, "chunk_id": "1", "document_id": "doc1"}
            ],
            "degradation_mode": "semantic_only",
            "components_used": ["qdrant", "reranker"],
            "components_skipped": ["opensearch"],
        })
        mock_client = create_mock_httpx_client(mock_response)

        state = {
            "request_id": "test-metadata",
            "query": "Test query",
            "tenant_id": "test-tenant",
            "strategy": "simple",
            "timing": {},
            "fallbacks_used": [],
        }

        with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
            retrieval_result = await retrieval_node(state)

        prompt_state = {
            **retrieval_result,
            "context": "Test context",
        }
        final_result = await prompt_building_node(prompt_state)

        # Verify all metadata needed for QueryResponse is present
        assert "retrieval_quality" in final_result
        assert "context_quality" in final_result
        assert "fallbacks_used" in final_result

        # Verify specific fields
        rq = final_result["retrieval_quality"]
        assert "mode" in rq
        assert "degradation_level" in rq
        assert "components_used" in rq
        assert "components_skipped" in rq

    @pytest.mark.asyncio
    async def test_complete_flow_with_all_degradation_modes(self):
        """Test complete flow through all degradation modes."""
        modes = [
            ("hybrid_full", "normal", "full"),
            ("semantic_only", "degraded", "partial"),
            ("keyword_only", "degraded", "partial"),
            ("hybrid_no_rerank", "degraded", "partial"),
            ("minimal", "minimal", "minimal"),
        ]

        for mode, expected_level, expected_quality in modes:
            mock_response = create_mock_httpx_response({
                "results": [{"content": "Test", "score": 0.8, "chunk_id": "1", "document_id": "doc1"}],
                "degradation_mode": mode,
                "components_used": ["qdrant"],
                "components_skipped": [],
            })
            mock_client = create_mock_httpx_client(mock_response)

            state = {
                "request_id": f"test-{mode}",
                "query": "Test",
                "tenant_id": "test-tenant",
                "strategy": "simple",
                "timing": {},
                "fallbacks_used": [],
            }

            with patch("workflow.nodes.retrieval.httpx.AsyncClient", return_value=mock_client):
                result = await retrieval_node(state)

            assert result["retrieval_quality"]["mode"] == mode, f"Mode mismatch for {mode}"
            assert result["retrieval_quality"]["degradation_level"] == expected_level, f"Level mismatch for {mode}"
            assert result["context_quality"] == expected_quality, f"Quality mismatch for {mode}"
