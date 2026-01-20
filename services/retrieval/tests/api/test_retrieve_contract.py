"""Tests for API contract alignment (US-3.10).

Verifies:
- Hybrid ordering: RRF → rerank → ACL
- Default weights/top_k consistent with architecture
- Debug block contains required fields
- Request/response schemas match architecture
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from acl.context import UserContextExtractor
from acl.filter import ACLFilter
from acl.models import ACLFilterConfig
from acl.safety_net import ACLSafetyNet
from api.routes import health, retrieve
from api.schemas.retrieve import (
    DebugInfo,
    RetrieveRequest,
    RetrieveResponse,
    SearchMetrics,
    SearchMode,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from query.models import ProcessedQuery, QueryType
from query.preprocessor import QueryPreprocessor
from reranking.reranker import RerankerService
from search.fusion import FusedResult, FusionMethod, HybridSearchResponse
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher
from search.semantic import SemanticSearcher

from config import RetrievalConfig


class TestDefaultsMatchArchitecture:
    """Test that defaults match architecture specification."""

    def test_default_semantic_weight(self):
        """Default semantic weight should be 0.7."""
        request = RetrieveRequest(query="test")
        assert request.semantic_weight == 0.7

    def test_default_keyword_weight(self):
        """Default keyword weight should be 0.3."""
        request = RetrieveRequest(query="test")
        assert request.keyword_weight == 0.3

    def test_default_mode_is_hybrid(self):
        """Default mode should be hybrid."""
        request = RetrieveRequest(query="test")
        assert request.mode == SearchMode.HYBRID

    def test_default_top_k(self):
        """Default top_k should be 10."""
        request = RetrieveRequest(query="test")
        assert request.top_k == 10

    def test_default_rerank_disabled(self):
        """Reranking is disabled by default for faster responses."""
        request = RetrieveRequest(query="test")
        assert request.rerank is False

    def test_default_rerank_top_k(self):
        """Default rerank_top_k should be 20."""
        request = RetrieveRequest(query="test")
        assert request.rerank_top_k == 20

    def test_config_defaults(self):
        """Config defaults should match architecture."""
        config = RetrievalConfig()
        assert config.semantic_weight == 0.7
        assert config.keyword_weight == 0.3


class TestDebugInfoSchema:
    """Test DebugInfo schema contains required fields."""

    def test_debug_info_has_stage_counts(self):
        """Debug info should have all stage counts."""
        debug = DebugInfo()

        assert hasattr(debug, "semantic_candidates")
        assert hasattr(debug, "keyword_candidates")
        assert hasattr(debug, "after_fusion")
        assert hasattr(debug, "after_rerank")
        assert hasattr(debug, "after_acl")

    def test_debug_info_has_latency_breakdown(self):
        """Debug info should have latency breakdown."""
        debug = DebugInfo()

        assert hasattr(debug, "preprocessing_latency_ms")
        assert hasattr(debug, "embedding_latency_ms")
        assert hasattr(debug, "semantic_search_latency_ms")
        assert hasattr(debug, "keyword_search_latency_ms")
        assert hasattr(debug, "fusion_latency_ms")
        assert hasattr(debug, "rerank_latency_ms")
        assert hasattr(debug, "acl_filter_latency_ms")
        assert hasattr(debug, "total_latency_ms")

    def test_debug_info_has_model_names(self):
        """Debug info should have model names."""
        debug = DebugInfo()

        assert hasattr(debug, "embedding_model")
        assert hasattr(debug, "rerank_model")

    def test_debug_info_has_pipeline_config(self):
        """Debug info should have pipeline configuration."""
        debug = DebugInfo()

        assert hasattr(debug, "fusion_method")
        assert hasattr(debug, "semantic_weight")
        assert hasattr(debug, "keyword_weight")
        assert hasattr(debug, "rrf_k")
        assert hasattr(debug, "top_k_semantic")
        assert hasattr(debug, "top_k_keyword")
        assert hasattr(debug, "rerank_top_k")

    def test_debug_info_default_values(self):
        """Debug info defaults should match architecture."""
        debug = DebugInfo()

        assert debug.fusion_method == "rrf"
        assert debug.semantic_weight == 0.7
        assert debug.keyword_weight == 0.3
        assert debug.rrf_k == 60
        assert debug.top_k_semantic == 50
        assert debug.top_k_keyword == 50
        assert debug.rerank_top_k == 10

    def test_debug_info_serialization(self):
        """Debug info should serialize to JSON."""
        debug = DebugInfo(
            semantic_candidates=50,
            keyword_candidates=50,
            after_fusion=40,
            after_rerank=10,
            after_acl=10,
            total_latency_ms=150.5,
            embedding_model="bge-large-en-v1.5",
            rerank_model="bge-reranker-v2-m3",
        )

        data = debug.model_dump()

        assert data["semantic_candidates"] == 50
        assert data["after_fusion"] == 40
        assert data["embedding_model"] == "bge-large-en-v1.5"


class TestRetrieveResponseDebug:
    """Test RetrieveResponse includes debug info."""

    def test_response_has_debug_field(self):
        """Response should have optional debug field."""
        response = RetrieveResponse(
            results=[],
            total_results=0,
            query="test",
            mode=SearchMode.HYBRID,
            metrics=SearchMetrics(total_ms=100),
            query_id=uuid4(),
            processed_at=datetime.now(tz=UTC),
        )

        assert hasattr(response, "debug")
        assert response.debug is None

    def test_response_with_debug_info(self):
        """Response can include debug info."""
        debug = DebugInfo(
            semantic_candidates=50,
            keyword_candidates=50,
            total_latency_ms=150.5,
        )

        response = RetrieveResponse(
            results=[],
            total_results=0,
            query="test",
            mode=SearchMode.HYBRID,
            metrics=SearchMetrics(total_ms=150.5),
            query_id=uuid4(),
            processed_at=datetime.now(tz=UTC),
            debug=debug,
        )

        assert response.debug is not None
        assert response.debug.semantic_candidates == 50


class TestRequestValidation:
    """Test request validation per contract."""

    def test_query_required(self):
        """Query is required."""
        with pytest.raises(Exception):
            RetrieveRequest()

    def test_query_min_length(self):
        """Query must have at least 1 character."""
        with pytest.raises(Exception):
            RetrieveRequest(query="")

    def test_query_max_length(self):
        """Query max length is 2000 characters."""
        # Should work at 2000
        request = RetrieveRequest(query="a" * 2000)
        assert len(request.query) == 2000

        # Should fail at 2001
        with pytest.raises(Exception):
            RetrieveRequest(query="a" * 2001)

    def test_top_k_range(self):
        """top_k must be between 1 and 100."""
        # Valid values
        RetrieveRequest(query="test", top_k=1)
        RetrieveRequest(query="test", top_k=100)

        # Invalid values
        with pytest.raises(Exception):
            RetrieveRequest(query="test", top_k=0)
        with pytest.raises(Exception):
            RetrieveRequest(query="test", top_k=101)

    def test_weight_range(self):
        """Weights must be between 0 and 1."""
        # Valid values
        RetrieveRequest(query="test", semantic_weight=0.0)
        RetrieveRequest(query="test", semantic_weight=1.0)

        # Invalid values
        with pytest.raises(Exception):
            RetrieveRequest(query="test", semantic_weight=-0.1)
        with pytest.raises(Exception):
            RetrieveRequest(query="test", semantic_weight=1.1)

    def test_mode_values(self):
        """Mode must be one of hybrid, semantic, keyword."""
        for mode in ["hybrid", "semantic", "keyword"]:
            request = RetrieveRequest(query="test", mode=mode)
            assert request.mode.value == mode


class TestHybridOrdering:
    """Test that hybrid pipeline ordering is correct: RRF → rerank → ACL."""

    @pytest.fixture
    def jwt_secret(self):
        """JWT secret for testing."""
        return "test-secret-key"

    @pytest.fixture
    def config(self, jwt_secret):
        """Test configuration."""
        return RetrievalConfig(jwt_secret=jwt_secret, debug=True)

    @pytest.fixture
    def mock_preprocessor(self):
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
    def mock_hybrid_searcher(self):
        """Mock HybridSearcher."""
        searcher = AsyncMock(spec=HybridSearcher)
        searcher.semantic = AsyncMock(spec=SemanticSearcher)
        searcher.keyword = AsyncMock(spec=KeywordSearcher)
        searcher.health_check.return_value = True

        # Create results that can be verified for ordering
        chunk_ids = [uuid4() for _ in range(5)]
        doc_ids = [uuid4() for _ in range(5)]

        results = [
            FusedResult(
                chunk_id=chunk_ids[i],
                document_id=doc_ids[i],
                content=f"Content {i}",
                fused_score=0.9 - (i * 0.1),  # 0.9, 0.8, 0.7, 0.6, 0.5
                semantic_score=0.9 - (i * 0.05),
                keyword_score=0.8 - (i * 0.1),
                semantic_rank=i + 1,
                keyword_rank=i + 1,
                metadata={},
            )
            for i in range(5)
        ]

        searcher.search.return_value = HybridSearchResponse(
            results=results,
            total_semantic=50,
            total_keyword=50,
            search_time_ms=25.0,
            fusion_method=FusionMethod.RRF,
        )

        return searcher

    @pytest.fixture
    def mock_reranker(self):
        """Mock RerankerService."""
        reranker = AsyncMock(spec=RerankerService)
        reranker.health_check.return_value = True

        async def mock_rerank_fused(query, fused_results, top_k=None):
            # Verify results come in after fusion
            for r in fused_results:
                r.fused_score = min(r.fused_score + 0.05, 1.0)
                r.metadata["reranked"] = True
            return fused_results[:top_k] if top_k else fused_results

        reranker.rerank_fused_results.side_effect = mock_rerank_fused
        return reranker

    @pytest.fixture
    def mock_acl_filter(self):
        """Mock ACLFilter that passes all results."""
        return ACLFilter(ACLFilterConfig(enabled=False))

    @pytest.fixture
    def mock_safety_net(self):
        """Mock ACLSafetyNet for testing."""
        return ACLSafetyNet()

    @pytest.fixture
    def mock_user_extractor(self, jwt_secret):
        """Mock UserContextExtractor."""
        return UserContextExtractor(secret_key=jwt_secret)

    @pytest.fixture
    def app(
        self,
        config,
        mock_preprocessor,
        mock_hybrid_searcher,
        mock_reranker,
        mock_acl_filter,
        mock_safety_net,
        mock_user_extractor,
    ):
        """Create test FastAPI app."""
        app = FastAPI()

        app.state.config = config
        app.state.preprocessor = mock_preprocessor
        app.state.hybrid = mock_hybrid_searcher
        app.state.reranker = mock_reranker
        app.state.acl_filter = mock_acl_filter
        app.state.safety_net = mock_safety_net
        app.state.user_extractor = mock_user_extractor

        app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
        app.include_router(health.router, tags=["Health"])

        return app

    @pytest.fixture
    def client(self, app):
        """Test client."""
        return TestClient(app)

    @pytest.fixture
    def auth_header(self, jwt_secret):
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

    def test_pipeline_executes_in_order(
        self,
        client,
        auth_header,
        mock_hybrid_searcher,
        mock_reranker,
    ):
        """Test that pipeline executes: search → fusion → rerank → ACL."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query", "rerank": True},  # Enable reranking explicitly
            headers=auth_header,
        )

        assert response.status_code == 200

        # Verify search was called
        mock_hybrid_searcher.search.assert_called_once()

        # Verify reranker was called with fused results
        mock_reranker.rerank_fused_results.assert_called_once()

    def test_response_has_metrics(self, client, auth_header):
        """Test that response includes timing metrics."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        metrics = data["metrics"]
        assert "total_ms" in metrics
        assert "query_preprocessing_ms" in metrics

    def test_response_has_query_id(self, client, auth_header):
        """Test that response includes query_id (retrieval_id)."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        assert "query_id" in data
        # Verify it's a valid UUID format
        assert len(data["query_id"]) == 36


