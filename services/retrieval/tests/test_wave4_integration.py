"""Wave 4 Integration Tests.

Tests that verify all Wave 4 components work together:
- US-3.7: Retrieval API
- US-3.8: Logging & Metrics
- US-3.9: Caching Layer
- US-3.10: Contract Alignment

This test file ensures the full retrieval service is ready for production.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from acl.context import UserContextExtractor
from acl.filter import ACLFilter
from acl.models import ACLFilterConfig
from api.routes import health, retrieve
from api.schemas import (
    DebugInfo,
    RetrieveRequest,
    SearchMode,
)
from cache import CacheConfig, CacheStats, RetrievalCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from observability import RetrievalLogger, RetrievalMetrics, TracingSetup
from query.models import ProcessedQuery, QueryType
from query.preprocessor import QueryPreprocessor
from reranking.reranker import RerankerService
from search.fusion import FusedResult, FusionMethod, HybridSearchResponse
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher
from search.semantic import SemanticSearcher

from config import RetrievalConfig


class TestWave4Imports:
    """Test that all Wave 4 components can be imported."""

    def test_api_imports(self):
        """Test API module imports."""
        from api.main import app
        from api.routes.health import router as health_router
        from api.routes.retrieve import router as retrieve_router

        assert app is not None
        assert health_router is not None
        assert retrieve_router is not None

    def test_observability_imports(self):
        """Test observability module imports."""
        from observability import (
            RetrievalLogger,
            RetrievalMetrics,
            TracingSetup,
        )

        assert RetrievalLogger is not None
        assert RetrievalMetrics is not None
        assert TracingSetup is not None

    def test_cache_imports(self):
        """Test cache module imports."""
        from cache import (
            CacheConfig,
            CacheStats,
            RetrievalCache,
        )

        assert RetrievalCache is not None
        assert CacheConfig is not None
        assert CacheStats is not None

    def test_config_imports(self):
        """Test config imports."""
        from config import RetrievalConfig

        assert RetrievalConfig is not None


class TestAPIWithObservability:
    """Test API with observability components."""

    @pytest.fixture
    def jwt_secret(self):
        """JWT secret for testing."""
        return "test-secret-key"

    @pytest.fixture
    def config(self, jwt_secret):
        """Test configuration."""
        return RetrievalConfig(
            jwt_secret=jwt_secret,
            debug=True,
            log_level="DEBUG",
        )

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
                    metadata={},
                ),
            ],
            total_semantic=10,
            total_keyword=8,
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
            for r in fused_results:
                r.fused_score = min(r.fused_score + 0.05, 1.0)
            return fused_results[:top_k] if top_k else fused_results

        reranker.rerank_fused_results.side_effect = mock_rerank_fused
        return reranker

    @pytest.fixture
    def mock_acl_filter(self):
        """Mock ACLFilter."""
        return ACLFilter(ACLFilterConfig(enabled=False))

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
        mock_user_extractor,
    ):
        """Create test FastAPI app with observability."""
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

    def test_full_api_flow(self, client, auth_header):
        """Test complete API request flow."""
        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test query"},
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "results" in data
        assert "total_results" in data
        assert "query" in data
        assert "mode" in data
        assert "metrics" in data
        assert "query_id" in data
        assert "processed_at" in data

    def test_health_endpoints(self, client):
        """Test health check endpoints."""
        # Main health
        response = client.get("/health")
        assert response.status_code == 200
        assert "status" in response.json()

        # Liveness
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

        # Readiness
        response = client.get("/health/ready")
        assert response.status_code == 200


class TestCacheIntegration:
    """Test cache integration with API."""

    def test_cache_config_from_retrieval_config(self):
        """Test that cache config can be derived from retrieval config."""
        config = RetrievalConfig(
            cache_enabled=True,
            cache_ttl_seconds=7200,
            redis_url="redis://redis:6379",
        )

        cache_config = CacheConfig(
            enabled=config.cache_enabled,
            redis_url=config.redis_url,
            default_ttl_seconds=config.cache_ttl_seconds,
        )

        assert cache_config.enabled is True
        assert cache_config.redis_url == "redis://redis:6379"
        assert cache_config.default_ttl_seconds == 7200

    @pytest.mark.asyncio
    async def test_cache_key_generation_with_user_context(self):
        """Test cache key includes user context for ACL scoping."""
        cache = RetrievalCache()
        tenant_id = uuid4()
        user_id1 = uuid4()
        user_id2 = uuid4()

        key1 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            user_id=user_id1,
        )
        key2 = cache._generate_cache_key(
            query="test",
            tenant_id=tenant_id,
            user_id=user_id2,
        )

        # Different users should have different cache keys
        assert key1 != key2

    def test_cache_metrics_integration(self):
        """Test cache metrics can be exported."""
        cache = RetrievalCache()
        cache._stats = CacheStats(
            hits=100,
            misses=50,
            sets=150,
            errors=2,
        )

        metrics = cache.get_metrics()

        assert metrics["cache_hits_total"] == 100
        assert metrics["cache_misses_total"] == 50
        assert metrics["cache_hit_rate"] == pytest.approx(0.666, rel=0.01)


class TestObservabilityIntegration:
    """Test observability components integration."""

    def test_logger_can_log_retrieval(self):
        """Test logger can log retrieval operations."""
        logger = RetrievalLogger(
            service_name="test-service",
            log_level="DEBUG",
            output_format="json",
        )

        # Should not raise
        logger.log_retrieval(
            query_id=uuid4(),
            query="test query",
            mode="hybrid",
            tenant_id=uuid4(),
            user_id=uuid4(),
            result_count=10,
            top_scores=[0.9, 0.8, 0.7],
            total_ms=150.0,
            preprocessing_ms=20.0,
            search_ms=100.0,
            rerank_ms=30.0,
        )

    def test_metrics_record_operations(self):
        """Test metrics can record operations."""
        # Use unique service name to avoid Prometheus conflicts
        service_name = f"test-metrics-{uuid4().hex[:8]}"
        metrics = RetrievalMetrics(service_name=service_name)

        # Record a request
        metrics.record_request(
            mode="hybrid",
            status="success",
            duration_seconds=0.15,
            result_count=10,
            top_score=0.9,
        )

        # Should not raise
        assert True

    def test_tracing_setup(self):
        """Test tracing can be set up."""
        tracing = TracingSetup(
            service_name="test-service",
            otlp_endpoint="http://localhost:4317",  # Default endpoint
            enable_console_export=False,
        )

        # TracingSetup should initialize without error
        # Tracer may be None if OpenTelemetry is not fully installed
        assert tracing.service_name == "test-service"
        assert tracing.otlp_endpoint == "http://localhost:4317"


class TestContractAlignment:
    """Test API contract alignment (US-3.10)."""

    def test_debug_info_structure(self):
        """Test DebugInfo has all required fields."""
        debug = DebugInfo()

        # Stage counts
        assert hasattr(debug, "semantic_candidates")
        assert hasattr(debug, "keyword_candidates")
        assert hasattr(debug, "after_fusion")
        assert hasattr(debug, "after_rerank")
        assert hasattr(debug, "after_acl")

        # Latency breakdown
        assert hasattr(debug, "total_latency_ms")
        assert hasattr(debug, "preprocessing_latency_ms")
        assert hasattr(debug, "semantic_search_latency_ms")
        assert hasattr(debug, "keyword_search_latency_ms")
        assert hasattr(debug, "rerank_latency_ms")

        # Model info
        assert hasattr(debug, "embedding_model")
        assert hasattr(debug, "rerank_model")

    def test_request_defaults_match_architecture(self):
        """Test request defaults match architecture spec."""
        request = RetrieveRequest(query="test")

        # Default weights per architecture
        assert request.semantic_weight == 0.7
        assert request.keyword_weight == 0.3

        # Default mode
        assert request.mode == SearchMode.HYBRID

        # Default reranking
        assert request.rerank is True

    def test_config_defaults_match_architecture(self):
        """Test config defaults match architecture spec."""
        config = RetrievalConfig()

        assert config.semantic_weight == 0.7
        assert config.keyword_weight == 0.3


class TestEndToEndIntegration:
    """End-to-end integration tests for complete retrieval service."""

    @pytest.fixture
    def jwt_secret(self):
        """JWT secret for testing."""
        return "test-secret-key"

    @pytest.fixture
    def config(self, jwt_secret):
        """Complete test configuration."""
        return RetrievalConfig(
            jwt_secret=jwt_secret,
            debug=True,
            log_level="DEBUG",
            cache_enabled=False,  # Disable for testing without Redis
        )

    @pytest.fixture
    def mock_preprocessor(self):
        """Mock QueryPreprocessor."""
        preprocessor = AsyncMock(spec=QueryPreprocessor)
        preprocessor.process.return_value = ProcessedQuery(
            original_query="machine learning basics",
            normalized_query="machine learning basics",
            expanded_queries=["ml fundamentals", "ai basics"],
            hyde_document=None,
            embedding=[0.1] * 1024,
            query_type=QueryType.HYBRID,
            tokens=15,
            processing_time_ms=8.0,
        )
        return preprocessor

    @pytest.fixture
    def mock_hybrid_searcher(self):
        """Mock HybridSearcher with realistic results."""
        searcher = AsyncMock(spec=HybridSearcher)
        searcher.semantic = AsyncMock(spec=SemanticSearcher)
        searcher.keyword = AsyncMock(spec=KeywordSearcher)
        searcher.health_check.return_value = True

        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Machine learning content chunk {i}",
                fused_score=0.95 - (i * 0.05),
                semantic_score=0.92 - (i * 0.03),
                keyword_score=0.88 - (i * 0.05),
                semantic_rank=i + 1,
                keyword_rank=i + 1,
                title=f"ML Guide Chapter {i + 1}",
                source=f"docs/ml-guide-{i + 1}.md",
                metadata={"source_type": "documentation"},
            )
            for i in range(10)
        ]

        searcher.search.return_value = HybridSearchResponse(
            results=results,
            total_semantic=50,
            total_keyword=45,
            search_time_ms=35.0,
            fusion_method=FusionMethod.RRF,
        )

        return searcher

    @pytest.fixture
    def mock_reranker(self):
        """Mock RerankerService."""
        reranker = AsyncMock(spec=RerankerService)
        reranker.health_check.return_value = True

        async def mock_rerank_fused(query, fused_results, top_k=None):
            # Simulate reranking adjusting scores
            for i, r in enumerate(fused_results):
                r.fused_score = 0.98 - (i * 0.03)  # Reranker adjusts
                r.metadata["reranked"] = True
            return fused_results[:top_k] if top_k else fused_results

        reranker.rerank_fused_results.side_effect = mock_rerank_fused
        return reranker

    @pytest.fixture
    def app(
        self,
        config,
        mock_preprocessor,
        mock_hybrid_searcher,
        mock_reranker,
        jwt_secret,
    ):
        """Create complete test app."""
        app = FastAPI()

        app.state.config = config
        app.state.preprocessor = mock_preprocessor
        app.state.hybrid = mock_hybrid_searcher
        app.state.reranker = mock_reranker
        app.state.acl_filter = ACLFilter(ACLFilterConfig(enabled=False))
        app.state.user_extractor = UserContextExtractor(secret_key=jwt_secret)

        app.include_router(retrieve.router, prefix="/api/v1")
        app.include_router(health.router)

        return app

    @pytest.fixture
    def client(self, app):
        """Test client."""
        return TestClient(app)

    @pytest.fixture
    def auth_header(self, jwt_secret):
        """Generate auth header."""
        token = jwt.encode(
            {
                "sub": str(uuid4()),
                "tenant_id": str(uuid4()),
                "groups": ["users", "ml-team"],
                "roles": ["user", "researcher"],
            },
            jwt_secret,
        )
        return {"Authorization": f"Bearer {token}"}

    def test_complete_retrieval_flow(self, client, auth_header):
        """Test complete retrieval flow with all components."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "machine learning basics",
                "mode": "hybrid",
                "top_k": 5,
                "rerank": True,
            },
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify results
        assert len(data["results"]) <= 5
        assert data["total_results"] >= 0

        # Verify metrics
        assert data["metrics"]["total_ms"] > 0
        assert data["metrics"]["query_preprocessing_ms"] >= 0

        # Verify query info
        assert data["query"] == "machine learning basics"
        assert data["mode"] == "hybrid"

    def test_semantic_only_mode(self, client, auth_header, mock_hybrid_searcher):
        """Test semantic-only mode."""
        # Set up semantic-only response
        mock_hybrid_searcher.search_semantic_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[
                    FusedResult(
                        chunk_id=uuid4(),
                        document_id=uuid4(),
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
            ),
        )

        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "mode": "semantic",
            },
            headers=auth_header,
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "semantic"

    def test_keyword_only_mode(self, client, auth_header, mock_hybrid_searcher):
        """Test keyword-only mode."""
        mock_hybrid_searcher.search_keyword_only = AsyncMock(
            return_value=HybridSearchResponse(
                results=[
                    FusedResult(
                        chunk_id=uuid4(),
                        document_id=uuid4(),
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
            ),
        )

        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "mode": "keyword",
            },
            headers=auth_header,
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "keyword"

    def test_with_filters(self, client, auth_header):
        """Test retrieval with filters."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "filters": {"source_type": "documentation"},
            },
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_without_reranking(self, client, auth_header):
        """Test retrieval without reranking."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "rerank": False,
            },
            headers=auth_header,
        )

        assert response.status_code == 200

    def test_with_min_score(self, client, auth_header):
        """Test retrieval with minimum score threshold."""
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "min_score": 0.5,
            },
            headers=auth_header,
        )

        assert response.status_code == 200
        data = response.json()

        # All results should be above threshold
        for result in data["results"]:
            assert result["score"] >= 0.5

    def test_multi_query_endpoint(self, client, auth_header):
        """Test multi-query endpoint."""
        response = client.post(
            "/api/v1/retrieve/multi",
            json={
                "queries": ["query 1", "query 2"],
                "aggregation": "rrf",
            },
            headers=auth_header,
        )

        assert response.status_code == 200
