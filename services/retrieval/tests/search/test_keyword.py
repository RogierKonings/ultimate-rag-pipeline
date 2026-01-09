"""Tests for keyword search."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from search.keyword import KeywordSearcher
from search.models import OpenSearchConfig, SearchResultItem
from search.exceptions import SearchFilterError


@pytest.fixture
def config():
    """Create test config."""
    return OpenSearchConfig(
        url="http://localhost:9200",
        index_name="test_index",
        default_operator="OR",
        fuzziness="AUTO",
    )


@pytest.fixture
def searcher(config):
    """Create searcher instance."""
    return KeywordSearcher(config)


@pytest.fixture
def mock_client():
    """Create mock OpenSearch client."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_opensearch_response():
    """Create mock OpenSearch response."""
    return {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {
                    "_id": str(uuid4()),
                    "_score": 15.5,
                    "_source": {
                        "content": "Machine learning is transforming AI",
                        "document_id": str(uuid4()),
                        "title": "ML Guide",
                        "source": "docs/ml.md",
                        "tenant_id": "tenant-123",
                        "chunk_index": 0,
                        "total_chunks": 3,
                    },
                    "highlight": {
                        "content": ["<mark>Machine learning</mark> is transforming AI"]
                    },
                },
                {
                    "_id": str(uuid4()),
                    "_score": 12.3,
                    "_source": {
                        "content": "Deep learning is a subset of ML",
                        "document_id": str(uuid4()),
                        "title": "Deep Learning",
                        "source": "docs/dl.md",
                        "tenant_id": "tenant-123",
                    },
                },
            ],
        }
    }


class TestKeywordSearcherInit:
    """Tests for KeywordSearcher initialization."""

    def test_default_config(self):
        """Test initialization with default config."""
        searcher = KeywordSearcher()
        assert searcher.config.url == "http://localhost:9200"
        assert searcher.config.index_name == "documents"
        assert searcher._client is None

    def test_custom_config(self, config):
        """Test initialization with custom config."""
        searcher = KeywordSearcher(config)
        assert searcher.config.index_name == "test_index"


class TestKeywordSearcherConnect:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, searcher):
        """Test connection creates client."""
        with patch("search.keyword.AsyncOpenSearch") as mock_class:
            mock_class.return_value = AsyncMock()
            await searcher.connect()

            mock_class.assert_called_once()
            assert searcher._client is not None

    @pytest.mark.asyncio
    async def test_connect_with_auth(self, config):
        """Test connection with authentication."""
        config.username = "admin"
        config.password = "secret"
        searcher = KeywordSearcher(config)

        with patch("search.keyword.AsyncOpenSearch") as mock_class:
            mock_class.return_value = AsyncMock()
            await searcher.connect()

            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["http_auth"] == ("admin", "secret")

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
        with patch("search.keyword.AsyncOpenSearch") as mock_class:
            mock_client = AsyncMock()
            mock_class.return_value = mock_client

            async with searcher:
                assert searcher._client is not None

            mock_client.close.assert_called_once()


