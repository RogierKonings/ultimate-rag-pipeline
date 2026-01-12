"""Integration tests for the embedding service.

These tests require running infrastructure (LLM Gateway, Redis).
Mark with @pytest.mark.integration to skip in unit test runs.
"""

from uuid import uuid4

import pytest

from ..cache import EmbeddingCache
from ..models import EmbeddingCacheConfig, EmbeddingServiceConfig
from ..service import EmbeddingService, create_embedding_service


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_service_with_real_llm_gateway():
    """Integration test with actual LLM Gateway."""
    config = EmbeddingServiceConfig(llm_gateway_url="http://localhost:8004")

    async with EmbeddingService(config) as service:
        result = await service.embed_texts(
            texts=["The quick brown fox jumps over the lazy dog."],
            chunk_ids=[uuid4()],
        )

        assert len(result.results) == 1
        assert len(result.results[0].embedding) == 1024
        assert result.results[0].model == "BAAI/bge-large-en-v1.5"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_service_with_real_cache():
    """Integration test with actual Redis cache."""
    config = EmbeddingServiceConfig(llm_gateway_url="http://localhost:8004")
    cache_config = EmbeddingCacheConfig(
        redis_url="redis://localhost:6379", key_prefix="test_integration:",
    )

    cache = EmbeddingCache(cache_config)

    try:
        async with EmbeddingService(config, cache=cache) as service:
            chunk_id = uuid4()
            text = "Test embedding with real services."

            # First call - should be cache miss
            result1 = await service.embed_texts(texts=[text], chunk_ids=[chunk_id])
            assert result1.cache_misses == 1
            assert result1.cache_hits == 0

            # Second call - should be cache hit
            result2 = await service.embed_texts(texts=[text], chunk_ids=[chunk_id])
            assert result2.cache_hits == 1
            assert result2.cache_misses == 0
            assert result2.results[0].cached is True

            # Embeddings should be identical
            assert result1.results[0].embedding == result2.results[0].embedding
    finally:
        # Clean up test keys
        await cache.connect()
        await cache.clear_all()
        await cache.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embed_query_integration():
    """Integration test for query embedding."""
    config = EmbeddingServiceConfig(llm_gateway_url="http://localhost:8004")

    async with EmbeddingService(config) as service:
        embedding = await service.embed_query("What is machine learning?")

        assert len(embedding) == 1024
        # Normalized vectors should have magnitude ~1
        import math

        magnitude = math.sqrt(sum(x * x for x in embedding))
        assert abs(magnitude - 1.0) < 0.01


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_embedding_integration():
    """Integration test for batch embedding."""
    config = EmbeddingServiceConfig(
        llm_gateway_url="http://localhost:8004", max_batch_size=5,
    )

    texts = [
        "First document about artificial intelligence.",
        "Second document about machine learning.",
        "Third document about neural networks.",
        "Fourth document about deep learning.",
        "Fifth document about natural language processing.",
        "Sixth document about computer vision.",
        "Seventh document about reinforcement learning.",
    ]

    async with EmbeddingService(config) as service:
        result = await service.embed_texts(
            texts=texts, chunk_ids=[uuid4() for _ in texts],
        )

        assert len(result.results) == 7
        for res in result.results:
            assert len(res.embedding) == 1024
            assert res.model == "BAAI/bge-large-en-v1.5"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_factory_function_integration():
    """Integration test for factory function."""
    service = await create_embedding_service(
        config=EmbeddingServiceConfig(llm_gateway_url="http://localhost:8004"),
        cache_config=EmbeddingCacheConfig(
            redis_url="redis://localhost:6379", key_prefix="test_factory:",
        ),
        enable_cache=True,
    )

    try:
        result = await service.embed_texts(
            texts=["Factory function test."], chunk_ids=[uuid4()],
        )
        assert len(result.results) == 1
    finally:
        await service.close()
        if service.cache:
            await service.cache.clear_all()