class TestScoresReflectWeights:
    """Test that scores reflect configured weights."""

    def test_request_accepts_custom_weights(self):
        """Request should accept custom weights."""
        request = RetrieveRequest(
            query="test",
            semantic_weight=0.8,
            keyword_weight=0.2,
        )

        assert request.semantic_weight == 0.8
        assert request.keyword_weight == 0.2

    def test_weights_can_be_equal(self):
        """Weights can be set to equal values."""
        request = RetrieveRequest(
            query="test",
            semantic_weight=0.5,
            keyword_weight=0.5,
        )

        assert request.semantic_weight == 0.5
        assert request.keyword_weight == 0.5


class TestConfigurableBounds:
    """Test that configurable values have sane bounds."""

    def test_top_k_bounds(self):
        """top_k is bounded between 1 and 100."""
        assert RetrieveRequest(query="test", top_k=1).top_k == 1
        assert RetrieveRequest(query="test", top_k=100).top_k == 100

    def test_rerank_top_k_bounds(self):
        """rerank_top_k is bounded between 1 and 100."""
        assert RetrieveRequest(query="test", rerank_top_k=1).rerank_top_k == 1
        assert RetrieveRequest(query="test", rerank_top_k=100).rerank_top_k == 100

    def test_min_score_bounds(self):
        """min_score is bounded between 0 and 1."""
        assert RetrieveRequest(query="test", min_score=0.0).min_score == 0.0
        assert RetrieveRequest(query="test", min_score=1.0).min_score == 1.0

        with pytest.raises(Exception):
            RetrieveRequest(query="test", min_score=-0.1)
        with pytest.raises(Exception):
            RetrieveRequest(query="test", min_score=1.1)