class TestKeywordSearcherSearch:
    """Tests for search functionality."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, searcher, mock_client, mock_opensearch_response):
        """Test search returns properly formatted results."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=mock_opensearch_response)

        response = await searcher.search(
            query="machine learning",
            top_k=10,
        )

        assert len(response.results) == 2
        assert response.total_found == 2
        assert response.search_time_ms > 0

    @pytest.mark.asyncio
    async def test_search_highlighting(self, searcher, mock_client, mock_opensearch_response):
        """Test that highlighted content is used when available."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=mock_opensearch_response)

        response = await searcher.search(
            query="machine learning",
            highlight=True,
        )

        # First result should have highlighted content
        assert "<mark>" in response.results[0].content

    @pytest.mark.asyncio
    async def test_search_normalizes_scores(self, searcher, mock_client, mock_opensearch_response):
        """Test that scores are normalized to 0-1 range."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(return_value=mock_opensearch_response)

        response = await searcher.search(query="test")

        for result in response.results:
            assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_search_with_field_boosts(self, searcher, mock_client):
        """Test search with field boosting."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        await searcher.search(
            query="test",
            fields=["content", "title"],
            field_boosts={"title": 3.0, "content": 1.0},
        )

        call_body = mock_client.search.call_args.kwargs["body"]
        query = call_body["query"]["multi_match"]

        assert "title^3.0" in query["fields"]
        assert "content^1.0" in query["fields"]

    @pytest.mark.asyncio
    async def test_search_with_filters(self, searcher, mock_client):
        """Test search with ACL filters."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        filters = {
            "must": [{"key": "tenant_id", "match": {"value": "tenant-123"}}],
        }

        await searcher.search(query="test", filters=filters)

        call_body = mock_client.search.call_args.kwargs["body"]
        assert "bool" in call_body["query"]
        assert "filter" in call_body["query"]["bool"]

    @pytest.mark.asyncio
    async def test_search_with_min_score(self, searcher, mock_client):
        """Test search with minimum score threshold."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        await searcher.search(query="test", min_score=5.0)

        call_body = mock_client.search.call_args.kwargs["body"]
        assert call_body["min_score"] == 5.0

    @pytest.mark.asyncio
    async def test_search_lazy_connect(self, searcher):
        """Test search connects lazily if not connected."""
        with patch("search.keyword.AsyncOpenSearch") as mock_class:
            mock_client = AsyncMock()
            mock_client.search = AsyncMock(
                return_value={"hits": {"total": {"value": 0}, "hits": []}}
            )
            mock_class.return_value = mock_client

            await searcher.search(query="test")

            mock_class.assert_called_once()


class TestKeywordSearcherFilterBuilding:
    """Tests for filter building."""

    def test_build_filter_must(self, searcher):
        """Test must filter conditions."""
        filters = {
            "must": [{"key": "tenant_id", "match": {"value": "tenant-123"}}]
        }
        clauses = searcher._build_filter_clauses(filters)

        assert len(clauses) == 1
        assert clauses[0] == {"term": {"tenant_id": "tenant-123"}}

    def test_build_filter_should(self, searcher):
        """Test should filter conditions."""
        filters = {
            "should": [
                {"key": "visibility", "match": {"value": "public"}},
                {"key": "allowed_groups", "match": {"any": ["group-1", "group-2"]}},
            ]
        }
        clauses = searcher._build_filter_clauses(filters)

        assert len(clauses) == 1
        assert "bool" in clauses[0]
        assert "should" in clauses[0]["bool"]
        assert len(clauses[0]["bool"]["should"]) == 2

    def test_build_filter_must_not(self, searcher):
        """Test must_not filter conditions."""
        filters = {
            "must_not": [{"key": "visibility", "match": {"value": "private"}}]
        }
        clauses = searcher._build_filter_clauses(filters)

        assert len(clauses) == 1
        assert "bool" in clauses[0]
        assert "must_not" in clauses[0]["bool"]

    def test_build_filter_match_any(self, searcher):
        """Test match any condition."""
        filters = {
            "must": [{"key": "groups", "match": {"any": ["a", "b"]}}]
        }
        clauses = searcher._build_filter_clauses(filters)

        assert clauses[0] == {"terms": {"groups": ["a", "b"]}}

    def test_build_filter_range(self, searcher):
        """Test range condition."""
        filters = {
            "must": [{"key": "created_at", "range": {"gte": "2024-01-01"}}]
        }
        clauses = searcher._build_filter_clauses(filters)

        assert clauses[0] == {"range": {"created_at": {"gte": "2024-01-01"}}}

    def test_build_filter_simple_key_value(self, searcher):
        """Test simple key-value filter."""
        filters = {"status": "active"}
        clauses = searcher._build_filter_clauses(filters)

        assert clauses[0] == {"term": {"status": "active"}}

    def test_build_filter_unsupported(self, searcher):
        """Test unsupported condition raises error."""
        with pytest.raises(SearchFilterError):
            searcher._build_filter_condition({"key": "test", "unknown": {}})


class TestKeywordSearcherScoreNormalization:
    """Tests for score normalization."""

    def test_normalize_scores_empty(self, searcher):
        """Test normalization with empty list."""
        result = searcher._normalize_scores([])
        assert result == []

    def test_normalize_scores_identical(self, searcher):
        """Test normalization with identical scores."""
        results = [
            SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="A", score=0.5),
            SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="B", score=0.5),
        ]
        normalized = searcher._normalize_scores(results)

        assert all(r.score == 1.0 for r in normalized)

    def test_normalize_scores_range(self, searcher):
        """Test normalization with varying scores."""
        results = [
            SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="A", score=0.8),
            SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="B", score=0.5),
            SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="C", score=0.3),
        ]
        normalized = searcher._normalize_scores(results)

        assert normalized[0].score == 1.0  # Max
        assert normalized[2].score == 0.0  # Min
        assert 0.0 < normalized[1].score < 1.0


class TestKeywordSearcherPhraseSearch:
    """Tests for phrase search."""

    @pytest.mark.asyncio
    async def test_phrase_search(self, searcher, mock_client):
        """Test phrase search with slop."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        await searcher.search_phrase(
            phrase="machine learning models",
            slop=2,
        )

        call_body = mock_client.search.call_args.kwargs["body"]
        phrase_query = call_body["query"]["bool"]["must"][0]["match_phrase"]

        assert phrase_query["content"]["query"] == "machine learning models"
        assert phrase_query["content"]["slop"] == 2

    @pytest.mark.asyncio
    async def test_phrase_search_with_filters(self, searcher, mock_client):
        """Test phrase search with filters."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        filters = {"must": [{"key": "tenant_id", "match": {"value": "123"}}]}

        await searcher.search_phrase(
            phrase="test phrase",
            filters=filters,
        )

        call_body = mock_client.search.call_args.kwargs["body"]
        assert "filter" in call_body["query"]["bool"]


class TestKeywordSearcherExpansionSearch:
    """Tests for query expansion search."""

    @pytest.mark.asyncio
    async def test_search_with_expansion(self, searcher, mock_client):
        """Test search with multiple query variations."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        await searcher.search_with_expansion(
            queries=["machine learning", "ML", "artificial intelligence"],
            top_k=10,
        )

        call_body = mock_client.search.call_args.kwargs["body"]
        assert "bool" in call_body["query"]
        assert "should" in call_body["query"]["bool"]
        assert len(call_body["query"]["bool"]["should"]) == 3

    @pytest.mark.asyncio
    async def test_search_with_expansion_filters(self, searcher, mock_client):
        """Test expansion search with filters."""
        searcher._client = mock_client
        mock_client.search = AsyncMock(
            return_value={"hits": {"total": {"value": 0}, "hits": []}}
        )

        filters = {"must": [{"key": "tenant_id", "match": {"value": "123"}}]}

        await searcher.search_with_expansion(
            queries=["q1", "q2"],
            filters=filters,
        )

        call_body = mock_client.search.call_args.kwargs["body"]
        assert "filter" in call_body["query"]["bool"]


