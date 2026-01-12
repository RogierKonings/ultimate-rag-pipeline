"""Tests for API schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from api.schemas.common import (
    ComponentHealth,
    ErrorResponse,
    HealthResponse,
    MetadataFilter,
    PaginationParams,
)
from api.schemas.retrieve import (
    ExplainResponse,
    MultiQueryRequest,
    RetrievedDocument,
    RetrieveRequest,
    RetrieveResponse,
    SearchMetrics,
    SearchMode,
)
from pydantic import ValidationError


class TestRetrieveRequest:
    """Tests for RetrieveRequest schema."""

    def test_minimal_request(self):
        """Test request with only required fields."""
        request = RetrieveRequest(query="test query")

        assert request.query == "test query"
        assert request.mode == SearchMode.HYBRID
        assert request.top_k == 10
        assert request.rerank is True
        assert request.semantic_weight == 0.7
        assert request.keyword_weight == 0.3

    def test_full_request(self):
        """Test request with all fields."""
        request = RetrieveRequest(
            query="machine learning",
            mode=SearchMode.SEMANTIC,
            top_k=20,
            semantic_weight=0.8,
            keyword_weight=0.2,
            rerank=False,
            rerank_top_k=30,
            filters={"source_type": "documentation"},
            min_score=0.5,
            include_metadata=False,
            include_highlights=False,
        )

        assert request.query == "machine learning"
        assert request.mode == SearchMode.SEMANTIC
        assert request.top_k == 20
        assert request.semantic_weight == 0.8
        assert request.rerank is False
        assert request.filters == {"source_type": "documentation"}
        assert request.min_score == 0.5

    def test_empty_query_rejected(self):
        """Test that empty query is rejected."""
        with pytest.raises(ValidationError):
            RetrieveRequest(query="")

    def test_query_max_length(self):
        """Test query max length validation."""
        long_query = "a" * 2001
        with pytest.raises(ValidationError):
            RetrieveRequest(query=long_query)

    def test_top_k_range(self):
        """Test top_k range validation."""
        # Valid range
        request = RetrieveRequest(query="test", top_k=1)
        assert request.top_k == 1

        request = RetrieveRequest(query="test", top_k=100)
        assert request.top_k == 100

        # Out of range
        with pytest.raises(ValidationError):
            RetrieveRequest(query="test", top_k=0)

        with pytest.raises(ValidationError):
            RetrieveRequest(query="test", top_k=101)

    def test_weight_range(self):
        """Test weight range validation."""
        # Valid range
        request = RetrieveRequest(query="test", semantic_weight=0.0)
        assert request.semantic_weight == 0.0

        request = RetrieveRequest(query="test", semantic_weight=1.0)
        assert request.semantic_weight == 1.0

        # Out of range
        with pytest.raises(ValidationError):
            RetrieveRequest(query="test", semantic_weight=-0.1)

        with pytest.raises(ValidationError):
            RetrieveRequest(query="test", semantic_weight=1.1)

    def test_search_modes(self):
        """Test all search modes."""
        for mode in SearchMode:
            request = RetrieveRequest(query="test", mode=mode)
            assert request.mode == mode


class TestMultiQueryRequest:
    """Tests for MultiQueryRequest schema."""

    def test_minimal_request(self):
        """Test request with only required fields."""
        request = MultiQueryRequest(queries=["query 1", "query 2"])

        assert request.queries == ["query 1", "query 2"]
        assert request.aggregation == "rrf"
        assert request.top_k == 10
        assert request.rerank is True

    def test_all_aggregation_methods(self):
        """Test all aggregation methods."""
        for agg in ["max", "avg", "rrf"]:
            request = MultiQueryRequest(queries=["test"], aggregation=agg)
            assert request.aggregation == agg

    def test_invalid_aggregation(self):
        """Test invalid aggregation method."""
        with pytest.raises(ValidationError):
            MultiQueryRequest(queries=["test"], aggregation="invalid")


class TestRetrievedDocument:
    """Tests for RetrievedDocument schema."""

    def test_minimal_document(self):
        """Test document with only required fields."""
        chunk_id = uuid4()
        doc_id = uuid4()

        doc = RetrievedDocument(
            chunk_id=chunk_id,
            document_id=doc_id,
            content="test content",
            score=0.85,
        )

        assert doc.chunk_id == chunk_id
        assert doc.document_id == doc_id
        assert doc.content == "test content"
        assert doc.score == 0.85
        assert doc.chunk_index == 0
        assert doc.total_chunks == 1

    def test_full_document(self):
        """Test document with all fields."""
        chunk_id = uuid4()
        doc_id = uuid4()
        now = datetime.now(tz=UTC)

        doc = RetrievedDocument(
            chunk_id=chunk_id,
            document_id=doc_id,
            content="test content",
            score=0.85,
            title="Test Document",
            source="docs/test.md",
            source_type="markdown",
            chunk_index=2,
            total_chunks=5,
            created_at=now,
            updated_at=now,
            semantic_score=0.9,
            keyword_score=0.7,
            rerank_score=0.88,
            metadata={"author": "test"},
            highlights=["test content"],
        )

        assert doc.title == "Test Document"
        assert doc.source == "docs/test.md"
        assert doc.semantic_score == 0.9
        assert doc.keyword_score == 0.7
        assert doc.rerank_score == 0.88

    def test_score_range(self):
        """Test score range validation."""
        chunk_id = uuid4()
        doc_id = uuid4()

        # Valid range
        doc = RetrievedDocument(
            chunk_id=chunk_id,
            document_id=doc_id,
            content="test",
            score=0.0,
        )
        assert doc.score == 0.0

        doc = RetrievedDocument(
            chunk_id=chunk_id,
            document_id=doc_id,
            content="test",
            score=1.0,
        )
        assert doc.score == 1.0


class TestSearchMetrics:
    """Tests for SearchMetrics schema."""

    def test_minimal_metrics(self):
        """Test metrics with only required fields."""
        metrics = SearchMetrics(total_ms=100.5)

        assert metrics.total_ms == 100.5
        assert metrics.query_preprocessing_ms == 0.0
        assert metrics.semantic_search_ms is None
        assert metrics.final_results_count == 0

    def test_full_metrics(self):
        """Test metrics with all fields."""
        metrics = SearchMetrics(
            query_preprocessing_ms=10.0,
            embedding_ms=15.0,
            semantic_search_ms=25.0,
            keyword_search_ms=20.0,
            fusion_ms=5.0,
            rerank_ms=50.0,
            total_ms=125.0,
            semantic_results_count=50,
            keyword_results_count=50,
            fused_results_count=40,
            final_results_count=10,
        )

        assert metrics.semantic_search_ms == 25.0
        assert metrics.keyword_search_ms == 20.0
        assert metrics.fused_results_count == 40


class TestRetrieveResponse:
    """Tests for RetrieveResponse schema."""

    def test_response_construction(self):
        """Test response construction."""
        chunk_id = uuid4()
        doc_id = uuid4()
        query_id = uuid4()

        response = RetrieveResponse(
            results=[
                RetrievedDocument(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    content="test content",
                    score=0.85,
                ),
            ],
            total_results=1,
            query="test query",
            mode=SearchMode.HYBRID,
            metrics=SearchMetrics(total_ms=100.0),
            query_id=query_id,
            processed_at=datetime.now(tz=UTC),
        )

        assert len(response.results) == 1
        assert response.total_results == 1
        assert response.mode == SearchMode.HYBRID
        assert response.query_id == query_id


class TestHealthResponse:
    """Tests for HealthResponse schema."""

    def test_healthy_status(self):
        """Test healthy status."""
        response = HealthResponse(
            status="healthy",
            version="1.0.0",
            components={"qdrant": True, "opensearch": True},
            timestamp=datetime.now(tz=UTC),
        )

        assert response.status == "healthy"
        assert response.components["qdrant"] is True

    def test_degraded_status(self):
        """Test degraded status."""
        response = HealthResponse(
            status="degraded",
            version="1.0.0",
            components={"qdrant": True, "opensearch": False},
            timestamp=datetime.now(tz=UTC),
        )

        assert response.status == "degraded"

    def test_unhealthy_status(self):
        """Test unhealthy status."""
        response = HealthResponse(
            status="unhealthy",
            version="1.0.0",
            components={"qdrant": False, "opensearch": False},
            timestamp=datetime.now(tz=UTC),
        )

        assert response.status == "unhealthy"


class TestCommonSchemas:
    """Tests for common schemas."""

    def test_error_response(self):
        """Test error response."""
        error = ErrorResponse(
            error="Not found",
            detail="Document not found",
            code="NOT_FOUND",
        )

        assert error.error == "Not found"
        assert error.detail == "Document not found"
        assert error.timestamp is not None

    def test_pagination_params(self):
        """Test pagination parameters."""
        params = PaginationParams(offset=10, limit=20)

        assert params.offset == 10
        assert params.limit == 20

    def test_pagination_defaults(self):
        """Test pagination defaults."""
        params = PaginationParams()

        assert params.offset == 0
        assert params.limit == 10

    def test_pagination_validation(self):
        """Test pagination validation."""
        with pytest.raises(ValidationError):
            PaginationParams(offset=-1)

        with pytest.raises(ValidationError):
            PaginationParams(limit=0)

        with pytest.raises(ValidationError):
            PaginationParams(limit=101)

    def test_metadata_filter(self):
        """Test metadata filter."""
        filter = MetadataFilter(
            field="source_type",
            operator="eq",
            value="documentation",
        )

        assert filter.field == "source_type"
        assert filter.operator == "eq"

    def test_component_health(self):
        """Test component health."""
        health = ComponentHealth(
            name="qdrant",
            healthy=True,
            latency_ms=5.2,
        )

        assert health.name == "qdrant"
        assert health.healthy is True
        assert health.latency_ms == 5.2

    def test_component_health_error(self):
        """Test component health with error."""
        health = ComponentHealth(
            name="opensearch",
            healthy=False,
            error="Connection refused",
        )

        assert health.healthy is False
        assert health.error == "Connection refused"


class TestExplainResponse:
    """Tests for ExplainResponse schema."""

    def test_explain_response(self):
        """Test explain response."""
        chunk_id = uuid4()

        response = ExplainResponse(
            chunk_id=chunk_id,
            query="test query",
            explanation={
                "semantic_similarity": 0.85,
                "keyword_score": 0.72,
                "final_rank": 1,
            },
        )

        assert response.chunk_id == chunk_id
        assert response.explanation["semantic_similarity"] == 0.85
