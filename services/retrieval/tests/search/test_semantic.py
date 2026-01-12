"""Tests for semantic search."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from search.exceptions import SearchFilterError
from search.models import QdrantConfig, SearchResultItem
from search.semantic import SemanticSearcher


class MockQdrantResult:
    """Mock Qdrant search result."""

    def __init__(self, id: str, score: float, payload: dict):
        self.id = id
        self.score = score
        self.payload = payload


@pytest.fixture
def config():
    """Create test config."""
    return QdrantConfig(
        url="http://localhost:6333",
        collection_name="test_collection",
        hnsw_ef=128,
    )


@pytest.fixture
def searcher(config):
    """Create searcher instance."""
    return SemanticSearcher(config)


@pytest.fixture
def mock_client():
    """Create mock Qdrant client."""
    return AsyncMock()


@pytest.fixture
def mock_results():
    """Create mock search results."""
    return [
        MockQdrantResult(
            id=str(uuid4()),
            score=0.95,
            payload={
                "content": "Document about machine learning",
                "document_id": str(uuid4()),
                "title": "ML Guide",
                "source": "docs/ml.md",
                "chunk_index": 0,
                "total_chunks": 3,
            },
        ),
        MockQdrantResult(
            id=str(uuid4()),
            score=0.85,
            payload={
                "content": "Neural networks are a type of ML",
                "document_id": str(uuid4()),
                "title": "Neural Networks",
                "source": "docs/nn.md",
                "chunk_index": 1,
                "total_chunks": 2,
            },
        ),
    ]


class TestSemanticSearcherInit:
    """Tests for SemanticSearcher initialization."""

    def test_default_config(self):
        """Test initialization with default config."""
        searcher = SemanticSearcher()
        assert searcher.config.url == "http://localhost:6333"
        assert searcher.config.collection_name == "documents"
        assert searcher._client is None

    def test_custom_config(self, config):
        """Test initialization with custom config."""
        searcher = SemanticSearcher(config)
        assert searcher.config.collection_name == "test_collection"


class TestSemanticSearcherConnect:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, searcher):
        """Test connection creates client."""
        with patch("search.semantic.AsyncQdrantClient") as mock_class:
            mock_class.return_value = AsyncMock()
            await searcher.connect()

            mock_class.assert_called_once_with(
                url=searcher.config.url,
                api_key=searcher.config.api_key,
                timeout=searcher.config.timeout,
            )
            assert searcher._client is not None

    @pytest.mark.asyncio
    async def test_close(self, searcher, mock_client):
        """Test close disconnects client."""
        searcher._client = mock_client

        await searcher.close()

        mock_client.close.assert_called_once()
        assert searcher._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self, searcher):
        """Test async context manager."""
        with patch("search.semantic.AsyncQdrantClient") as mock_class:
            mock_client = AsyncMock()
            mock_class.return_value = mock_client

            async with searcher:
                assert searcher._client is not None

            mock_client.close.assert_called_once()


class TestSemanticSearcherSearch:
    """Tests for search functionality."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, searcher, mock_client, mock_results):
        """Test search returns properly formatted results."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=mock_results)

        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        assert len(response.results) == 2
        assert response.total_found == 2
        assert response.search_time_ms > 0
        assert response.results[0].content == "Document about machine learning"

    @pytest.mark.asyncio
    async def test_search_normalizes_scores(self, searcher, mock_client, mock_results):
        """Test that scores are normalized to 0-1 range."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=mock_results)

        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        for result in response.results:
            assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_search_with_filters(self, searcher, mock_client):
        """Test search with ACL filters."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=[])

        filters = {
            "must": [{"key": "tenant_id", "match": {"value": "tenant-123"}}],
            "should": [{"key": "visibility", "match": {"value": "public"}}],
        }

        await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
            filters=filters,
        )

        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None

    @pytest.mark.asyncio
    async def test_search_with_score_threshold(self, searcher, mock_client):
        """Test search with score threshold."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=[])

        await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
            score_threshold=0.5,
        )

        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["score_threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_search_lazy_connect(self, searcher):
        """Test search connects lazily if not connected."""
        with patch("search.semantic.AsyncQdrantClient") as mock_class:
            mock_client = AsyncMock()
            mock_client.search = AsyncMock(return_value=[])
            mock_class.return_value = mock_client

            await searcher.search(query_embedding=[0.1] * 1024)

            mock_class.assert_called_once()


class TestSemanticSearcherFilterBuilding:
    """Tests for filter building."""

    def test_build_filter_simple(self, searcher):
        """Test simple key-value filter."""
        filter_dict = {"tenant_id": "123"}
        result = searcher._build_filter(filter_dict)

        assert result.must is not None
        assert len(result.must) == 1

    def test_build_filter_must_conditions(self, searcher):
        """Test must conditions."""
        filter_dict = {
            "must": [
                {"key": "tenant_id", "match": {"value": "tenant-123"}},
                {"key": "visibility", "match": {"value": "public"}},
            ],
        }
        result = searcher._build_filter(filter_dict)

        assert result.must is not None
        assert len(result.must) == 2

    def test_build_filter_should_conditions(self, searcher):
        """Test should conditions."""
        filter_dict = {
            "should": [
                {"key": "group", "match": {"value": "engineering"}},
                {"key": "group", "match": {"value": "ml-team"}},
            ],
        }
        result = searcher._build_filter(filter_dict)

        assert result.should is not None
        assert len(result.should) == 2

    def test_build_filter_must_not_conditions(self, searcher):
        """Test must_not conditions."""
        filter_dict = {
            "must_not": [{"key": "visibility", "match": {"value": "private"}}],
        }
        result = searcher._build_filter(filter_dict)

        assert result.must_not is not None
        assert len(result.must_not) == 1

    def test_build_filter_match_any(self, searcher):
        """Test match any condition."""
        filter_dict = {
            "must": [{"key": "allowed_groups", "match": {"any": ["group-1", "group-2"]}}],
        }
        result = searcher._build_filter(filter_dict)

        assert result.must is not None
        assert len(result.must) == 1

    def test_build_filter_range(self, searcher):
        """Test range condition."""
        filter_dict = {
            "must": [{"key": "created_at", "range": {"gte": "2024-01-01"}}],
        }
        result = searcher._build_filter(filter_dict)

        assert result.must is not None
        assert len(result.must) == 1

    def test_build_condition_unsupported(self, searcher):
        """Test unsupported condition raises error."""
        with pytest.raises(SearchFilterError):
            searcher._build_condition({"key": "test", "unknown": {}})


class TestSemanticSearcherScoreNormalization:
    """Tests for score normalization."""

    def test_normalize_score_positive(self, searcher):
        """Test positive cosine similarity normalization."""
        # Cosine 0.9 -> (0.9 + 1) / 2 = 0.95
        result = searcher._normalize_score(0.9)
        assert result == 0.95

    def test_normalize_score_negative(self, searcher):
        """Test negative cosine similarity normalization."""
        # Cosine -0.5 -> (-0.5 + 1) / 2 = 0.25
        result = searcher._normalize_score(-0.5)
        assert result == 0.25

    def test_normalize_score_bounds(self, searcher):
        """Test score bounds are respected."""
        # Out of range values should be clamped
        assert searcher._normalize_score(2.0) == 1.0
        assert searcher._normalize_score(-3.0) == 0.0


class TestSemanticSearcherMultiVector:
    """Tests for multi-vector search."""

    @pytest.mark.asyncio
    async def test_multi_vector_search(self, searcher, mock_client):
        """Test multi-vector search with aggregation."""
        searcher._client = mock_client

        # Create results for two queries
        chunk_id = uuid4()
        doc_id = uuid4()

        result1 = MockQdrantResult(
            id=str(chunk_id),
            score=0.9,
            payload={"content": "Doc A", "document_id": str(doc_id)},
        )
        result2 = MockQdrantResult(
            id=str(uuid4()),
            score=0.8,
            payload={"content": "Doc B", "document_id": str(uuid4())},
        )

        mock_client.search = AsyncMock(side_effect=[[result1, result2], [result1]])

        response = await searcher.search_multi_vector(
            query_embeddings=[[0.1] * 1024, [0.2] * 1024],
            top_k=10,
            aggregation="max",
        )

        assert response.total_found > 0
        assert response.search_time_ms > 0

    def test_aggregate_results_max(self, searcher):
        """Test max aggregation."""
        chunk_id = uuid4()
        item = SearchResultItem(
            chunk_id=chunk_id,
            document_id=uuid4(),
            content="Test",
            score=0.5,
        )

        result_lists = [
            [item],
            [SearchResultItem(chunk_id=chunk_id, document_id=item.document_id, content="Test", score=0.9)],
        ]

        aggregated = searcher._aggregate_results(result_lists, "max", 10)

        assert len(aggregated) == 1
        assert aggregated[0].score == 0.9  # Max of 0.5 and 0.9

    def test_aggregate_results_avg(self, searcher):
        """Test average aggregation."""
        chunk_id = uuid4()
        doc_id = uuid4()

        result_lists = [
            [SearchResultItem(chunk_id=chunk_id, document_id=doc_id, content="Test", score=0.4)],
            [SearchResultItem(chunk_id=chunk_id, document_id=doc_id, content="Test", score=0.6)],
        ]

        aggregated = searcher._aggregate_results(result_lists, "avg", 10)

        assert len(aggregated) == 1
        assert aggregated[0].score == 0.5  # Avg of 0.4 and 0.6

    def test_aggregate_results_rrf(self, searcher):
        """Test RRF aggregation."""
        chunk_id1 = uuid4()
        chunk_id2 = uuid4()
        doc_id = uuid4()

        result_lists = [
            [
                SearchResultItem(chunk_id=chunk_id1, document_id=doc_id, content="A", score=0.9),
                SearchResultItem(chunk_id=chunk_id2, document_id=doc_id, content="B", score=0.8),
            ],
            [
                SearchResultItem(chunk_id=chunk_id1, document_id=doc_id, content="A", score=0.85),
            ],
        ]

        aggregated = searcher._aggregate_results(result_lists, "rrf", 10)

        # chunk_id1 appears in both, should rank higher
        assert len(aggregated) == 2
        assert aggregated[0].chunk_id == chunk_id1


class TestSemanticSearcherCollectionInfo:
    """Tests for collection info."""

    @pytest.mark.asyncio
    async def test_get_collection_info(self, searcher, mock_client):
        """Test getting collection info."""
        searcher._client = mock_client

        mock_info = MagicMock()
        mock_info.vectors_count = 1000
        mock_info.indexed_vectors_count = 1000
        mock_info.points_count = 1000
        mock_info.status.value = "green"

        mock_client.get_collection = AsyncMock(return_value=mock_info)

        info = await searcher.get_collection_info()

        assert info["name"] == "test_collection"
        assert info["vectors_count"] == 1000
        assert info["status"] == "green"


class TestSemanticSearcherHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, searcher, mock_client):
        """Test health check returns True on success."""
        searcher._client = mock_client
        mock_client.get_collection = AsyncMock()

        result = await searcher.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, searcher, mock_client):
        """Test health check returns False on failure."""
        searcher._client = mock_client
        mock_client.get_collection = AsyncMock(side_effect=Exception("Connection failed"))

        result = await searcher.health_check()

        assert result is False


