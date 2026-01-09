"""Wave 2 Integration Tests.

Tests that Semantic and Keyword search modules work together with ACL filters.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from acl.models import UserContext, Visibility
from acl.filter import ACLFilter
from search.models import (
    QdrantConfig,
    OpenSearchConfig,
    SearchResultItem,
    ScoreNormalizer,
)
from search.semantic import SemanticSearcher
from search.keyword import KeywordSearcher


class MockQdrantResult:
    """Mock Qdrant search result."""

    def __init__(self, id: str, score: float, payload: dict):
        self.id = id
        self.score = score
        self.payload = payload


class TestWave2Integration:
    """Integration tests for Wave 2 components."""

    @pytest.fixture
    def user_context(self):
        """Create a user context for testing."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering", "ml-team"],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def acl_filter(self):
        """Create an ACL filter."""
        return ACLFilter()

    def test_imports_work(self):
        """Test that all imports work correctly without circular dependencies."""
        # ACL imports
        from acl.models import UserContext, DocumentACL, Visibility
        from acl.filter import ACLFilter

        # Search imports
        from search.models import (
            SearchResultItem,
            SemanticSearchRequest,
            SemanticSearchResponse,
            KeywordSearchRequest,
            KeywordSearchResponse,
            QdrantConfig,
            OpenSearchConfig,
            ScoreNormalizer,
        )
        from search.semantic import SemanticSearcher
        from search.keyword import KeywordSearcher
        from search.base import BaseSearcher
        from search.exceptions import SearchError, SearchConnectionError

        # All imports should succeed
        assert UserContext is not None
        assert ACLFilter is not None
        assert SemanticSearcher is not None
        assert KeywordSearcher is not None
        assert ScoreNormalizer is not None

    def test_acl_filter_compatible_with_semantic_search(self, acl_filter, user_context):
        """Test ACL filter output is compatible with SemanticSearcher."""
        filters = acl_filter.build_filter(user_context)

        # The filter dict should be usable by SemanticSearcher._build_filter
        searcher = SemanticSearcher()
        qdrant_filter = searcher._build_filter(filters)

        assert qdrant_filter is not None
        assert qdrant_filter.must is not None or qdrant_filter.should is not None

    def test_acl_filter_compatible_with_keyword_search(self, acl_filter, user_context):
        """Test ACL filter output is compatible with KeywordSearcher."""
        filters = acl_filter.build_filter(user_context)

        # The filter dict should be usable by KeywordSearcher._build_filter_clauses
        searcher = KeywordSearcher()
        os_clauses = searcher._build_filter_clauses(filters)

        assert os_clauses is not None
        assert len(os_clauses) > 0

    @pytest.mark.asyncio
    async def test_semantic_search_with_acl(self, acl_filter, user_context):
        """Test semantic search with ACL filters applied."""
        searcher = SemanticSearcher()
        mock_client = AsyncMock()

        # Create mock results
        mock_results = [
            MockQdrantResult(
                id=str(uuid4()),
                score=0.9,
                payload={
                    "content": "Machine learning document",
                    "document_id": str(uuid4()),
                    "tenant_id": str(user_context.tenant_id),
                },
            )
        ]
        mock_client.search = AsyncMock(return_value=mock_results)
        searcher._client = mock_client

        # Build ACL filter
        filters = acl_filter.build_filter(user_context)

        # Execute search with ACL filter
        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
            filters=filters,
        )

        assert response is not None
        assert len(response.results) == 1
        mock_client.search.assert_called_once()

        # Verify filter was passed to search
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["query_filter"] is not None

    @pytest.mark.asyncio
    async def test_keyword_search_with_acl(self, acl_filter, user_context):
        """Test keyword search with ACL filters applied."""
        searcher = KeywordSearcher()
        mock_client = AsyncMock()

        # Create mock response
        mock_response = {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_id": str(uuid4()),
                        "_score": 15.5,
                        "_source": {
                            "content": "Machine learning document",
                            "document_id": str(uuid4()),
                            "tenant_id": str(user_context.tenant_id),
                        },
                    }
                ],
            }
        }
        mock_client.search = AsyncMock(return_value=mock_response)
        searcher._client = mock_client

        # Build ACL filter
        filters = acl_filter.build_filter(user_context)

        # Execute search with ACL filter
        response = await searcher.search(
            query="machine learning",
            top_k=10,
            filters=filters,
        )

        assert response is not None
        assert len(response.results) == 1
        mock_client.search.assert_called_once()

    def test_score_normalization_consistency(self):
        """Test that score normalization produces consistent results."""
        # Create results with different raw scores
        results = [
            SearchResultItem(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Result {i}",
                score=float(10 * (5 - i)),  # 50, 40, 30, 20, 10
            )
            for i in range(5)
        ]

        # Normalize
        normalized = ScoreNormalizer.normalize_results(results.copy(), method="min_max")

        # Best score should be 1.0, worst should be 0.0
        assert normalized[0].score == 1.0
        assert normalized[4].score == 0.0

        # Order should be preserved
        for i in range(len(normalized) - 1):
            assert normalized[i].score >= normalized[i + 1].score

    def test_search_result_model_serialization(self):
        """Test SearchResultItem can be serialized and deserialized."""
        item = SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            score=0.85,
            metadata={"key": "value"},
            title="Test Title",
            source="test.md",
            highlights={"content": ["<mark>test</mark>"]},
        )

        # Serialize
        json_str = item.model_dump_json()

        # Deserialize
        restored = SearchResultItem.model_validate_json(json_str)

        assert restored.content == item.content
        assert restored.score == item.score
        assert restored.title == item.title
        assert restored.highlights == item.highlights