class TestKeywordSearcherIndexInfo:
    """Tests for index info."""

    @pytest.mark.asyncio
    async def test_get_index_info(self, searcher, mock_client):
        """Test getting index info."""
        searcher._client = mock_client
        mock_client.indices.stats = AsyncMock(
            return_value={
                "indices": {
                    "test_index": {
                        "total": {
                            "docs": {"count": 1000, "deleted": 50},
                            "store": {"size_in_bytes": 1048576},
                        }
                    }
                }
            }
        )

        info = await searcher.get_index_info()

        assert info["name"] == "test_index"
        assert info["docs_count"] == 1000
        assert info["docs_deleted"] == 50
        assert info["store_size"] == 1048576
        assert info["store_size_human"] == "1.0MB"


class TestKeywordSearcherHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_health_check_green(self, searcher, mock_client):
        """Test health check returns True for green cluster."""
        searcher._client = mock_client
        mock_client.cluster.health = AsyncMock(return_value={"status": "green"})

        result = await searcher.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_yellow(self, searcher, mock_client):
        """Test health check returns True for yellow cluster."""
        searcher._client = mock_client
        mock_client.cluster.health = AsyncMock(return_value={"status": "yellow"})

        result = await searcher.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_red(self, searcher, mock_client):
        """Test health check returns False for red cluster."""
        searcher._client = mock_client
        mock_client.cluster.health = AsyncMock(return_value={"status": "red"})

        result = await searcher.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_failure(self, searcher, mock_client):
        """Test health check returns False on exception."""
        searcher._client = mock_client
        mock_client.cluster.health = AsyncMock(side_effect=Exception("Connection failed"))

        result = await searcher.health_check()

        assert result is False


