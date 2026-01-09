"""Tests for RerankerService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx

from reranking.exceptions import (
    RerankerConnectionError,
    RerankerTimeoutError,
    RerankerValidationError,
)
from reranking.models import RerankerConfig
from reranking.reranker import RerankerService
from search.fusion import FusedResult


@pytest.fixture
def config():
    """Create test config."""
    return RerankerConfig(
        llm_gateway_url="http://localhost:8004",
        max_batch_size=32,
    )


@pytest.fixture
def reranker(config):
    """Create reranker instance."""
    return RerankerService(config)


@pytest.fixture
def mock_rerank_response():
    """Mock LLM Gateway rerank response."""
    return {
        "results": [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.75},
            {"index": 2, "relevance_score": 0.45},
        ]
    }


class TestRerankerServiceInit:
    """Tests for RerankerService initialization."""

    def test_default_config(self):
        """Test initialization with default config."""
        reranker = RerankerService()
        assert reranker.config.model == "BAAI/bge-reranker-v2-m3"
        assert reranker._client is None

    def test_custom_config(self, config):
        """Test initialization with custom config."""
        reranker = RerankerService(config)
        assert reranker.config.llm_gateway_url == "http://localhost:8004"


class TestRerankerServiceRerank:
    """Tests for rerank functionality."""

    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(self, reranker, mock_rerank_response):
        """Test that rerank returns results sorted by score."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_rerank_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            response = await reranker.rerank(
                query="test query",
                documents=["doc1", "doc2", "doc3"],
                document_ids=[uuid4(), uuid4(), uuid4()],
            )

            assert len(response.results) == 3
            assert response.results[0].relevance_score == 0.95
            assert response.results[1].relevance_score == 0.75
            assert response.results[2].relevance_score == 0.45

    @pytest.mark.asyncio
    async def test_rerank_top_k_limits_results(self, reranker, mock_rerank_response):
        """Test that top_k limits returned results."""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_rerank_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            response = await reranker.rerank(
                query="test query",
                documents=["doc1", "doc2", "doc3"],
                document_ids=[uuid4(), uuid4(), uuid4()],
                top_k=2,
            )

            assert len(response.results) == 2

    @pytest.mark.asyncio
    async def test_rerank_score_threshold_filtering(self, reranker):
        """Test that low scores are filtered."""
        reranker.config.score_threshold = 0.5

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.3},  # Below threshold
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            response = await reranker.rerank(
                query="test",
                documents=["doc1", "doc2"],
                document_ids=[uuid4(), uuid4()],
            )

            assert len(response.results) == 1
            assert response.results[0].relevance_score == 0.95

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self, reranker):
        """Test rerank with empty document list."""
        response = await reranker.rerank(
            query="test",
            documents=[],
            document_ids=[],
        )

        assert len(response.results) == 0
        assert response.processing_time_ms == 0.0

    @pytest.mark.asyncio
    async def test_rerank_mismatched_lengths(self, reranker):
        """Test validation error for mismatched lengths."""
        with pytest.raises(RerankerValidationError, match="same length"):
            await reranker.rerank(
                query="test",
                documents=["doc1", "doc2"],
                document_ids=[uuid4()],  # Only one ID
            )

    @pytest.mark.asyncio
    async def test_rerank_too_many_documents(self, reranker):
        """Test validation error for too many documents."""
        reranker.config.max_documents = 5

        with pytest.raises(RerankerValidationError, match="Too many documents"):
            await reranker.rerank(
                query="test",
                documents=["doc"] * 10,
                document_ids=[uuid4() for _ in range(10)],
            )

    @pytest.mark.asyncio
    async def test_rerank_return_documents(self, reranker):
        """Test return_documents option."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            response = await reranker.rerank(
                query="test",
                documents=["document content"],
                document_ids=[uuid4()],
                return_documents=True,
            )

            assert response.results[0].document == "document content"


class TestRerankerServiceBatching:
    """Tests for batch processing."""

    @pytest.mark.asyncio
    async def test_batching_large_document_sets(self, reranker):
        """Test that large document sets are batched."""
        reranker.config.max_batch_size = 2

        call_count = [0]

        def mock_json():
            call_count[0] += 1
            return {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.8},
                ]
            }

        mock_response = MagicMock()
        mock_response.json = mock_json
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            await reranker.rerank(
                query="test",
                documents=["d1", "d2", "d3", "d4"],  # 4 docs, batch size 2
                document_ids=[uuid4() for _ in range(4)],
            )

            assert mock_client.post.call_count == 2  # 2 batches


class TestRerankerServiceTruncation:
    """Tests for text truncation."""

    def test_truncate_short_text(self, reranker):
        """Test truncation of short text."""
        reranker.config.max_query_length = 100
        text = "Short text"

        truncated = reranker._truncate(text, 100)
        assert truncated == text

    def test_truncate_long_text(self, reranker):
        """Test truncation of long text."""
        reranker.config.max_query_length = 10
        # 10 tokens * 4 chars = 40 chars max
        long_text = "a" * 100

        truncated = reranker._truncate(long_text, 10)
        assert len(truncated) == 40


class TestRerankerServiceFusedResults:
    """Tests for reranking FusedResult objects."""

    @pytest.mark.asyncio
    async def test_rerank_fused_results(self, reranker):
        """Test convenience method for FusedResult objects."""
        chunk_id1 = uuid4()
        chunk_id2 = uuid4()

        fused = [
            FusedResult(
                chunk_id=chunk_id1,
                document_id=uuid4(),
                content="First document",
                fused_score=0.8,
            ),
            FusedResult(
                chunk_id=chunk_id2,
                document_id=uuid4(),
                content="Second document",
                fused_score=0.9,
            ),
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.6},  # First doc now lower
                {"index": 1, "relevance_score": 0.95},  # Second doc still higher
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            reranked = await reranker.rerank_fused_results(
                query="test",
                fused_results=fused,
            )

            # Should be reordered by rerank score
            assert len(reranked) == 2
            assert reranked[0].fused_score == 0.95
            assert reranked[1].fused_score == 0.6

    @pytest.mark.asyncio
    async def test_rerank_fused_results_preserves_metadata(self, reranker):
        """Test that metadata is preserved after reranking."""
        chunk_id = uuid4()

        fused = [
            FusedResult(
                chunk_id=chunk_id,
                document_id=uuid4(),
                content="Test document",
                fused_score=0.8,
                metadata={"existing": "value"},
                title="Test Title",
                source="test.md",
            )
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            reranked = await reranker.rerank_fused_results(
                query="test",
                fused_results=fused,
            )

            assert reranked[0].title == "Test Title"
            assert reranked[0].source == "test.md"
            assert reranked[0].metadata["existing"] == "value"
            assert reranked[0].metadata["rerank_score"] == 0.9
            assert reranked[0].metadata["original_fused_score"] == 0.8

    @pytest.mark.asyncio
    async def test_rerank_fused_results_empty(self, reranker):
        """Test reranking empty list."""
        result = await reranker.rerank_fused_results(
            query="test",
            fused_results=[],
        )
        assert result == []


class TestRerankerServiceErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_timeout_error(self, reranker):
        """Test timeout error handling."""
        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_get_client.return_value = mock_client

            with pytest.raises(RerankerTimeoutError):
                await reranker._rerank_batch("test", ["doc"])

    @pytest.mark.asyncio
    async def test_connection_error(self, reranker):
        """Test connection error handling."""
        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("connection failed")
            mock_get_client.return_value = mock_client

            with pytest.raises(RerankerConnectionError):
                await reranker._rerank_batch("test", ["doc"])


class TestRerankerServiceLifecycle:
    """Tests for service lifecycle management."""

    @pytest.mark.asyncio
    async def test_close(self, reranker):
        """Test closing the client."""
        # Create a mock client
        mock_client = AsyncMock()
        reranker._client = mock_client

        await reranker.close()

        mock_client.aclose.assert_called_once()
        assert reranker._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self, config):
        """Test async context manager."""
        async with RerankerService(config) as reranker:
            assert reranker is not None

    @pytest.mark.asyncio
    async def test_health_check_success(self, reranker):
        """Test health check success."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await reranker.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, reranker):
        """Test health check failure."""
        with patch.object(reranker, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Failed")
            mock_get_client.return_value = mock_client

            result = await reranker.health_check()
            assert result is False