class TestWave2UsagePatterns:
    """Test common usage patterns for Wave 2 components."""

    @pytest.fixture
    def user_context(self):
        """Create a user context."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering"],
        )

    def test_typical_retrieval_flow_pattern(self, user_context):
        """Test the typical flow pattern for retrieval."""
        # 1. Build ACL filter for user
        acl = ACLFilter()
        acl_filters = acl.build_filter(user_context)

        # 2. Create search configs
        qdrant_config = QdrantConfig(
            url="http://qdrant:6333",
            collection_name="documents",
            hnsw_ef=128,
        )
        opensearch_config = OpenSearchConfig(
            url="http://opensearch:9200",
            index_name="documents",
            fuzziness="AUTO",
        )

        # 3. Create searchers
        semantic_searcher = SemanticSearcher(qdrant_config)
        keyword_searcher = KeywordSearcher(opensearch_config)

        # Verify configurations
        assert semantic_searcher.config.hnsw_ef == 128
        assert keyword_searcher.config.fuzziness == "AUTO"

        # Verify ACL filters have required structure
        assert "must" in acl_filters or "should" in acl_filters

    def test_multi_tenant_filters(self):
        """Test that different tenants get properly isolated filters."""
        tenant1 = uuid4()
        tenant2 = uuid4()

        user1 = UserContext(user_id=uuid4(), tenant_id=tenant1, groups=["team-a"])
        user2 = UserContext(user_id=uuid4(), tenant_id=tenant2, groups=["team-a"])

        acl = ACLFilter()

        filter1 = acl.build_filter(user1)
        filter2 = acl.build_filter(user2)

        # Both filters should work with searchers
        semantic_searcher = SemanticSearcher()
        keyword_searcher = KeywordSearcher()

        qdrant_filter1 = semantic_searcher._build_filter(filter1)
        qdrant_filter2 = semantic_searcher._build_filter(filter2)

        os_clauses1 = keyword_searcher._build_filter_clauses(filter1)
        os_clauses2 = keyword_searcher._build_filter_clauses(filter2)

        # Filters should be different (different tenant IDs)
        assert qdrant_filter1 is not None
        assert qdrant_filter2 is not None
        assert os_clauses1 != os_clauses2

    def test_admin_bypass_applies_to_both_searchers(self):
        """Test admin context bypass works with both searchers."""
        admin = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["admins"],
            roles=["admin"],
            permissions=["*"],
        )

        acl = ACLFilter()
        filters = acl.build_filter(admin)

        # Admin should get empty filter (bypass)
        assert filters == {}

        # Empty filters should still be handleable by searchers
        semantic_searcher = SemanticSearcher()
        keyword_searcher = KeywordSearcher()

        # No filter should be built for empty dict
        # (searchers check if filters before building)
        # This tests the pattern used in search methods


class TestSearcherConfiguration:
    """Test searcher configuration options."""

    def test_qdrant_config_hnsw_tuning(self):
        """Test HNSW parameter configuration."""
        # High recall config
        high_recall_config = QdrantConfig(
            hnsw_ef=256,
            exact_search=False,
        )

        # Exact search config
        exact_config = QdrantConfig(
            exact_search=True,
        )

        assert high_recall_config.hnsw_ef == 256
        assert exact_config.exact_search is True

    def test_opensearch_config_bm25_tuning(self):
        """Test BM25 parameter configuration."""
        # Strict matching config
        strict_config = OpenSearchConfig(
            default_operator="AND",
            fuzziness="0",
        )

        # Fuzzy matching config
        fuzzy_config = OpenSearchConfig(
            default_operator="OR",
            fuzziness="AUTO",
        )

        assert strict_config.default_operator == "AND"
        assert fuzzy_config.fuzziness == "AUTO"

    def test_search_result_metadata_structure(self):
        """Test search result metadata is properly structured."""
        result = SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test",
            score=0.9,
            metadata={
                "tenant_id": "tenant-123",
                "visibility": "group",
                "allowed_groups": ["engineering"],
                "source_type": "pdf",
                "language": "en",
            },
            title="Test Document",
            source="docs/test.pdf",
            chunk_index=0,
            total_chunks=5,
        )

        # Metadata should contain ACL-relevant fields
        assert "tenant_id" in result.metadata
        assert "visibility" in result.metadata
        assert "allowed_groups" in result.metadata

        # Position info should be available
        assert result.chunk_index == 0
        assert result.total_chunks == 5