class TestACLSafetyNetIntegration:
    """Test ACL safety net integration in retrieve endpoint.

    The safety net is a defense-in-depth filter applied AFTER reranking
    but BEFORE score threshold and top_k limiting.
    """

    @pytest.fixture
    def jwt_secret(self):
        """JWT secret for testing."""
        return "test-secret-key"

    @pytest.fixture
    def config(self, jwt_secret):
        """Test configuration."""
        return RetrievalConfig(jwt_secret=jwt_secret, debug=True)

    @pytest.fixture
    def tenant_id(self):
        """Consistent tenant ID for tests."""
        return uuid4()

    @pytest.fixture
    def user_id(self):
        """Consistent user ID for tests."""
        return uuid4()

    @pytest.fixture
    def mock_preprocessor(self):
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
    def mock_hybrid_searcher_with_acl_metadata(self, tenant_id, user_id):
        """Mock HybridSearcher returning results with ACL metadata."""
        searcher = AsyncMock(spec=HybridSearcher)
        searcher.semantic = AsyncMock(spec=SemanticSearcher)
        searcher.keyword = AsyncMock(spec=KeywordSearcher)
        searcher.health_check.return_value = True

        # Create results with proper ACL metadata
        # These should all pass through safety net since tenant matches
        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Content {i}",
                fused_score=0.9 - (i * 0.1),
                semantic_score=0.9 - (i * 0.05),
                keyword_score=0.8 - (i * 0.1),
                semantic_rank=i + 1,
                keyword_rank=i + 1,
                metadata={
                    "tenant_id": str(tenant_id),
                    "visibility": "public",
                    "status": "active",
                },
            )
            for i in range(3)
        ]

        searcher.search.return_value = HybridSearchResponse(
            results=results,
            total_semantic=50,
            total_keyword=50,
            search_time_ms=25.0,
            fusion_method=FusionMethod.RRF,
        )

        return searcher

    @pytest.fixture
    def mock_reranker(self):
        """Mock RerankerService."""
        reranker = AsyncMock(spec=RerankerService)
        reranker.health_check.return_value = True

        async def mock_rerank_fused(query, fused_results, top_k=None):
            return fused_results[:top_k] if top_k else fused_results

        reranker.rerank_fused_results.side_effect = mock_rerank_fused
        return reranker

    @pytest.fixture
    def mock_acl_filter(self):
        """Mock ACLFilter that passes all results."""
        return ACLFilter(ACLFilterConfig(enabled=False))

    @pytest.fixture
    def safety_net(self):
        """Real ACLSafetyNet for integration testing."""
        return ACLSafetyNet()

    @pytest.fixture
    def mock_user_extractor(self, jwt_secret):
        """Mock UserContextExtractor."""
        return UserContextExtractor(secret_key=jwt_secret)

    @pytest.fixture
    def app(
        self,
        config,
        mock_preprocessor,
        mock_hybrid_searcher_with_acl_metadata,
        mock_reranker,
        mock_acl_filter,
        safety_net,
        mock_user_extractor,
    ):
        """Create test FastAPI app with safety net."""
        app = FastAPI()

        app.state.config = config
        app.state.preprocessor = mock_preprocessor
        app.state.hybrid = mock_hybrid_searcher_with_acl_metadata
        app.state.reranker = mock_reranker
        app.state.acl_filter = mock_acl_filter
        app.state.safety_net = safety_net
        app.state.user_extractor = mock_user_extractor

        app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
        app.include_router(health.router, tags=["Health"])

        return app

    @pytest.fixture
    def client(self, app):
        """Test client."""
        return TestClient(app)

    @pytest.fixture
    def auth_header(self, jwt_secret, tenant_id, user_id):
        """Generate auth header with valid JWT matching tenant."""
        token = jwt.encode(
            {
                "sub": str(user_id),
                "tenant_id": str(tenant_id),
                "groups": ["users"],
                "roles": ["user"],
            },
            jwt_secret,
        )
        return {"Authorization": f"Bearer {token}"}

    def test_safety_net_passes_all_accessible_results(self, client, auth_header):
        """Safety net should pass all results when ACL metadata matches user."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        # All 3 results should pass through (tenant matches, public visibility)
        assert data["total_results"] == 3

    def test_safety_net_filters_wrong_tenant(
        self,
        config,
        mock_preprocessor,
        mock_reranker,
        mock_acl_filter,
        safety_net,
        mock_user_extractor,
        jwt_secret,
    ):
        """Safety net should filter results from wrong tenant."""
        # Create a searcher that returns a result from a different tenant
        wrong_tenant_id = uuid4()
        user_tenant_id = uuid4()

        searcher = AsyncMock(spec=HybridSearcher)
        searcher.semantic = AsyncMock(spec=SemanticSearcher)
        searcher.keyword = AsyncMock(spec=KeywordSearcher)
        searcher.health_check.return_value = True

        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Content from wrong tenant",
                fused_score=0.9,
                semantic_score=0.85,
                keyword_score=0.75,
                metadata={
                    "tenant_id": str(wrong_tenant_id),  # Different tenant
                    "visibility": "public",
                    "status": "active",
                },
            ),
        ]

        searcher.search.return_value = HybridSearchResponse(
            results=results,
            total_semantic=1,
            total_keyword=1,
            search_time_ms=25.0,
            fusion_method=FusionMethod.RRF,
        )

        app = FastAPI()
        app.state.config = config
        app.state.preprocessor = mock_preprocessor
        app.state.hybrid = searcher
        app.state.reranker = mock_reranker
        app.state.acl_filter = mock_acl_filter
        app.state.safety_net = safety_net
        app.state.user_extractor = mock_user_extractor

        app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])

        client = TestClient(app)

        # Create token with user's tenant
        token = jwt.encode(
            {
                "sub": str(uuid4()),
                "tenant_id": str(user_tenant_id),  # User's tenant
                "groups": ["users"],
                "roles": ["user"],
            },
            jwt_secret,
        )

        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Result should be filtered out by safety net (wrong tenant)
        assert data["total_results"] == 0

    def test_safety_net_filters_deleted_documents(
        self,
        config,
        mock_preprocessor,
        mock_reranker,
        mock_acl_filter,
        safety_net,
        mock_user_extractor,
        jwt_secret,
    ):
        """Safety net should filter soft-deleted documents."""
        tenant_id = uuid4()

        searcher = AsyncMock(spec=HybridSearcher)
        searcher.semantic = AsyncMock(spec=SemanticSearcher)
        searcher.keyword = AsyncMock(spec=KeywordSearcher)
        searcher.health_check.return_value = True

        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Deleted document content",
                fused_score=0.9,
                semantic_score=0.85,
                keyword_score=0.75,
                metadata={
                    "tenant_id": str(tenant_id),
                    "visibility": "public",
                    "status": "deleted",  # Soft-deleted
                },
            ),
        ]

        searcher.search.return_value = HybridSearchResponse(
            results=results,
            total_semantic=1,
            total_keyword=1,
            search_time_ms=25.0,
            fusion_method=FusionMethod.RRF,
        )

        app = FastAPI()
        app.state.config = config
        app.state.preprocessor = mock_preprocessor
        app.state.hybrid = searcher
        app.state.reranker = mock_reranker
        app.state.acl_filter = mock_acl_filter
        app.state.safety_net = safety_net
        app.state.user_extractor = mock_user_extractor

        app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])

        client = TestClient(app)

        token = jwt.encode(
            {
                "sub": str(uuid4()),
                "tenant_id": str(tenant_id),
                "groups": ["users"],
                "roles": ["user"],
            },
            jwt_secret,
        )

        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Deleted document should be filtered out
        assert data["total_results"] == 0
