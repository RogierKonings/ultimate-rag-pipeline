"""Tests for degradation disclaimers in prompt building."""

import pytest
from workflow.nodes.prompt_building import (
    DEGRADATION_DISCLAIMERS,
    _build_messages,
    prompt_building_node,
)


class TestDegradationDisclaimers:
    """Tests for DEGRADATION_DISCLAIMERS constant."""

    def test_degradation_disclaimers_defined(self):
        """DEGRADATION_DISCLAIMERS should be defined for all degradation modes."""
        assert "semantic_only" in DEGRADATION_DISCLAIMERS
        assert "keyword_only" in DEGRADATION_DISCLAIMERS
        assert "hybrid_no_rerank" in DEGRADATION_DISCLAIMERS
        assert "minimal" in DEGRADATION_DISCLAIMERS

    def test_disclaimers_are_non_empty_strings(self):
        """Each disclaimer should be a non-empty string."""
        for mode, disclaimer in DEGRADATION_DISCLAIMERS.items():
            assert isinstance(disclaimer, str), f"Disclaimer for {mode} is not a string"
            assert len(disclaimer) > 0, f"Disclaimer for {mode} is empty"

    def test_minimal_disclaimer_has_strong_warning(self):
        """Minimal mode disclaimer should have strong warning language."""
        disclaimer = DEGRADATION_DISCLAIMERS["minimal"].lower()
        assert "significantly degraded" in disclaimer or "important" in disclaimer.lower()


class TestBuildMessagesWithDegradation:
    """Tests for _build_messages function with degradation handling."""

    def test_no_disclaimer_when_retrieval_quality_is_none(self):
        """No disclaimer should be added when retrieval_quality is None."""
        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=None,
        )

        system_content = messages[0]["content"]
        assert "unavailable" not in system_content.lower()
        assert "degraded" not in system_content.lower()

    def test_no_disclaimer_when_normal_degradation(self):
        """No disclaimer should be added for normal (hybrid_full) mode."""
        retrieval_quality = {
            "degradation_level": "normal",
            "mode": "hybrid_full",
            "components_used": ["qdrant", "opensearch", "reranker"],
            "components_skipped": [],
        }

        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=retrieval_quality,
        )

        system_content = messages[0]["content"]
        assert "unavailable" not in system_content.lower()
        assert "degraded" not in system_content.lower()

    def test_semantic_only_disclaimer_included(self):
        """Semantic only mode should include keyword unavailable disclaimer."""
        retrieval_quality = {
            "degradation_level": "degraded",
            "mode": "semantic_only",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch"],
        }

        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=retrieval_quality,
        )

        system_content = messages[0]["content"]
        assert "keyword" in system_content.lower()
        assert "unavailable" in system_content.lower()

    def test_keyword_only_disclaimer_included(self):
        """Keyword only mode should include semantic unavailable disclaimer."""
        retrieval_quality = {
            "degradation_level": "degraded",
            "mode": "keyword_only",
            "components_used": ["opensearch"],
            "components_skipped": ["qdrant"],
        }

        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=retrieval_quality,
        )

        system_content = messages[0]["content"]
        assert "semantic" in system_content.lower()
        assert "unavailable" in system_content.lower()

    def test_hybrid_no_rerank_disclaimer_included(self):
        """Hybrid no rerank mode should include reranking disclaimer."""
        retrieval_quality = {
            "degradation_level": "degraded",
            "mode": "hybrid_no_rerank",
            "components_used": ["qdrant", "opensearch"],
            "components_skipped": ["reranker"],
        }

        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=retrieval_quality,
        )

        system_content = messages[0]["content"]
        assert "rerank" in system_content.lower()

    def test_minimal_disclaimer_included(self):
        """Minimal mode should include strong warning disclaimer."""
        retrieval_quality = {
            "degradation_level": "minimal",
            "mode": "minimal",
            "components_used": ["qdrant"],
            "components_skipped": ["opensearch", "reranker"],
        }

        messages = _build_messages(
            query="test query",
            context="test context",
            strategy="simple",
            retrieval_quality=retrieval_quality,
        )

        system_content = messages[0]["content"]
        # Check for strong warning language
        assert (
            "significantly degraded" in system_content.lower()
            or "incomplete" in system_content.lower()
        )


class TestPromptBuildingNode:
    """Tests for prompt_building_node with degradation handling."""

    @pytest.mark.asyncio
    async def test_prompt_building_node_passes_retrieval_quality(self):
        """prompt_building_node should pass retrieval_quality to _build_messages."""
        state = {
            "request_id": "test-123",
            "query": "test query",
            "context": "test context",
            "strategy": "simple",
            "timing": {},
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "semantic_only",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch"],
            },
        }

        result = await prompt_building_node(state)

        # Verify disclaimer is in the system message
        system_content = result["messages"][0]["content"]
        assert "keyword" in system_content.lower()
        assert "unavailable" in system_content.lower()

    @pytest.mark.asyncio
    async def test_prompt_building_node_no_retrieval_quality(self):
        """prompt_building_node should handle missing retrieval_quality."""
        state = {
            "request_id": "test-123",
            "query": "test query",
            "context": "test context",
            "strategy": "simple",
            "timing": {},
            # No retrieval_quality field
        }

        result = await prompt_building_node(state)

        # Should not crash and should not include disclaimer
        system_content = result["messages"][0]["content"]
        assert "unavailable" not in system_content.lower()
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_prompt_building_node_preserves_state(self):
        """prompt_building_node should preserve existing state fields."""
        state = {
            "request_id": "test-123",
            "query": "test query",
            "context": "test context",
            "strategy": "simple",
            "timing": {},
            "documents": [{"id": "doc-1"}],
            "retrieval_quality": {
                "degradation_level": "normal",
                "mode": "hybrid_full",
                "components_used": ["qdrant", "opensearch"],
                "components_skipped": [],
            },
        }

        result = await prompt_building_node(state)

        # Verify original fields are preserved
        assert result["request_id"] == "test-123"
        assert result["query"] == "test query"
        assert result["documents"] == [{"id": "doc-1"}]
        assert "timing" in result
        assert "prompt_building" in result["timing"]
