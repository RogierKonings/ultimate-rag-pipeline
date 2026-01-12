"""Tests for search models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from search.models import (
    AnalyzerConfig,
    KeywordSearchRequest,
    KeywordSearchResponse,
    OpenSearchConfig,
    QdrantConfig,
    ScoreNormalizer,
    SearchResultItem,
    SemanticSearchRequest,
    SemanticSearchResponse,
)


class TestSearchResultItem:
    """Tests for SearchResultItem model."""

    def test_basic_creation(self):
        """Test basic result creation."""
        item = SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            score=0.85,
        )
        assert item.content == "Test content"
        assert item.score == 0.85
        assert item.metadata == {}
        assert item.highlights is None

    def test_full_creation(self):
        """Test result with all fields."""
        chunk_id = uuid4()
        document_id = uuid4()
        now = datetime.now(tz=UTC)

        item = SearchResultItem(
            chunk_id=chunk_id,
            document_id=document_id,
            content="Full content",
            score=0.95,
            metadata={"key": "value"},
            title="Test Title",
            source="test.md",
            chunk_index=2,
            total_chunks=5,
            created_at=now,
            updated_at=now,
            highlights={"content": ["<mark>test</mark>"]},
        )

        assert item.chunk_id == chunk_id
        assert item.document_id == document_id
        assert item.title == "Test Title"
        assert item.source == "test.md"
        assert item.chunk_index == 2
        assert item.total_chunks == 5
        assert item.created_at == now
        assert item.highlights == {"content": ["<mark>test</mark>"]}

    def test_score_validation(self):
        """Test score must be >= 0 (unbounded BM25 scores allowed)."""
        # Valid scores (0 and positive)
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="",
            score=0.0,
        )
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="",
            score=1.0,
        )
        # BM25 can have high scores
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="",
            score=15.5,
        )

        # Invalid score (negative)
        with pytest.raises(ValueError):
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="",
                score=-0.1,
            )


class TestSemanticSearchRequest:
    """Tests for SemanticSearchRequest model."""

    def test_defaults(self):
        """Test default values."""
        request = SemanticSearchRequest(
            query_embedding=[0.1] * 1024,
        )
        assert request.top_k == 10
        assert request.score_threshold == 0.0
        assert request.filters is None
        assert request.include_metadata is True
        assert request.include_vectors is False

    def test_custom_values(self):
        """Test custom values."""
        request = SemanticSearchRequest(
            query_embedding=[0.1] * 1024,
            top_k=50,
            score_threshold=0.5,
            filters={"tenant_id": "123"},
            include_metadata=False,
            include_vectors=True,
        )
        assert request.top_k == 50
        assert request.score_threshold == 0.5
        assert request.filters == {"tenant_id": "123"}

    def test_top_k_validation(self):
        """Test top_k validation."""
        with pytest.raises(ValueError):
            SemanticSearchRequest(query_embedding=[0.1], top_k=0)

        with pytest.raises(ValueError):
            SemanticSearchRequest(query_embedding=[0.1], top_k=101)


class TestSemanticSearchResponse:
    """Tests for SemanticSearchResponse model."""

    def test_empty_response(self):
        """Test empty response."""
        response = SemanticSearchResponse(
            results=[],
            total_found=0,
            search_time_ms=5.0,
        )
        assert len(response.results) == 0
        assert response.total_found == 0
        assert response.query_id is None

    def test_with_results(self):
        """Test response with results."""
        query_id = uuid4()
        results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="Test",
                score=0.9,
            ),
        ]

        response = SemanticSearchResponse(
            results=results,
            total_found=1,
            search_time_ms=25.5,
            query_id=query_id,
        )

        assert len(response.results) == 1
        assert response.total_found == 1
        assert response.search_time_ms == 25.5
        assert response.query_id == query_id


class TestKeywordSearchRequest:
    """Tests for KeywordSearchRequest model."""

    def test_defaults(self):
        """Test default values."""
        request = KeywordSearchRequest(query="test query")
        assert request.top_k == 10
        assert request.filters is None
        assert request.fields == ["content", "title"]
        assert request.field_boosts == {"title": 2.0, "content": 1.0}
        assert request.highlight is True
        assert request.min_score == 0.0

    def test_custom_values(self):
        """Test custom values."""
        request = KeywordSearchRequest(
            query="machine learning",
            top_k=20,
            fields=["content", "title", "description"],
            field_boosts={"title": 3.0, "content": 1.0, "description": 1.5},
            highlight=False,
            min_score=5.0,
        )
        assert request.query == "machine learning"
        assert request.top_k == 20
        assert "description" in request.fields


class TestKeywordSearchResponse:
    """Tests for KeywordSearchResponse model."""

    def test_response_creation(self):
        """Test response creation."""
        response = KeywordSearchResponse(
            results=[],
            total_found=100,
            search_time_ms=15.0,
        )
        assert response.total_found == 100
        assert response.search_time_ms == 15.0


class TestQdrantConfig:
    """Tests for QdrantConfig model."""

    def test_defaults(self):
        """Test default values."""
        config = QdrantConfig()
        assert config.url == "http://localhost:6333"
        assert config.api_key is None
        assert config.collection_name == "documents"
        assert config.timeout == 30.0
        assert config.hnsw_ef == 128
        assert config.exact_search is False
        assert config.use_quantization is True
        assert config.quantization_rescore is True

    def test_custom_values(self):
        """Test custom values."""
        config = QdrantConfig(
            url="http://qdrant:6333",
            api_key="secret",
            collection_name="my_docs",
            hnsw_ef=256,
            exact_search=True,
        )
        assert config.url == "http://qdrant:6333"
        assert config.api_key == "secret"
        assert config.collection_name == "my_docs"
        assert config.hnsw_ef == 256
        assert config.exact_search is True


class TestOpenSearchConfig:
    """Tests for OpenSearchConfig model."""

    def test_defaults(self):
        """Test default values."""
        config = OpenSearchConfig()
        assert config.url == "http://localhost:9200"
        assert config.username is None
        assert config.password is None
        assert config.index_name == "documents"
        assert config.use_ssl is False
        assert config.verify_certs is True
        assert config.default_operator == "OR"
        assert config.fuzziness == "AUTO"
        assert config.analyzer == "standard"

    def test_custom_values(self):
        """Test custom values."""
        config = OpenSearchConfig(
            url="https://opensearch:9200",
            username="admin",
            password="secret",
            use_ssl=True,
            default_operator="AND",
            fuzziness="2",
        )
        assert config.url == "https://opensearch:9200"
        assert config.username == "admin"
        assert config.use_ssl is True
        assert config.default_operator == "AND"


class TestScoreNormalizer:
    """Tests for ScoreNormalizer."""

    def test_min_max_empty(self):
        """Test min-max with empty list."""
        result = ScoreNormalizer.min_max([])
        assert result == []

    def test_min_max_single(self):
        """Test min-max with single value."""
        result = ScoreNormalizer.min_max([0.5])
        assert result == [1.0]

    def test_min_max_identical(self):
        """Test min-max with identical values."""
        result = ScoreNormalizer.min_max([0.5, 0.5, 0.5])
        assert result == [1.0, 1.0, 1.0]

    def test_min_max_range(self):
        """Test min-max normalization."""
        scores = [10.0, 20.0, 30.0]
        result = ScoreNormalizer.min_max(scores)

        assert result[0] == 0.0  # Min
        assert result[2] == 1.0  # Max
        assert result[1] == 0.5  # Middle

    def test_z_score_empty(self):
        """Test z-score with empty list."""
        result = ScoreNormalizer.z_score([])
        assert result == []

    def test_z_score_single(self):
        """Test z-score with single value."""
        result = ScoreNormalizer.z_score([0.5])
        assert result == [0.5]

    def test_z_score_identical(self):
        """Test z-score with identical values."""
        result = ScoreNormalizer.z_score([0.5, 0.5, 0.5])
        assert result == [0.5, 0.5, 0.5]

    def test_z_score_range(self):
        """Test z-score normalization produces values in [0, 1]."""
        scores = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = ScoreNormalizer.z_score(scores)

        for score in result:
            assert 0.0 <= score <= 1.0

    def test_rank_based_empty(self):
        """Test rank-based with empty list."""
        result = ScoreNormalizer.rank_based([])
        assert result == []

    def test_rank_based(self):
        """Test rank-based normalization."""
        scores = [0.3, 0.9, 0.5]  # Ranks: 3, 1, 2
        result = ScoreNormalizer.rank_based(scores)

        # Highest score (0.9 at index 1) should get highest normalized score
        assert result[1] > result[2] > result[0]

    def test_normalize_results_empty(self):
        """Test normalize_results with empty list."""
        result = ScoreNormalizer.normalize_results([])
        assert result == []

    def test_normalize_results_min_max(self):
        """Test normalize_results with min_max method."""
        results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="A",
                score=0.2,
            ),
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="B",
                score=0.8,
            ),
        ]

        normalized = ScoreNormalizer.normalize_results(results, method="min_max")

        assert normalized[0].score == 0.0  # Min
        assert normalized[1].score == 1.0  # Max

    def test_normalize_results_invalid_method(self):
        """Test normalize_results with invalid method."""
        results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content="A",
                score=0.5,
            ),
        ]

        with pytest.raises(ValueError, match="Unknown normalization method"):
            ScoreNormalizer.normalize_results(results, method="invalid")


class TestAnalyzerConfig:
    """Tests for AnalyzerConfig."""

    def test_get_index_settings(self):
        """Test index settings generation."""
        settings = AnalyzerConfig.get_index_settings()

        assert "settings" in settings
        assert "mappings" in settings

        # Check analyzers
        analysis = settings["settings"]["analysis"]
        assert "technical" in analysis["analyzer"]
        assert "autocomplete" in analysis["analyzer"]

        # Check mappings
        properties = settings["mappings"]["properties"]
        assert "content" in properties
        assert "title" in properties
        assert "tenant_id" in properties
        assert "visibility" in properties

        # Check content has technical sub-field
        assert "fields" in properties["content"]
        assert "technical" in properties["content"]["fields"]
