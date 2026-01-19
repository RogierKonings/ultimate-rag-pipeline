"""Tests for span naming conventions."""

import pytest


class TestSpanNames:
    """Tests for SpanNames constants."""

    def test_qdrant_span_names_follow_convention(self):
        """Test Qdrant span names follow {service}.{component}.{operation} pattern."""
        from shared.observability.otel.span_names import SpanNames

        assert SpanNames.QDRANT_QUERY == "qdrant.query.search"
        assert SpanNames.QDRANT_UPSERT == "qdrant.mutation.upsert"

    def test_opensearch_span_names_follow_convention(self):
        """Test OpenSearch span names follow convention."""
        from shared.observability.otel.span_names import SpanNames

        assert SpanNames.OPENSEARCH_QUERY == "opensearch.query.search"
        assert SpanNames.OPENSEARCH_INDEX == "opensearch.mutation.index"

    def test_retrieval_span_names_follow_convention(self):
        """Test retrieval span names follow convention."""
        from shared.observability.otel.span_names import SpanNames

        assert SpanNames.RETRIEVAL_SEARCH == "retrieval.search.hybrid"
        assert SpanNames.RETRIEVAL_PREPROCESS == "retrieval.preprocess.query"
        assert SpanNames.RETRIEVAL_EMBED_QUERY == "retrieval.embed.query"
        assert SpanNames.RETRIEVAL_SEMANTIC == "retrieval.search.semantic"
        assert SpanNames.RETRIEVAL_KEYWORD == "retrieval.search.keyword"
        assert SpanNames.RETRIEVAL_FUSION == "retrieval.fusion.rrf"
        assert SpanNames.RETRIEVAL_RERANK == "retrieval.rerank.crossencoder"

    def test_orchestrator_span_names_follow_convention(self):
        """Test orchestrator span names follow convention."""
        from shared.observability.otel.span_names import SpanNames

        assert SpanNames.ORCHESTRATOR_QUERY == "orchestrator.query.process"
        assert SpanNames.ORCHESTRATOR_ROUTING == "orchestrator.workflow.routing"
        assert SpanNames.ORCHESTRATOR_RETRIEVAL == "orchestrator.workflow.retrieval"
        assert SpanNames.ORCHESTRATOR_PROMPT == "orchestrator.workflow.prompt_building"
        assert SpanNames.ORCHESTRATOR_GENERATION == "orchestrator.workflow.generation"
        assert SpanNames.ORCHESTRATOR_VALIDATION == "orchestrator.workflow.validation"

    def test_all_span_names_are_strings(self):
        """Test all span names are non-empty strings."""
        from shared.observability.otel.span_names import SpanNames

        for attr_name in dir(SpanNames):
            if attr_name.isupper() and not attr_name.startswith("_"):
                value = getattr(SpanNames, attr_name)
                assert isinstance(value, str), f"{attr_name} should be a string"
                assert len(value) > 0, f"{attr_name} should not be empty"
                assert "." in value, f"{attr_name} should follow dotted convention"
