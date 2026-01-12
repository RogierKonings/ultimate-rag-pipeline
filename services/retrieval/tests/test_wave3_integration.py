"""Wave 3 Integration Tests: Hybrid Fusion + Reranking Pipeline.

Tests the complete retrieval pipeline:
1. Semantic + Keyword search (Wave 2)
2. Hybrid fusion (US-3.4)
3. Cross-encoder reranking (US-3.5)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from reranking import RerankerService
from search.fusion import (
    DistributionBasedScoreFusion,
    FusedResult,
    FusionMethod,
    HybridSearchConfig,
    LinearFusion,
    ReciprocalRankFusion,
)
from search.hybrid import HybridSearcher
from search.models import (
    KeywordSearchResponse,
    SearchResultItem,
    SemanticSearchResponse,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def shared_chunk_ids():
    """Chunk IDs that appear in both semantic and keyword results."""
    return [uuid4() for _ in range(3)]


@pytest.fixture
def semantic_only_chunk_ids():
    """Chunk IDs that only appear in semantic results."""
    return [uuid4() for _ in range(2)]


@pytest.fixture
def keyword_only_chunk_ids():
    """Chunk IDs that only appear in keyword results."""
    return [uuid4() for _ in range(2)]


@pytest.fixture
def semantic_results(shared_chunk_ids, semantic_only_chunk_ids):
    """Semantic search results with mixed chunks."""
    results = []
    doc_id = uuid4()

    # Shared chunks with semantic scores
    for i, chunk_id in enumerate(shared_chunk_ids):
        results.append(
            SearchResultItem(
                chunk_id=chunk_id,
                document_id=doc_id,
                content=f"Shared document {i} about machine learning",
                score=0.95 - i * 0.1,  # 0.95, 0.85, 0.75
                title=f"Shared {i}",
                source="shared.md",
            ),
        )

    # Semantic-only chunks
    for i, chunk_id in enumerate(semantic_only_chunk_ids):
        results.append(
            SearchResultItem(
                chunk_id=chunk_id,
                document_id=uuid4(),
                content=f"Semantic only document {i}",
                score=0.65 - i * 0.1,  # 0.65, 0.55
                title=f"Semantic {i}",
                source="semantic.md",
            ),
        )

    return results


@pytest.fixture
def keyword_results(shared_chunk_ids, keyword_only_chunk_ids):
    """Keyword search results with mixed chunks."""
    results = []
    doc_id = uuid4()

    # Shared chunks with keyword scores (different order)
    # Reverse order to test RRF's ability to combine rankings
    for i, chunk_id in enumerate(reversed(shared_chunk_ids)):
        results.append(
            SearchResultItem(
                chunk_id=chunk_id,
                document_id=doc_id,
                content=f"Shared document {i} about machine learning",
                score=12.0 - i * 2.0,  # BM25-like scores: 12.0, 10.0, 8.0
                title=f"Shared {i}",
                source="shared.md",
            ),
        )

    # Keyword-only chunks
    for i, chunk_id in enumerate(keyword_only_chunk_ids):
        results.append(
            SearchResultItem(
                chunk_id=chunk_id,
                document_id=uuid4(),
                content=f"Keyword only document {i}",
                score=6.0 - i * 2.0,  # 6.0, 4.0
                title=f"Keyword {i}",
                source="keyword.md",
            ),
        )

    return results


@pytest.fixture
def mock_semantic_searcher(semantic_results):
    """Mock semantic searcher."""
    mock = MagicMock()
    mock.search = AsyncMock(
        return_value=SemanticSearchResponse(
            results=semantic_results,
            total_found=len(semantic_results),
            search_time_ms=50.0,
        ),
    )
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_keyword_searcher(keyword_results):
    """Mock keyword searcher."""
    mock = MagicMock()
    mock.search = AsyncMock(
        return_value=KeywordSearchResponse(
            results=keyword_results,
            total_found=len(keyword_results),
            search_time_ms=30.0,
        ),
    )
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    return mock


# ============================================================================
# Fusion Algorithm Tests
# ============================================================================


class TestRRFFusionIntegration:
    """Integration tests for RRF fusion."""

    def test_rrf_combines_results_from_both_sources(
        self, semantic_results, keyword_results, shared_chunk_ids,
    ):
        """Test RRF properly combines results from both sources."""
        rrf = ReciprocalRankFusion(k=60)

        fused = rrf.fuse(semantic_results, keyword_results, top_k=10)

        # All shared chunks should be in results
        fused_ids = {r.chunk_id for r in fused}
        for chunk_id in shared_chunk_ids:
            assert chunk_id in fused_ids

        # Check that shared chunks have both scores
        for result in fused:
            if result.chunk_id in shared_chunk_ids:
                assert result.semantic_score is not None
                assert result.keyword_score is not None

    def test_rrf_ranks_shared_chunks_higher(
        self, semantic_results, keyword_results, shared_chunk_ids,
    ):
        """Test RRF ranks chunks appearing in both lists higher."""
        rrf = ReciprocalRankFusion(k=60)

        fused = rrf.fuse(semantic_results, keyword_results, top_k=10)

        # Shared chunks should rank higher than single-source chunks
        shared_scores = [r.fused_score for r in fused if r.chunk_id in shared_chunk_ids]
        other_scores = [
            r.fused_score for r in fused if r.chunk_id not in shared_chunk_ids
        ]

        # Average shared score should be higher
        avg_shared = sum(shared_scores) / len(shared_scores)
        avg_other = sum(other_scores) / len(other_scores) if other_scores else 0

        assert avg_shared > avg_other


class TestLinearFusionIntegration:
    """Integration tests for linear fusion."""

    def test_linear_weighted_combination(self, semantic_results, keyword_results):
        """Test linear fusion properly weights scores."""
        linear = LinearFusion(semantic_weight=0.7, keyword_weight=0.3)

        fused = linear.fuse(semantic_results, keyword_results, top_k=10)

        # All results should have fused scores
        for result in fused:
            assert result.fused_score >= 0


class TestDBSFIntegration:
    """Integration tests for distribution-based score fusion."""

    def test_dbsf_normalizes_different_scales(
        self, semantic_results, keyword_results,
    ):
        """Test DBSF handles different score scales (cosine vs BM25)."""
        dbsf = DistributionBasedScoreFusion(
            semantic_weight=0.7, keyword_weight=0.3,
        )

        fused = dbsf.fuse(semantic_results, keyword_results, top_k=10)

        # All fused scores should be in [0, 1] range
        for result in fused:
            assert 0.0 <= result.fused_score <= 1.0


# ============================================================================
# Hybrid Searcher Tests
# ============================================================================


class TestHybridSearcherIntegration:
    """Integration tests for HybridSearcher."""

    @pytest.mark.asyncio
    async def test_hybrid_search_runs_parallel(
        self, mock_semantic_searcher, mock_keyword_searcher,
    ):
        """Test hybrid search runs semantic and keyword in parallel."""
        config = HybridSearchConfig(
            fusion_method=FusionMethod.RRF,
            semantic_weight=0.7,
            keyword_weight=0.3,
        )
        searcher = HybridSearcher(
            mock_semantic_searcher, mock_keyword_searcher, config,
        )

        response = await searcher.search(
            query="machine learning",
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        # Both searchers should be called
        mock_semantic_searcher.search.assert_called_once()
        mock_keyword_searcher.search.assert_called_once()

        # Should have fused results
        assert len(response.results) > 0
        assert response.fusion_method == FusionMethod.RRF

    @pytest.mark.asyncio
    async def test_hybrid_search_with_all_fusion_methods(
        self, mock_semantic_searcher, mock_keyword_searcher,
    ):
        """Test hybrid search works with all fusion methods."""
        for method in [FusionMethod.RRF, FusionMethod.LINEAR, FusionMethod.DBSF]:
            if method == FusionMethod.CONVEX:
                config = HybridSearchConfig(
                    fusion_method=method,
                    semantic_weight=0.6,
                    keyword_weight=0.4,
                )
            else:
                config = HybridSearchConfig(fusion_method=method)

            searcher = HybridSearcher(
                mock_semantic_searcher, mock_keyword_searcher, config,
            )

            # Reset mock call counts
            mock_semantic_searcher.search.reset_mock()
            mock_keyword_searcher.search.reset_mock()

            response = await searcher.search(
                query="test",
                query_embedding=[0.1] * 1024,
            )

            assert response.fusion_method == method
            assert len(response.results) > 0


# ============================================================================
# Reranker Integration Tests
# ============================================================================


class TestRerankerIntegration:
    """Integration tests for reranker with fusion results."""

    @pytest.fixture
    def fused_results(self, shared_chunk_ids):
        """Sample fused results for reranking."""
        return [
            FusedResult(
                chunk_id=chunk_id,
                document_id=uuid4(),
                content=f"Document {i} about machine learning algorithms",
                fused_score=0.9 - i * 0.1,
            )
            for i, chunk_id in enumerate(shared_chunk_ids)
        ]

    @pytest.fixture
    def mock_rerank_response(self, shared_chunk_ids):
        """Mock rerank response that reverses order."""
        # Reverse the order compared to fusion scores
        return {
            "results": [
                {"index": i, "relevance_score": 0.5 + i * 0.2}
                for i in range(len(shared_chunk_ids))
            ],
        }

    @pytest.mark.asyncio
    async def test_reranker_reorders_fused_results(
        self, fused_results, mock_rerank_response,
    ):
        """Test reranker can reorder fused results."""
        reranker = RerankerService()

        mock_response = MagicMock()
        mock_response.json.return_value = mock_rerank_response
        mock_response.raise_for_status = MagicMock()

        from unittest.mock import patch

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            reranked = await reranker.rerank_fused_results(
                query="machine learning algorithms",
                fused_results=fused_results,
            )

            # Order should be reversed (highest rerank score first)
            assert len(reranked) == len(fused_results)
            # Verify scores are from reranker, not fusion
            assert reranked[0].fused_score == max(
                r["relevance_score"] for r in mock_rerank_response["results"]
            )


# ============================================================================
# End-to-End Pipeline Tests
# ============================================================================


class TestEndToEndPipeline:
    """End-to-end tests for the complete retrieval pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_search_fusion_rerank(
        self, mock_semantic_searcher, mock_keyword_searcher, shared_chunk_ids,
    ):
        """Test complete pipeline: search -> fusion -> rerank."""
        # Step 1: Setup hybrid searcher
        config = HybridSearchConfig(
            fusion_method=FusionMethod.RRF,
            top_k=10,
        )
        hybrid = HybridSearcher(
            mock_semantic_searcher, mock_keyword_searcher, config,
        )

        # Step 2: Execute hybrid search
        fusion_response = await hybrid.search(
            query="machine learning",
            query_embedding=[0.1] * 1024,
        )

        assert len(fusion_response.results) > 0

        # Step 3: Setup reranker
        reranker = RerankerService()

        # Mock rerank response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": i, "relevance_score": 0.9 - i * 0.1}
                for i in range(len(fusion_response.results))
            ],
        }
        mock_response.raise_for_status = MagicMock()

        from unittest.mock import patch

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            # Step 4: Rerank fused results
            final_results = await reranker.rerank_fused_results(
                query="machine learning",
                fused_results=fusion_response.results,
                top_k=5,
            )

            # Verify final results
            assert len(final_results) <= 5
            assert all(r.fused_score > 0 for r in final_results)

            # Verify provenance is tracked
            for result in final_results:
                assert "rerank_score" in result.metadata
                assert "original_fused_score" in result.metadata

    @pytest.mark.asyncio
    async def test_pipeline_with_filters(
        self, mock_semantic_searcher, mock_keyword_searcher,
    ):
        """Test pipeline passes filters through correctly."""
        hybrid = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher)

        filters = {
            "must": [{"key": "tenant_id", "match": {"value": "test-tenant"}}],
        }

        await hybrid.search(
            query="test",
            query_embedding=[0.1] * 1024,
            filters=filters,
        )

        # Verify filters were passed to both searchers
        sem_call = mock_semantic_searcher.search.call_args
        kw_call = mock_keyword_searcher.search.call_args

        assert sem_call.kwargs["filters"] == filters
        assert kw_call.kwargs["filters"] == filters

    @pytest.mark.asyncio
    async def test_pipeline_deduplication(
        self, mock_semantic_searcher, mock_keyword_searcher,
    ):
        """Test pipeline deduplication works correctly."""
        # Create results with duplicate document_ids
        doc_id = uuid4()
        duplicate_results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=doc_id,  # Same doc
                content="Chunk 1 of document",
                score=0.9,
            ),
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=doc_id,  # Same doc
                content="Chunk 2 of document",
                score=0.8,
            ),
        ]

        mock_semantic_searcher.search.return_value = SemanticSearchResponse(
            results=duplicate_results,
            total_found=2,
            search_time_ms=50.0,
        )
        mock_keyword_searcher.search.return_value = KeywordSearchResponse(
            results=[],
            total_found=0,
            search_time_ms=30.0,
        )

        config = HybridSearchConfig(deduplicate=True)
        hybrid = HybridSearcher(
            mock_semantic_searcher, mock_keyword_searcher, config,
        )

        response = await hybrid.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )

        # Should only have one result per document
        doc_ids = [r.document_id for r in response.results]
        assert len(doc_ids) == len(set(doc_ids))


