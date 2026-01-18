"""Tests for retrieval quality fields in RAGState."""

import typing

import pytest
from workflow.state import RAGState, create_initial_state


class TestRAGStateRetrievalQuality:
    """Tests for retrieval quality tracking in state."""

    def test_state_has_retrieval_quality_field(self):
        """RAGState should have retrieval_quality field."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test",
            "retrieval_quality": {
                "degradation_level": "normal",
                "mode": "hybrid_full",
                "components_used": ["qdrant", "opensearch", "reranker"],
                "components_skipped": [],
            },
        }
        assert state["retrieval_quality"]["degradation_level"] == "normal"

    def test_state_has_context_quality_field(self):
        """RAGState should have context_quality field."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test",
            "context_quality": "full",
        }
        assert state["context_quality"] == "full"

    def test_context_quality_values(self):
        """context_quality should accept full, partial, minimal."""
        for quality in ["full", "partial", "minimal"]:
            state: RAGState = {
                "request_id": "test-123",
                "query": "test",
                "context_quality": quality,
            }
            assert state["context_quality"] == quality

    def test_create_initial_state_defaults(self):
        """create_initial_state should set default retrieval quality."""
        state = create_initial_state(
            request_id="test-123",
            query="test query",
        )
        # Should not have retrieval_quality until retrieval runs
        assert "retrieval_quality" not in state or state.get("retrieval_quality") is None

    def test_retrieval_quality_mode_values(self):
        """retrieval_quality mode should accept various degradation modes."""
        modes = [
            "hybrid_full",
            "semantic_only",
            "keyword_only",
            "cache_only",
            "unavailable",
        ]
        for mode in modes:
            state: RAGState = {
                "request_id": "test-123",
                "query": "test",
                "retrieval_quality": {
                    "degradation_level": "normal",
                    "mode": mode,
                    "components_used": [],
                    "components_skipped": [],
                },
            }
            assert state["retrieval_quality"]["mode"] == mode

    def test_retrieval_quality_degradation_levels(self):
        """retrieval_quality degradation_level should accept expected values."""
        levels = ["normal", "degraded", "minimal", "unavailable"]
        for level in levels:
            state: RAGState = {
                "request_id": "test-123",
                "query": "test",
                "retrieval_quality": {
                    "degradation_level": level,
                    "mode": "hybrid_full",
                    "components_used": [],
                    "components_skipped": [],
                },
            }
            assert state["retrieval_quality"]["degradation_level"] == level

    def test_retrieval_quality_tracks_components(self):
        """retrieval_quality should track used and skipped components."""
        state: RAGState = {
            "request_id": "test-123",
            "query": "test",
            "retrieval_quality": {
                "degradation_level": "degraded",
                "mode": "semantic_only",
                "components_used": ["qdrant"],
                "components_skipped": ["opensearch", "reranker"],
            },
        }
        assert state["retrieval_quality"]["components_used"] == ["qdrant"]
        assert state["retrieval_quality"]["components_skipped"] == ["opensearch", "reranker"]

    def test_retrieval_quality_in_type_annotations(self):
        """retrieval_quality should be defined in RAGState type annotations."""
        type_hints = typing.get_type_hints(RAGState)
        assert "retrieval_quality" in type_hints
        assert type_hints["retrieval_quality"] == dict

    def test_context_quality_in_type_annotations(self):
        """context_quality should be defined in RAGState type annotations."""
        type_hints = typing.get_type_hints(RAGState)
        assert "context_quality" in type_hints
        assert type_hints["context_quality"] == str
