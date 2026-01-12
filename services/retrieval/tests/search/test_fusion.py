"""Tests for hybrid fusion algorithms."""

from uuid import uuid4

import pytest
from search.fusion import (
    DistributionBasedScoreFusion,
    FusedResult,
    FusionMethod,
    HybridSearchConfig,
    HybridSearchResponse,
    LinearFusion,
    ReciprocalRankFusion,
)
from search.models import SearchResultItem


@pytest.fixture
def sample_semantic_results():
    """Sample semantic search results."""
    return [
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Document about machine learning",
            score=0.95,
            title="ML Guide",
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Neural networks introduction",
            score=0.85,
            title="NN Basics",
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Deep learning fundamentals",
            score=0.75,
            title="DL Intro",
        ),
    ]


@pytest.fixture
def sample_keyword_results():
    """Sample keyword search results."""
    return [
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Keyword search optimization",
            score=0.90,
            title="Search Guide",
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="BM25 algorithm explained",
            score=0.80,
            title="BM25 Intro",
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Text retrieval methods",
            score=0.70,
            title="Retrieval",
        ),
    ]


class TestFusionMethod:
    """Tests for FusionMethod enum."""

    def test_rrf_value(self):
        """Test RRF enum value."""
        assert FusionMethod.RRF.value == "rrf"

    def test_linear_value(self):
        """Test LINEAR enum value."""
        assert FusionMethod.LINEAR.value == "linear"

    def test_convex_value(self):
        """Test CONVEX enum value."""
        assert FusionMethod.CONVEX.value == "convex"

    def test_dbsf_value(self):
        """Test DBSF enum value."""
        assert FusionMethod.DBSF.value == "dbsf"


class TestFusedResult:
    """Tests for FusedResult model."""

    def test_basic_creation(self):
        """Test basic fused result creation."""
        result = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            fused_score=0.85,
        )
        assert result.fused_score == 0.85
        assert result.semantic_score is None
        assert result.keyword_score is None

    def test_full_creation(self):
        """Test fused result with all fields."""
        result = FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Full content",
            fused_score=0.90,
            semantic_score=0.95,
            semantic_rank=1,
            keyword_score=0.80,
            keyword_rank=2,
            metadata={"key": "value"},
            title="Test Title",
            source="test.md",
        )
        assert result.semantic_score == 0.95
        assert result.semantic_rank == 1
        assert result.keyword_score == 0.80
        assert result.keyword_rank == 2


class TestHybridSearchConfig:
    """Tests for HybridSearchConfig model."""

    def test_defaults(self):
        """Test default configuration values."""
        config = HybridSearchConfig()
        assert config.semantic_weight == 0.7
        assert config.keyword_weight == 0.3
        assert config.fusion_method == FusionMethod.RRF
        assert config.rrf_k == 60
        assert config.top_k == 10
        assert config.semantic_top_k == 50
        assert config.keyword_top_k == 50
        assert config.min_score == 0.0
        assert config.deduplicate is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = HybridSearchConfig(
            semantic_weight=0.8,
            keyword_weight=0.2,
            fusion_method=FusionMethod.LINEAR,
            rrf_k=30,
            top_k=20,
        )
        assert config.semantic_weight == 0.8
        assert config.keyword_weight == 0.2
        assert config.fusion_method == FusionMethod.LINEAR
        assert config.rrf_k == 30
        assert config.top_k == 20

    def test_convex_weights_valid(self):
        """Test convex weights that sum to 1.0."""
        config = HybridSearchConfig(
            semantic_weight=0.6,
            keyword_weight=0.4,
            fusion_method=FusionMethod.CONVEX,
        )
        assert config.semantic_weight == 0.6
        assert config.keyword_weight == 0.4

    def test_convex_weights_invalid(self):
        """Test convex weights that don't sum to 1.0."""
        with pytest.raises(ValueError, match="Convex fusion requires weights to sum to 1.0"):
            HybridSearchConfig(
                semantic_weight=0.7,
                keyword_weight=0.5,  # Sum = 1.2
                fusion_method=FusionMethod.CONVEX,
            )

    def test_weight_bounds(self):
        """Test weight bounds validation."""
        # Valid weights at bounds
        HybridSearchConfig(semantic_weight=0.0, keyword_weight=1.0)
        HybridSearchConfig(semantic_weight=1.0, keyword_weight=0.0)

        # Invalid weights
        with pytest.raises(ValueError):
            HybridSearchConfig(semantic_weight=-0.1, keyword_weight=0.3)

        with pytest.raises(ValueError):
            HybridSearchConfig(semantic_weight=1.1, keyword_weight=0.3)


