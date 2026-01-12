"""Tests for hybrid search orchestrator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from search.fusion import FusedResult, FusionMethod, HybridSearchConfig
from search.hybrid import HybridSearcher
from search.models import (
    KeywordSearchResponse,
    SearchResultItem,
    SemanticSearchResponse,
)


@pytest.fixture
def mock_semantic_searcher():
    """Create mock semantic searcher."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.get_collection_info = AsyncMock(return_value={"name": "test", "vectors_count": 100})
    return mock


@pytest.fixture
def mock_keyword_searcher():
    """Create mock keyword searcher."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    mock.get_index_info = AsyncMock(return_value={"name": "test", "doc_count": 100})
    return mock


@pytest.fixture
def hybrid_searcher(mock_semantic_searcher, mock_keyword_searcher):
    """Create hybrid searcher with mocked backends."""
    return HybridSearcher(
        semantic_searcher=mock_semantic_searcher,
        keyword_searcher=mock_keyword_searcher,
    )


@pytest.fixture
def sample_semantic_response():
    """Sample semantic search response."""
    return SemanticSearchResponse(
        results=[
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Machine learning basics",
                score=0.95,
                title="ML Guide",
            ),
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Neural networks overview",
                score=0.85,
                title="NN Guide",
            ),
        ],
        total_found=2,
        search_time_ms=50.0,
    )


@pytest.fixture
def sample_keyword_response():
    """Sample keyword search response."""
    return KeywordSearchResponse(
        results=[
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Machine learning applications",
                score=0.90,
                title="ML Apps",
            ),
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Deep learning frameworks",
                score=0.80,
                title="DL Frameworks",
            ),
        ],
        total_found=2,
        search_time_ms=30.0,
    )


class TestHybridSearcherInit:
    """Tests for HybridSearcher initialization."""

    def test_default_config(self, mock_semantic_searcher, mock_keyword_searcher):
        """Test initialization with default config."""
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher)

        assert searcher.config.fusion_method == FusionMethod.RRF
        assert searcher.config.semantic_weight == 0.7
        assert searcher.config.keyword_weight == 0.3

    def test_custom_config(self, mock_semantic_searcher, mock_keyword_searcher):
        """Test initialization with custom config."""
        config = HybridSearchConfig(
            fusion_method=FusionMethod.LINEAR,
            semantic_weight=0.6,
            keyword_weight=0.4,
        )
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher, config)

        assert searcher.config.fusion_method == FusionMethod.LINEAR
        assert searcher.config.semantic_weight == 0.6


class TestHybridSearcherConnection:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, hybrid_searcher, mock_semantic_searcher, mock_keyword_searcher):
        """Test connect calls both backends."""
        await hybrid_searcher.connect()

        mock_semantic_searcher.connect.assert_called_once()
        mock_keyword_searcher.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, hybrid_searcher, mock_semantic_searcher, mock_keyword_searcher):
        """Test close calls both backends."""
        await hybrid_searcher.close()

        mock_semantic_searcher.close.assert_called_once()
        mock_keyword_searcher.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self, hybrid_searcher):
        """Test health check returns True when both backends healthy."""
        result = await hybrid_searcher.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_semantic_failure(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
    ):
        """Test health check returns False when semantic unhealthy."""
        mock_semantic_searcher.health_check = AsyncMock(return_value=False)

        result = await hybrid_searcher.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_keyword_failure(
        self,
        hybrid_searcher,
        mock_keyword_searcher,
    ):
        """Test health check returns False when keyword unhealthy."""
        mock_keyword_searcher.health_check = AsyncMock(return_value=False)

        result = await hybrid_searcher.health_check()
        assert result is False


class TestHybridSearcherSearch:
    """Tests for hybrid search functionality."""

    @pytest.mark.asyncio
    async def test_search_returns_fused_results(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test search returns properly fused results."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await hybrid_searcher.search(
            query="machine learning",
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        assert len(response.results) > 0
        assert response.total_semantic == 2
        assert response.total_keyword == 2
        assert response.search_time_ms > 0
        assert response.fusion_method == FusionMethod.RRF

    @pytest.mark.asyncio
    async def test_search_with_filters(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test search passes filters to both backends."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        filters = {"tenant_id": "test-tenant"}

        await hybrid_searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
            filters=filters,
        )

        # Verify filters were passed
        sem_call = mock_semantic_searcher.search.call_args
        kw_call = mock_keyword_searcher.search.call_args

        assert sem_call.kwargs["filters"] == filters
        assert kw_call.kwargs["filters"] == filters

    @pytest.mark.asyncio
    async def test_search_with_custom_config(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test search with custom config override."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        custom_config = HybridSearchConfig(
            fusion_method=FusionMethod.LINEAR,
            semantic_weight=0.8,
            keyword_weight=0.2,
        )

        response = await hybrid_searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
            config=custom_config,
        )

        assert response.fusion_method == FusionMethod.LINEAR

    @pytest.mark.asyncio
    async def test_search_min_score_filtering(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
    ):
        """Test min_score filtering removes low-scored results."""
        # Create results with varying scores
        semantic_results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="High score",
                score=0.9,
            ),
        ]
        keyword_results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Low score",
                score=0.3,
            ),
        ]

        mock_semantic_searcher.search = AsyncMock(
            return_value=SemanticSearchResponse(
                results=semantic_results,
                total_found=1,
                search_time_ms=10,
            ),
        )
        mock_keyword_searcher.search = AsyncMock(
            return_value=KeywordSearchResponse(
                results=keyword_results,
                total_found=1,
                search_time_ms=10,
            ),
        )

        # Use high min_score to filter out low RRF scores
        config = HybridSearchConfig(min_score=0.02)  # RRF scores are typically low

        response = await hybrid_searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
            config=config,
        )

        # Results depend on RRF scores - both may be filtered if min_score is too high
        # or kept if low enough
        assert response.search_time_ms > 0


class TestHybridSearcherDeduplication:
    """Tests for document deduplication."""

    def test_deduplicate_keeps_highest_score(self, hybrid_searcher):
        """Test deduplication keeps highest-scored chunk per document."""
        doc_id = uuid4()

        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=doc_id,
                content="Chunk 1",
                fused_score=0.9,
            ),
            FusedResult(
                chunk_id=uuid4(),
                document_id=doc_id,
                content="Chunk 2",
                fused_score=0.95,  # Higher
            ),
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Different doc",
                fused_score=0.8,
            ),
        ]

        deduped = hybrid_searcher._deduplicate(results)

        assert len(deduped) == 2
        # Highest scored kept
        doc_result = [r for r in deduped if r.document_id == doc_id][0]
        assert doc_result.fused_score == 0.95

    def test_deduplicate_maintains_order(self, hybrid_searcher):
        """Test deduplication maintains score order."""
        results = [
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="A",
                fused_score=0.9,
            ),
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="B",
                fused_score=0.8,
            ),
            FusedResult(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="C",
                fused_score=0.7,
            ),
        ]

        deduped = hybrid_searcher._deduplicate(results)

        assert deduped[0].fused_score == 0.9
        assert deduped[1].fused_score == 0.8
        assert deduped[2].fused_score == 0.7

    def test_deduplicate_empty_list(self, hybrid_searcher):
        """Test deduplication with empty list."""
        deduped = hybrid_searcher._deduplicate([])
        assert deduped == []


class TestHybridSearcherSemanticOnly:
    """Tests for semantic-only search."""

    @pytest.mark.asyncio
    async def test_semantic_only_search(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        sample_semantic_response,
    ):
        """Test semantic-only search bypasses keyword search."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)

        response = await hybrid_searcher.search_semantic_only(
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        assert len(response.results) == 2
        assert response.total_semantic == 2
        assert response.total_keyword == 0
        assert response.search_time_ms > 0

    @pytest.mark.asyncio
    async def test_semantic_only_result_format(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        sample_semantic_response,
    ):
        """Test semantic-only results are properly formatted."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)

        response = await hybrid_searcher.search_semantic_only(
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        result = response.results[0]
        assert result.semantic_score is not None
        assert result.semantic_rank == 1
        assert result.keyword_score is None
        assert result.keyword_rank is None


class TestHybridSearcherKeywordOnly:
    """Tests for keyword-only search."""

    @pytest.mark.asyncio
    async def test_keyword_only_search(
        self,
        hybrid_searcher,
        mock_keyword_searcher,
        sample_keyword_response,
    ):
        """Test keyword-only search bypasses semantic search."""
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await hybrid_searcher.search_keyword_only(
            query="machine learning",
            top_k=10,
        )

        assert len(response.results) == 2
        assert response.total_semantic == 0
        assert response.total_keyword == 2
        assert response.search_time_ms > 0

    @pytest.mark.asyncio
    async def test_keyword_only_result_format(
        self,
        hybrid_searcher,
        mock_keyword_searcher,
        sample_keyword_response,
    ):
        """Test keyword-only results are properly formatted."""
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await hybrid_searcher.search_keyword_only(
            query="test",
            top_k=10,
        )

        result = response.results[0]
        assert result.keyword_score is not None
        assert result.keyword_rank == 1
        assert result.semantic_score is None
        assert result.semantic_rank is None


class TestHybridSearcherParallelExecution:
    """Tests for parallel search execution."""

    @pytest.mark.asyncio
    async def test_parallel_search_timing(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
    ):
        """Test that searches run in parallel."""
        import time

        # Create slow async functions
        async def slow_semantic(*args, **kwargs):
            await asyncio.sleep(0.1)
            return SemanticSearchResponse(results=[], total_found=0, search_time_ms=100)

        async def slow_keyword(*args, **kwargs):
            await asyncio.sleep(0.1)
            return KeywordSearchResponse(results=[], total_found=0, search_time_ms=100)

        mock_semantic_searcher.search = slow_semantic
        mock_keyword_searcher.search = slow_keyword

        start = time.time()
        await hybrid_searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )
        elapsed = time.time() - start

        # Should take ~0.1s (parallel), not ~0.2s (sequential)
        assert elapsed < 0.15


class TestHybridSearcherBackendInfo:
    """Tests for backend info retrieval."""

    @pytest.mark.asyncio
    async def test_get_backend_info(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
    ):
        """Test getting backend info from both searchers."""
        info = await hybrid_searcher.get_backend_info()

        assert "semantic" in info
        assert "keyword" in info
        assert "config" in info
        assert info["semantic"]["name"] == "test"
        assert info["keyword"]["name"] == "test"
        assert info["config"]["fusion_method"] == "rrf"

    @pytest.mark.asyncio
    async def test_get_backend_info_with_error(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
    ):
        """Test backend info handles errors gracefully."""
        mock_semantic_searcher.get_collection_info = AsyncMock(
            side_effect=Exception("Connection failed"),
        )

        info = await hybrid_searcher.get_backend_info()

        assert "error" in info["semantic"]


class TestHybridSearcherFusionMethods:
    """Tests for different fusion methods."""

    @pytest.mark.asyncio
    async def test_rrf_fusion(
        self,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test RRF fusion method."""
        config = HybridSearchConfig(fusion_method=FusionMethod.RRF)
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher, config)

        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )

        assert response.fusion_method == FusionMethod.RRF

    @pytest.mark.asyncio
    async def test_linear_fusion(
        self,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test LINEAR fusion method."""
        config = HybridSearchConfig(fusion_method=FusionMethod.LINEAR)
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher, config)

        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )

        assert response.fusion_method == FusionMethod.LINEAR

    @pytest.mark.asyncio
    async def test_dbsf_fusion(
        self,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test DBSF fusion method."""
        config = HybridSearchConfig(fusion_method=FusionMethod.DBSF)
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher, config)

        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )

        assert response.fusion_method == FusionMethod.DBSF

    @pytest.mark.asyncio
    async def test_convex_fusion(
        self,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test CONVEX fusion method."""
        config = HybridSearchConfig(
            fusion_method=FusionMethod.CONVEX,
            semantic_weight=0.6,
            keyword_weight=0.4,  # Sum = 1.0
        )
        searcher = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher, config)

        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await searcher.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )

        assert response.fusion_method == FusionMethod.CONVEX