class TestKeywordSearcherResultConversion:
    """Tests for result conversion."""

    def test_convert_hit_basic(self, searcher):
        """Test basic hit conversion."""
        chunk_id = uuid4()
        doc_id = uuid4()

        hit = {
            "_id": str(chunk_id),
            "_score": 10.5,
            "_source": {
                "content": "Test content",
                "document_id": str(doc_id),
                "title": "Test Title",
            },
        }

        item = searcher._convert_hit(hit)

        assert item.chunk_id == chunk_id
        assert item.document_id == doc_id
        assert item.content == "Test content"
        assert item.title == "Test Title"

    def test_convert_hit_with_highlights(self, searcher):
        """Test hit conversion with highlights."""
        hit = {
            "_id": str(uuid4()),
            "_score": 10.0,
            "_source": {
                "content": "Original content",
                "document_id": str(uuid4()),
            },
            "highlight": {
                "content": ["<mark>highlighted</mark> content"]
            },
        }

        item = searcher._convert_hit(hit)

        # Highlighted content should be used
        assert "<mark>" in item.content
        assert item.highlights is not None

    def test_convert_hit_non_uuid_id(self, searcher):
        """Test hit conversion with non-UUID ID."""
        hit = {
            "_id": "non-uuid-string",
            "_score": 10.0,
            "_source": {
                "content": "Test",
                "document_id": str(uuid4()),
            },
        }

        item = searcher._convert_hit(hit)

        # Should still create a valid UUID
        assert item.chunk_id is not None

    def test_convert_hit_metadata_extraction(self, searcher):
        """Test that metadata excludes certain fields."""
        hit = {
            "_id": str(uuid4()),
            "_score": 10.0,
            "_source": {
                "content": "Test",
                "document_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "embedding": [0.1, 0.2],
                "custom_field": "value",
            },
        }

        item = searcher._convert_hit(hit)

        assert "custom_field" in item.metadata
        assert "content" not in item.metadata
        assert "document_id" not in item.metadata
        assert "embedding" not in item.metadata


class TestKeywordSearcherUtilities:
    """Tests for utility methods."""

    def test_format_bytes_bytes(self, searcher):
        """Test bytes formatting for small sizes."""
        assert searcher._format_bytes(500) == "500.0B"

    def test_format_bytes_kb(self, searcher):
        """Test bytes formatting for KB."""
        assert searcher._format_bytes(2048) == "2.0KB"

    def test_format_bytes_mb(self, searcher):
        """Test bytes formatting for MB."""
        assert searcher._format_bytes(1048576) == "1.0MB"

    def test_format_bytes_gb(self, searcher):
        """Test bytes formatting for GB."""
        assert searcher._format_bytes(1073741824) == "1.0GB"

    def test_parse_uuid_valid(self, searcher):
        """Test parsing valid UUID."""
        original = uuid4()
        parsed = searcher._parse_uuid(str(original))
        assert parsed == original

    def test_parse_uuid_invalid(self, searcher):
        """Test parsing invalid UUID creates fallback."""
        parsed = searcher._parse_uuid("not-a-uuid")
        assert parsed is not None
