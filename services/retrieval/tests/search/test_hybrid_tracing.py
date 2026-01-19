"""Tests for hybrid search tracing."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from search.fusion import FusionMethod, HybridSearchConfig
from search.hybrid import HybridSearcher
from search.models import (
    KeywordSearchResponse,
    SearchResultItem,
    SemanticSearchResponse,
)
from shared.observability.otel.span_names import SpanNames


@pytest.fixture
def mock_semantic_searcher():
    """Create mock semantic searcher."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_keyword_searcher():
    """Create mock keyword searcher."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.close = AsyncMock()
    mock.health_check = AsyncMock(return_value=True)
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
        ],
        total_found=1,
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
        ],
        total_found=1,
        search_time_ms=30.0,
    )


class TestHybridSearchTracing:
    """Tests for hybrid search tracing."""

    @pytest.mark.asyncio
    async def test_search_creates_root_span_with_correct_name(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search creates a root span with the correct name."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            # Setup mock span context manager
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            # Verify the root span was created with correct name
            calls = mock_tracer.start_as_current_span.call_args_list
            span_names = [call[0][0] for call in calls]
            assert SpanNames.RETRIEVAL_SEARCH in span_names

    @pytest.mark.asyncio
    async def test_search_creates_semantic_span(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search creates a semantic search span."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            calls = mock_tracer.start_as_current_span.call_args_list
            span_names = [call[0][0] for call in calls]
            assert SpanNames.RETRIEVAL_SEMANTIC in span_names

    @pytest.mark.asyncio
    async def test_search_creates_keyword_span(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search creates a keyword search span."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            calls = mock_tracer.start_as_current_span.call_args_list
            span_names = [call[0][0] for call in calls]
            assert SpanNames.RETRIEVAL_KEYWORD in span_names

    @pytest.mark.asyncio
    async def test_search_creates_fusion_span(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search creates a fusion span."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            calls = mock_tracer.start_as_current_span.call_args_list
            span_names = [call[0][0] for call in calls]
            assert SpanNames.RETRIEVAL_FUSION in span_names

    @pytest.mark.asyncio
    async def test_search_sets_root_span_attributes(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search sets attributes on the root span."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            # Check that set_attribute was called with expected attributes
            set_attr_calls = mock_span.set_attribute.call_args_list
            attr_names = [call[0][0] for call in set_attr_calls]

            assert "retrieval.result_count" in attr_names
            assert "retrieval.search_time_ms" in attr_names

    @pytest.mark.asyncio
    async def test_search_root_span_has_query_attributes(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that the root span is created with query length and embedding dim."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        query = "machine learning"
        embedding = [0.1] * 1024

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query=query,
                query_embedding=embedding,
                top_k=10,
            )

            # Find the root span call
            root_call = None
            for call in mock_tracer.start_as_current_span.call_args_list:
                if call[0][0] == SpanNames.RETRIEVAL_SEARCH:
                    root_call = call
                    break

            assert root_call is not None
            attributes = root_call.kwargs.get("attributes", {})
            assert attributes.get("retrieval.query_length") == len(query)
            assert attributes.get("retrieval.embedding_dim") == len(embedding)

    @pytest.mark.asyncio
    async def test_search_fusion_span_has_count_attributes(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that the fusion span is created with result count attributes."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        with patch("search.hybrid.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await hybrid_searcher.search(
                query="machine learning",
                query_embedding=[0.1] * 1024,
                top_k=10,
            )

            # Find the fusion span call
            fusion_call = None
            for call in mock_tracer.start_as_current_span.call_args_list:
                if call[0][0] == SpanNames.RETRIEVAL_FUSION:
                    fusion_call = call
                    break

            assert fusion_call is not None
            attributes = fusion_call.kwargs.get("attributes", {})
            assert "retrieval.fusion.semantic_count" in attributes
            assert "retrieval.fusion.keyword_count" in attributes

    @pytest.mark.asyncio
    async def test_search_behavior_unchanged_with_tracing(
        self,
        hybrid_searcher,
        mock_semantic_searcher,
        mock_keyword_searcher,
        sample_semantic_response,
        sample_keyword_response,
    ):
        """Test that search behavior is unchanged when tracing is added."""
        mock_semantic_searcher.search = AsyncMock(return_value=sample_semantic_response)
        mock_keyword_searcher.search = AsyncMock(return_value=sample_keyword_response)

        response = await hybrid_searcher.search(
            query="machine learning",
            query_embedding=[0.1] * 1024,
            top_k=10,
        )

        # Verify core functionality still works
        assert len(response.results) > 0
        assert response.total_semantic == 1
        assert response.total_keyword == 1
        assert response.search_time_ms > 0
        assert response.fusion_method == FusionMethod.RRF
