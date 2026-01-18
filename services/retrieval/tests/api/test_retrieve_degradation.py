"""Tests for degradation info in retrieval responses."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from acl.context import UserContextExtractor
from acl.filter import ACLFilter
from acl.models import ACLFilterConfig
from acl.safety_net import ACLSafetyNet
from api.routes import health, retrieve
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from query.models import ProcessedQuery, QueryType
from query.preprocessor import QueryPreprocessor
from reranking.reranker import RerankerService
from resilience.degradation import (
    DegradationMode,
    DegradationStatus,
    RetrievalDegradationManager,
)
from search.fusion import FusedResult, FusionMethod, HybridSearchResponse
from search.hybrid import HybridSearcher

from config import RetrievalConfig


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
def mock_hybrid_searcher():
    """Mock HybridSearcher."""
    searcher = AsyncMock(spec=HybridSearcher)
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
            ),
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
            ),
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
            ),
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
    return reranker


@pytest.fixture
def mock_acl_filter():
    """Mock ACLFilter."""
    return ACLFilter(ACLFilterConfig(enabled=False))


@pytest.fixture
def mock_safety_net():
    """Mock ACLSafetyNet."""
    safety_net = MagicMock(spec=ACLSafetyNet)
    safety_net.filter.side_effect = lambda results, user: results
    return safety_net


@pytest.fixture
def mock_user_extractor(jwt_secret):
    """Mock UserContextExtractor."""
    return UserContextExtractor(secret_key=jwt_secret)


@pytest.fixture
def mock_degradation_manager():
    """Create a mock degradation manager with all healthy components."""
    manager = MagicMock(spec=RetrievalDegradationManager)
    manager.get_status.return_value = DegradationStatus(
        mode=DegradationMode.HYBRID_FULL,
        qdrant_healthy=True,
        opensearch_healthy=True,
        reranker_healthy=True,
        components_available=["qdrant", "opensearch", "reranker"],
        components_unavailable=[],
    )
    return manager


@pytest.fixture
def app(
    config,
    mock_preprocessor,
    mock_hybrid_searcher,
    mock_reranker,
    mock_acl_filter,
    mock_safety_net,
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
    app.state.safety_net = mock_safety_net
    app.state.user_extractor = mock_user_extractor

    # Include routers
    app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
    app.include_router(health.router, tags=["Health"])

    return app


@pytest.fixture
def test_client(app):
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


class TestRetrieveDegradationInfo:
    """Tests for degradation info in retrieve endpoint."""

    def test_retrieve_includes_degradation_mode_normal(
        self, test_client, auth_header, mock_degradation_manager
    ):
        """Retrieve should include normal degradation mode when all healthy."""
        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=mock_degradation_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
                headers=auth_header,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "hybrid_full"
        assert "qdrant" in data["components_used"]
        assert "opensearch" in data["components_used"]
        assert data["components_skipped"] == []

    def test_retrieve_includes_degradation_mode_semantic_only(
        self, test_client, auth_header
    ):
        """Retrieve should show semantic_only when opensearch is down."""
        degraded_manager = MagicMock(spec=RetrievalDegradationManager)
        degraded_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.SEMANTIC_ONLY,
            qdrant_healthy=True,
            opensearch_healthy=False,
            reranker_healthy=True,
            components_available=["qdrant", "reranker"],
            components_unavailable=["opensearch"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=degraded_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
                headers=auth_header,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "semantic_only"
        assert "qdrant" in data["components_used"]
        assert "opensearch" in data["components_skipped"]

    def test_retrieve_includes_degradation_mode_minimal(
        self, test_client, auth_header
    ):
        """Retrieve should show minimal when multiple components down."""
        minimal_manager = MagicMock(spec=RetrievalDegradationManager)
        minimal_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.MINIMAL,
            qdrant_healthy=True,
            opensearch_healthy=False,
            reranker_healthy=False,
            components_available=["qdrant"],
            components_unavailable=["opensearch", "reranker"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=minimal_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
                headers=auth_header,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "minimal"
        assert data["components_used"] == ["qdrant"]
        assert "opensearch" in data["components_skipped"]
        assert "reranker" in data["components_skipped"]

    def test_retrieve_includes_degradation_mode_keyword_only(
        self, test_client, auth_header
    ):
        """Retrieve should show keyword_only when qdrant is down."""
        keyword_manager = MagicMock(spec=RetrievalDegradationManager)
        keyword_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.KEYWORD_ONLY,
            qdrant_healthy=False,
            opensearch_healthy=True,
            reranker_healthy=True,
            components_available=["opensearch", "reranker"],
            components_unavailable=["qdrant"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=keyword_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
                headers=auth_header,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "keyword_only"
        assert "opensearch" in data["components_used"]
        assert "qdrant" in data["components_skipped"]

    def test_retrieve_includes_degradation_mode_no_rerank(
        self, test_client, auth_header
    ):
        """Retrieve should show hybrid_no_rerank when reranker is down."""
        no_rerank_manager = MagicMock(spec=RetrievalDegradationManager)
        no_rerank_manager.get_status.return_value = DegradationStatus(
            mode=DegradationMode.HYBRID_NO_RERANK,
            qdrant_healthy=True,
            opensearch_healthy=True,
            reranker_healthy=False,
            components_available=["qdrant", "opensearch"],
            components_unavailable=["reranker"],
        )

        with patch(
            "api.routes.retrieve.get_degradation_manager",
            return_value=no_rerank_manager,
        ):
            response = test_client.post(
                "/api/v1/retrieve",
                json={"query": "test query", "top_k": 5},
                headers=auth_header,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["degradation_mode"] == "hybrid_no_rerank"
        assert "qdrant" in data["components_used"]
        assert "opensearch" in data["components_used"]
        assert "reranker" in data["components_skipped"]