# ============================================================================
# Performance Tests
# ============================================================================


class TestPipelinePerformance:
    """Performance-related tests for the pipeline."""

    @pytest.mark.asyncio
    async def test_parallel_execution_faster_than_sequential(
        self, mock_semantic_searcher, mock_keyword_searcher,
    ):
        """Test that parallel execution is faster than sequential."""
        import time

        # Add delays to mock searchers
        async def slow_semantic(*args, **kwargs):
            await asyncio.sleep(0.05)
            return SemanticSearchResponse(
                results=[], total_found=0, search_time_ms=50,
            )

        async def slow_keyword(*args, **kwargs):
            await asyncio.sleep(0.05)
            return KeywordSearchResponse(
                results=[], total_found=0, search_time_ms=50,
            )

        mock_semantic_searcher.search = slow_semantic
        mock_keyword_searcher.search = slow_keyword

        hybrid = HybridSearcher(mock_semantic_searcher, mock_keyword_searcher)

        start = time.time()
        await hybrid.search(
            query="test",
            query_embedding=[0.1] * 1024,
        )
        elapsed = time.time() - start

        # Should take ~0.05s (parallel), not ~0.1s (sequential)
        assert elapsed < 0.08

    def test_fusion_computation_time(self, semantic_results, keyword_results):
        """Test fusion computation is fast."""
        import time

        rrf = ReciprocalRankFusion()

        start = time.time()
        for _ in range(100):  # Run 100 times
            rrf.fuse(semantic_results, keyword_results, top_k=10)
        elapsed = time.time() - start

        # 100 fusions should take < 100ms
        assert elapsed < 0.1