class TestReciprocalRankFusion:
    """Tests for ReciprocalRankFusion algorithm."""

    def test_default_k(self):
        """Test default k value."""
        rrf = ReciprocalRankFusion()
        assert rrf.k == 60

    def test_custom_k(self):
        """Test custom k value."""
        rrf = ReciprocalRankFusion(k=30)
        assert rrf.k == 30

    def test_fuse_empty_lists(self):
        """Test fusion with empty result lists."""
        rrf = ReciprocalRankFusion()
        results = rrf.fuse([], [], top_k=10)
        assert len(results) == 0

    def test_fuse_semantic_only(self, sample_semantic_results):
        """Test fusion with semantic results only."""
        rrf = ReciprocalRankFusion()
        results = rrf.fuse(sample_semantic_results, [], top_k=10)

        assert len(results) == 3
        # Order should be preserved (by score)
        assert results[0].semantic_rank == 1
        assert results[1].semantic_rank == 2

    def test_fuse_keyword_only(self, sample_keyword_results):
        """Test fusion with keyword results only."""
        rrf = ReciprocalRankFusion()
        results = rrf.fuse([], sample_keyword_results, top_k=10)

        assert len(results) == 3
        assert results[0].keyword_rank == 1

    def test_rrf_score_calculation(self):
        """Test RRF score calculation formula."""
        rrf = ReciprocalRankFusion(k=60)

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.9,
            ),
        ]
        keyword = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.9,
            ),
        ]

        results = rrf.fuse(semantic, keyword, top_k=10)

        # Expected: 1/(60+1) + 1/(60+1) = 2/61
        expected_score = 2 / 61
        assert abs(results[0].fused_score - expected_score) < 0.0001

    def test_rrf_ranking_logic(self):
        """Test RRF ranking favors items in both lists."""
        rrf = ReciprocalRankFusion(k=60)

        chunk_a = uuid4()
        chunk_b = uuid4()
        doc_id = uuid4()

        # A is #1 semantic, #2 keyword
        # B is #2 semantic, #1 keyword
        semantic = [
            SearchResultItem(
                chunk_id=chunk_a, document_id=doc_id, content="A", score=0.9,
            ),
            SearchResultItem(
                chunk_id=chunk_b, document_id=doc_id, content="B", score=0.8,
            ),
        ]
        keyword = [
            SearchResultItem(
                chunk_id=chunk_b, document_id=doc_id, content="B", score=0.9,
            ),
            SearchResultItem(
                chunk_id=chunk_a, document_id=doc_id, content="A", score=0.7,
            ),
        ]

        results = rrf.fuse(semantic, keyword, top_k=10)

        # Both have same RRF score: 1/61 + 1/62
        # With k=60: A gets 1/61 + 1/62, B gets 1/62 + 1/61
        # They should have equal scores
        assert abs(results[0].fused_score - results[1].fused_score) < 0.0001

    def test_rrf_provenance_tracking(self):
        """Test that RRF tracks original scores and ranks."""
        rrf = ReciprocalRankFusion(k=60)

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.9,
            ),
        ]
        keyword = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.8,
            ),
        ]

        results = rrf.fuse(semantic, keyword, top_k=10)

        assert results[0].semantic_score == 0.9
        assert results[0].semantic_rank == 1
        assert results[0].keyword_score == 0.8
        assert results[0].keyword_rank == 1

    def test_rrf_top_k_limit(self):
        """Test top_k limits results."""
        rrf = ReciprocalRankFusion()

        # Create many results
        semantic = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Sem {i}",
                score=0.9 - i * 0.01,
            )
            for i in range(20)
        ]
        keyword = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Kw {i}",
                score=0.9 - i * 0.01,
            )
            for i in range(20)
        ]

        results = rrf.fuse(semantic, keyword, top_k=5)
        assert len(results) == 5


