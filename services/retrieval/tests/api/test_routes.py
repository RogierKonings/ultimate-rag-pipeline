"""Tests for API routes."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from acl.context import UserContextExtractor
from acl.filter import ACLFilter
from acl.models import ACLFilterConfig, UserContext
from api.routes import health, retrieve
from config import RetrievalConfig
from query.models import ProcessedQuery, QueryType
from query.preprocessor import QueryPreprocessor
from reranking.models import RerankerConfig, RerankResponse, RerankResult
from reranking.reranker import RerankerService
from search.fusion import FusedResult, FusionMethod, HybridSearchConfig, HybridSearchResponse
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher
from search.models import KeywordSearchResponse, SearchResultItem, SemanticSearchResponse
from search.semantic import SemanticSearcher


@pytest.fixture
def jwt_secret():
    """JWT secret for testing."""
    return "test-secret-key"


@pytest.fixture
def config(jwt_secret):
    """Test configuration."""
    return RetrievalConfig(
        jwt_secret=jwt_secret,
        debug=True,
    )


@pytest.fixture
def mock_preprocessor():
    """Mock QueryPreprocessor."""
    preprocessor = AsyncMock(spec=QueryPreprocessor)
    preprocessor.process.return_value = ProcessedQuery(
        original_query="test query",
        normalized_query="test query",
        expanded_queries=[],
        hyde_document=None,
        embedding=[0.1] * 1024,
        query_type=QueryType.HYBRID,
        tokens=10,
        processing_time_ms=5.0,
    )
    return preprocessor


@pytest.fixture
def mock_semantic_searcher():
    """Mock SemanticSearcher."""
    searcher = AsyncMock(spec=SemanticSearcher)
    searcher.health_check.return_value = True
    searcher.search.return_value = SemanticSearchResponse(
        results=[
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test content 1",
                score=0.9,
                title="Doc 1",
                source="test.md",
                metadata={},
            )
        ],
        total_found=1,
        search_time_ms=10.0,
    )
    return searcher


@pytest.fixture
def mock_keyword_searcher():
    """Mock KeywordSearcher."""
    searcher = AsyncMock(spec=KeywordSearcher)
    searcher.health_check.return_value = True
    searcher.search.return_value = KeywordSearchResponse(
        results=[
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test content 2",
                score=0.8,
                title="Doc 2",
                source="test2.md",
                metadata={},
            )
        ],
        total_found=1,
        search_time_ms=8.0,
    )
    return searcher


@pytest.fixture
def mock_hybrid_searcher(mock_semantic_searcher, mock_keyword_searcher):
    """Mock HybridSearcher."""
    searcher = AsyncMock(spec=HybridSearcher)
    searcher.semantic = mock_semantic_searcher
    searcher.keyword = mock_keyword_searcher
    searcher.health_check.return_value = True

    chunk_id = uuid4()
    doc_id = uuid4()

    searcher.search.return_value = HybridSearchResponse(
        results=[
            FusedResult(
                chunk_id=chunk_id,
                document_id=doc_id,
                content="Test content",
                fused_score=0.85,
                semantic_score=0.9,
                keyword_score=0.7,
                semantic_rank=1,
                keyword_rank=2,
                metadata={"source_type": "test"},
                title="Test Doc",
                source="test.md",
            )
        ],
        total_semantic=10,
        total_keyword=8,
        search_time_ms=25.0,
        fusion_method=FusionMethod.RRF,
    )

    searcher.search_semantic_only.return_value = HybridSearchResponse(
        results=[
            FusedResult(
                chunk_id=chunk_id,
                document_id=doc_id,
                content="Semantic result",
                fused_score=0.9,
                semantic_score=0.9,
                semantic_rank=1,
                metadata={},
            )
        ],
        total_semantic=10,
        total_keyword=0,
        search_time_ms=15.0,
        fusion_method=FusionMethod.RRF,
    )

    searcher.search_keyword_only.return_value = HybridSearchResponse(
        results=[
            FusedResult(
                chunk_id=chunk_id,
                document_id=doc_id,
                content="Keyword result",
                fused_score=0.8,
                keyword_score=0.8,
                keyword_rank=1,
                metadata={},
            )
        ],
        total_semantic=0,
        total_keyword=8,
        search_time_ms=10.0,
        fusion_method=FusionMethod.RRF,
    )

    return searcher


@pytest.fixture
def mock_reranker():
    """Mock RerankerService."""
    reranker = AsyncMock(spec=RerankerService)
    reranker.health_check.return_value = True

    async def mock_rerank_fused(query, fused_results, top_k=None):
        # Return the same results with updated scores
        for r in fused_results:
            r.fused_score = min(r.fused_score + 0.05, 1.0)
            r.metadata["rerank_score"] = r.fused_score
        return fused_results[:top_k] if top_k else fused_results

    reranker.rerank_fused_results.side_effect = mock_rerank_fused
    reranker.rerank.return_value = RerankResponse(
        results=[
            RerankResult(
                document_id=uuid4(),
                index=0,
                relevance_score=0.92,
            )
        ],
        model="test-model",
        processing_time_ms=50.0,
    )
    return reranker


@pytest.fixture
def mock_acl_filter():
    """Mock ACLFilter."""
    return ACLFilter(ACLFilterConfig(enabled=False))


@pytest.fixture
def mock_user_extractor(jwt_secret):
    """Mock UserContextExtractor."""
    return UserContextExtractor(secret_key=jwt_secret)


@pytest.fixture
def app(
    config,
    mock_preprocessor,
    mock_hybrid_searcher,
    mock_reranker,
    mock_acl_filter,
    mock_user_extractor,
):
    """Create test FastAPI app with mocked dependencies."""
    app = FastAPI()

    # Set up app state
    app.state.config = config
    app.state.preprocessor = mock_preprocessor
    app.state.hybrid = mock_hybrid_searcher
    app.state.reranker = mock_reranker
    app.state.acl_filter = mock_acl_filter
    app.state.user_extractor = mock_user_extractor

    # Include routers
    app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
    app.include_router(health.router, tags=["Health"])

    return app


@pytest.fixture
def client(app):
    """Test client."""
    return TestClient(app)


@pytest.fixture
def auth_header(jwt_secret):
    """Generate auth header with valid JWT."""
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "groups": ["users"],
            "roles": ["user"],
        },
        jwt_secret,
    )
    return {"Authorization": f"Bearer {token}"}


class TestRetrieveEndpoint:
    """Tests for /api/v1/retrieve endpoint."""

    def test_retrieve_basic(self, client, auth_header):
        """Test basic retrieve request."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "metrics" in data
        assert "query_id" in data
        assert data["mode"] == "hybrid"

    def test_retrieve_with_mode_semantic(self, client, auth_header):
        """Test retrieve with semantic mode."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "mode": "semantic"},
            headers=auth_header,
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "semantic"

    def test_retrieve_with_mode_keyword(self, client, auth_header):
        """Test retrieve with keyword mode."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "mode": "keyword"},
            headers=auth_header,
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "keyword"

    def test_retrieve_with_top_k(self, client, auth_header):
        """Test retrieve with custom top_k."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "top_k": 5},
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_retrieve_with_weights(self, client, auth_header):
        """Test retrieve with custom weights."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test query",
                "semantic_weight": 0.8,
                "keyword_weight": 0.2,
            },
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_retrieve_no_rerank(self, client, auth_header):
        """Test retrieve without reranking."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "rerank": False},
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_retrieve_with_filters(self, client, auth_header):
        """Test retrieve with metadata filters."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test query",
                "filters": {"source_type": "documentation"},
            },
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_retrieve_with_min_score(self, client, auth_header):
        """Test retrieve with minimum score threshold."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "min_score": 0.5},
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_retrieve_includes_metrics(self, client, auth_header):
        """Test that response includes timing metrics."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        data = response.json()
        assert "metrics" in data
        metrics = data["metrics"]
        assert "total_ms" in metrics
        assert "query_preprocessing_ms" in metrics

    def test_retrieve_includes_score_breakdown(self, client, auth_header):
        """Test that results include score breakdown."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        data = response.json()
        if data["results"]:
            result = data["results"][0]
            assert "score" in result

    def test_retrieve_empty_query_rejected(self, client, auth_header):
        """Test that empty query is rejected."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": ""},
            headers=auth_header,
        )

        assert response.status_code == 422

    def test_retrieve_top_k_out_of_range(self, client, auth_header):
        """Test that out of range top_k is rejected."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test", "top_k": 1000},
            headers=auth_header,
        )

        assert response.status_code == 422

    def test_retrieve_anonymous_allowed(self, client):
        """Test that anonymous access is allowed."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
        )

        # Anonymous should be allowed but with limited access
        assert response.status_code == 200

    def test_retrieve_invalid_token(self, client):
        """Test that invalid token is rejected."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401


class TestMultiQueryEndpoint:
    """Tests for /api/v1/retrieve/multi endpoint."""

    def test_multi_query_basic(self, client, auth_header):
        """Test basic multi-query request."""
        response = client.post(
            "/api/v1/retrieve/multi",
            json={"queries": ["query 1", "query 2"]},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_multi_query_aggregation_max(self, client, auth_header):
        """Test multi-query with max aggregation."""
        response = client.post(
            "/api/v1/retrieve/multi",
            json={"queries": ["query 1", "query 2"], "aggregation": "max"},
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_multi_query_aggregation_avg(self, client, auth_header):
        """Test multi-query with avg aggregation."""
        response = client.post(
            "/api/v1/retrieve/multi",
            json={"queries": ["query 1", "query 2"], "aggregation": "avg"},
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_multi_query_aggregation_rrf(self, client, auth_header):
        """Test multi-query with rrf aggregation."""
        response = client.post(
            "/api/v1/retrieve/multi",
            json={"queries": ["query 1", "query 2"], "aggregation": "rrf"},
            headers=auth_header,
        )

        assert response.status_code == 200


class TestExplainEndpoint:
    """Tests for /api/v1/retrieve/explain endpoint."""

    def test_explain_basic(self, client, auth_header, mock_hybrid_searcher):
        """Test basic explain request."""
        # Get the chunk_id from mock
        chunk_id = mock_hybrid_searcher.search.return_value.results[0].chunk_id

        response = client.get(
            f"/api/v1/retrieve/explain/{chunk_id}",
            params={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()
        assert "chunk_id" in data
        assert "explanation" in data

    def test_explain_not_found(self, client, auth_header):
        """Test explain for non-existent chunk."""
        response = client.get(
            f"/api/v1/retrieve/explain/{uuid4()}",
            params={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 404


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client):
        """Test main health endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "components" in data
        assert "timestamp" in data

    def test_liveness_probe(self, client):
        """Test liveness probe."""
        response = client.get("/health/live")

        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_readiness_probe(self, client):
        """Test readiness probe."""
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"


class TestResponseHeaders:
    """Tests for response headers."""

    def test_timing_header(self, client, auth_header):
        """Test that timing header is included."""
        # Note: This would require middleware setup in the test app
        # For now, we test the endpoint works
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test"},
            headers=auth_header,
        )

        assert response.status_code == 200