class TestSemanticSearcherResultConversion:
    """Tests for result conversion."""

    def test_convert_result_with_string_uuid(self, searcher):
        """Test converting result with string UUID."""
        chunk_id = uuid4()
        doc_id = uuid4()

        result = MockQdrantResult(
            id=str(chunk_id),
            score=0.9,
            payload={
                "content": "Test content",
                "document_id": str(doc_id),
                "title": "Test Title",
            },
        )

        item = searcher._convert_result(result)

        assert item.chunk_id == chunk_id
        assert item.document_id == doc_id
        assert item.content == "Test content"
        assert item.title == "Test Title"

    def test_convert_result_with_int_id(self, searcher):
        """Test converting result with integer ID."""
        result = MockQdrantResult(
            id=12345,
            score=0.8,
            payload={
                "content": "Test",
                "document_id": str(uuid4()),
            },
        )

        item = searcher._convert_result(result)

        # Should create UUID from int
        assert item.chunk_id is not None

    def test_convert_result_metadata_extraction(self, searcher):
        """Test that metadata excludes certain fields."""
        result = MockQdrantResult(
            id=str(uuid4()),
            score=0.9,
            payload={
                "content": "Test",
                "document_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "custom_field": "value",
            },
        )

        item = searcher._convert_result(result)

        assert "custom_field" in item.metadata
        assert "content" not in item.metadata
        assert "document_id" not in item.metadata
        assert "chunk_id" not in item.metadata