class TestLinearFusion:
    """Tests for LinearFusion algorithm."""

    def test_default_weights(self):
        """Test default weight values."""
        fusion = LinearFusion()
        assert fusion.semantic_weight == 0.7
        assert fusion.keyword_weight == 0.3

    def test_custom_weights(self):
        """Test custom weight values."""
        fusion = LinearFusion(semantic_weight=0.5, keyword_weight=0.5)
        assert fusion.semantic_weight == 0.5
        assert fusion.keyword_weight == 0.5

    def test_linear_score_calculation(self):
        """Test linear score calculation."""
        fusion = LinearFusion(semantic_weight=0.7, keyword_weight=0.3)

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=1.0,
            ),
        ]
        keyword = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.5,
            ),
        ]

        results = fusion.fuse(semantic, keyword, top_k=10)

        # Expected: 0.7 * 1.0 + 0.3 * 0.5 = 0.85
        assert abs(results[0].fused_score - 0.85) < 0.0001

    def test_linear_missing_keyword(self):
        """Test linear fusion when item is not in keyword results."""
        fusion = LinearFusion(semantic_weight=0.7, keyword_weight=0.3)

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=1.0,
            ),
        ]
        keyword = []

        results = fusion.fuse(semantic, keyword, top_k=10)

        # Expected: 0.7 * 1.0 + 0.3 * 0.0 = 0.7
        assert abs(results[0].fused_score - 0.7) < 0.0001

    def test_linear_missing_semantic(self):
        """Test linear fusion when item is not in semantic results."""
        fusion = LinearFusion(semantic_weight=0.7, keyword_weight=0.3)

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = []
        keyword = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=1.0,
            ),
        ]

        results = fusion.fuse(semantic, keyword, top_k=10)

        # Expected: 0.7 * 0.0 + 0.3 * 1.0 = 0.3
        assert abs(results[0].fused_score - 0.3) < 0.0001

    def test_linear_preserves_metadata(self):
        """Test linear fusion preserves metadata."""
        fusion = LinearFusion()

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id,
                document_id=doc_id,
                content="A",
                score=0.9,
                metadata={"key": "value"},
                title="Test",
                source="test.md",
            ),
        ]

        results = fusion.fuse(semantic, [], top_k=10)

        assert results[0].metadata == {"key": "value"}
        assert results[0].title == "Test"
        assert results[0].source == "test.md"


class TestDistributionBasedScoreFusion:
    """Tests for DistributionBasedScoreFusion algorithm."""

    def test_default_weights(self):
        """Test default weight values."""
        dbsf = DistributionBasedScoreFusion()
        assert dbsf.semantic_weight == 0.7
        assert dbsf.keyword_weight == 0.3

    def test_dbsf_normalization(self):
        """Test DBSF normalizes scores."""
        dbsf = DistributionBasedScoreFusion()

        # Create results with different score distributions
        semantic = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Sem {i}",
                score=0.9 - i * 0.1,
            )
            for i in range(3)
        ]
        keyword = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Kw {i}",
                score=20 - i * 5,  # Much higher range (BM25-like)
            )
            for i in range(3)
        ]

        results = dbsf.fuse(semantic, keyword, top_k=10)

        # All fused scores should be in [0, 1] due to sigmoid
        for result in results:
            assert 0.0 <= result.fused_score <= 1.0

    def test_dbsf_empty_lists(self):
        """Test DBSF with empty result lists."""
        dbsf = DistributionBasedScoreFusion()
        results = dbsf.fuse([], [], top_k=10)
        assert len(results) == 0

    def test_dbsf_single_result(self):
        """Test DBSF with single result."""
        dbsf = DistributionBasedScoreFusion()

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.9,
            ),
        ]

        results = dbsf.fuse(semantic, [], top_k=10)

        assert len(results) == 1
        assert 0.0 <= results[0].fused_score <= 1.0

    def test_dbsf_preserves_original_scores(self):
        """Test DBSF preserves original scores in result."""
        dbsf = DistributionBasedScoreFusion()

        chunk_id = uuid4()
        doc_id = uuid4()

        semantic = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=0.9,
            ),
        ]
        keyword = [
            SearchResultItem(
                chunk_id=chunk_id, document_id=doc_id, content="A", score=15.5,
            ),
        ]

        results = dbsf.fuse(semantic, keyword, top_k=10)

        assert results[0].semantic_score == 0.9
        assert results[0].keyword_score == 15.5


class TestHybridSearchResponse:
    """Tests for HybridSearchResponse model."""

    def test_basic_creation(self):
        """Test basic response creation."""
        response = HybridSearchResponse(
            results=[],
            total_semantic=10,
            total_keyword=15,
            search_time_ms=50.5,
            fusion_method=FusionMethod.RRF,
        )
        assert response.total_semantic == 10
        assert response.total_keyword == 15
        assert response.search_time_ms == 50.5
        assert response.fusion_method == FusionMethod.RRF

    def test_with_results(self):
        """Test response with fused results."""
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
        ]

        response = HybridSearchResponse(
            results=results,
            total_semantic=5,
            total_keyword=5,
            search_time_ms=100.0,
            fusion_method=FusionMethod.LINEAR,
        )

        assert len(response.results) == 2
        assert response.fusion_method == FusionMethod.LINEAR
