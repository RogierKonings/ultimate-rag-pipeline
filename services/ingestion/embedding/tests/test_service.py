"""Tests for the embedding service."""

import math
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from ..models import EmbeddingServiceConfig
from ..service import EmbeddingService, ParallelEmbedder


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    @pytest.mark.asyncio
    async def test_embed_texts_returns_correct_dimensions(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that embeddings have correct dimensions."""
        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            result = await embedding_service.embed_texts(
                texts=["test text"],
                chunk_ids=[uuid4()],
            )

            assert len(result.results) == 1
            assert len(result.results[0].embedding) == 1024
            assert result.results[0].model == "BAAI/bge-large-en-v1.5"
            assert result.results[0].dimensions == 1024

    @pytest.mark.asyncio
    async def test_embed_texts_applies_prefix(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that prefix is correctly applied to texts."""
        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            await embedding_service.embed_texts(
                texts=["test text"],
                chunk_ids=[uuid4()],
                prefix="passage: ",
            )

            # Check that the text was prefixed
            call_args = mock.call_args[0][0]
            assert call_args[0] == "passage: test text"

    @pytest.mark.asyncio
    async def test_embed_texts_no_prefix(self, embedding_service: EmbeddingService):
        """Test embedding without prefix."""
        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            await embedding_service.embed_texts(
                texts=["test text"],
                chunk_ids=[uuid4()],
                prefix=None,
            )

            call_args = mock.call_args[0][0]
            assert call_args[0] == "test text"

    @pytest.mark.asyncio
    async def test_cache_prevents_redundant_calls(
        self,
        embedding_service_with_cache: EmbeddingService,
    ):
        """Test that cache prevents redundant API calls."""
        service = embedding_service_with_cache
        chunk_id = uuid4()

        with patch.object(
            service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            # First call - cache miss
            service.cache.get.return_value = None
            result1 = await service.embed_texts(
                texts=["test text"],
                chunk_ids=[chunk_id],
            )
            assert result1.cache_misses == 1
            assert result1.cache_hits == 0
            assert mock.call_count == 1

            # Second call - cache hit
            service.cache.get.return_value = [0.1] * 1024
            result2 = await service.embed_texts(
                texts=["test text"],
                chunk_ids=[chunk_id],
            )
            assert result2.cache_hits == 1
            assert result2.cache_misses == 0
            assert result2.results[0].cached is True

            # API should only be called once
            assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_batching_splits_large_requests(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that large requests are split into batches."""
        embedding_service.config.max_batch_size = 2

        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024, [0.2] * 1024], 200)

            result = await embedding_service.embed_texts(
                texts=["text1", "text2", "text3", "text4"],
                chunk_ids=[uuid4() for _ in range(4)],
            )

            # Should split into 2 batches
            assert mock.call_count == 2
            assert len(result.results) == 4

    @pytest.mark.asyncio
    async def test_batching_respects_token_limit(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that batching respects token limits."""
        embedding_service.config.max_batch_size = 100
        embedding_service.config.max_tokens_per_batch = 100

        # Create texts that exceed token limit (4 chars ~= 1 token)
        long_text = "a" * 400  # ~100 tokens each

        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            await embedding_service.embed_texts(
                texts=[long_text, long_text, long_text],
                chunk_ids=[uuid4() for _ in range(3)],
            )

            # Each text should be in its own batch due to token limit
            assert mock.call_count == 3

    def test_normalization_produces_unit_vectors(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that normalization produces unit vectors."""
        embedding = [3.0, 4.0]  # 3-4-5 triangle
        normalized = embedding_service._normalize(embedding)

        # Should have length 1
        length = math.sqrt(sum(x * x for x in normalized))
        assert abs(length - 1.0) < 0.0001

    def test_normalization_handles_zero_vector(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that normalization handles zero vectors."""
        embedding = [0.0, 0.0, 0.0]
        normalized = embedding_service._normalize(embedding)

        # Should return unchanged
        assert normalized == embedding

    def test_cache_key_deterministic(self, embedding_service: EmbeddingService):
        """Test that cache key generation is deterministic."""
        key1 = embedding_service._get_cache_key("test text")
        key2 = embedding_service._get_cache_key("test text")

        assert key1 == key2

    def test_cache_key_includes_model(self, embedding_service: EmbeddingService):
        """Test that cache key includes model name."""
        key1 = embedding_service._get_cache_key("test text")

        embedding_service.config.model = "different-model"
        key2 = embedding_service._get_cache_key("test text")

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_embed_query_uses_query_prefix(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that embed_query uses query prefix."""
        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024], 100)

            await embedding_service.embed_query("search query")

            call_args = mock.call_args[0][0]
            assert call_args[0] == "query: search query"

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, embedding_service: EmbeddingService):
        """Test that metrics are correctly tracked."""
        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ([[0.1] * 1024, [0.2] * 1024], 250)

            result = await embedding_service.embed_texts(
                texts=["text1", "text2"],
                chunk_ids=[uuid4(), uuid4()],
            )

            assert result.total_tokens == 250
            assert result.processing_time_ms > 0
            assert result.cache_misses == 2
            assert result.cache_hits == 0

    @pytest.mark.asyncio
    async def test_context_manager(self, embedding_config: EmbeddingServiceConfig):
        """Test async context manager."""
        service = EmbeddingService(config=embedding_config)

        with (
            patch.object(
                service._client,
                "connect",
                new_callable=AsyncMock,
            ) as mock_connect,
            patch.object(
                service._client,
                "disconnect",
                new_callable=AsyncMock,
            ) as mock_disconnect,
        ):
            async with service:
                pass

            mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()


class TestParallelEmbedder:
    """Tests for ParallelEmbedder."""

    @pytest.mark.asyncio
    async def test_parallel_embedding(self, embedding_service: EmbeddingService):
        """Test parallel embedding processing."""

        # Create mock chunks
        class MockChunk:
            def __init__(self, content: str, chunk_id):
                self.content = content
                self.chunk_id = chunk_id

        chunks = [MockChunk(f"text{i}", uuid4()) for i in range(10)]

        with patch.object(
            embedding_service._client,
            "embed_batch",
            new_callable=AsyncMock,
        ) as mock:
            # Return embeddings for batch size
            mock.return_value = ([[0.1] * 1024] * 10, 1000)

            embedder = ParallelEmbedder(embedding_service, max_concurrent=2)
            results = []

            async for result in embedder.embed_chunks_parallel(chunks):
                results.append(result)

            assert len(results) == 10

    @pytest.mark.asyncio
    async def test_parallel_respects_concurrency_limit(
        self,
        embedding_service: EmbeddingService,
    ):
        """Test that parallel embedder respects concurrency limit."""
        embedding_service.config.max_batch_size = 2

        class MockChunk:
            def __init__(self, content: str, chunk_id):
                self.content = content
                self.chunk_id = chunk_id

        chunks = [MockChunk(f"text{i}", uuid4()) for i in range(10)]

        concurrent_calls = []
        max_concurrent = 0

        async def mock_embed_batch(texts):
            nonlocal max_concurrent
            concurrent_calls.append(1)
            max_concurrent = max(max_concurrent, len(concurrent_calls))
            # Simulate some work
            import asyncio

            await asyncio.sleep(0.01)
            concurrent_calls.pop()
            return [[0.1] * 1024] * len(texts), len(texts) * 100

        with patch.object(
            embedding_service._client,
            "embed_batch",
            side_effect=mock_embed_batch,
        ):
            embedder = ParallelEmbedder(embedding_service, max_concurrent=2)
            results = []

            async for result in embedder.embed_chunks_parallel(chunks):
                results.append(result)

            assert len(results) == 10
            # Max concurrent should be at most 2
            assert max_concurrent <= 2
