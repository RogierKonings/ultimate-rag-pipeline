"""Pytest fixtures for embedding service tests."""

from unittest.mock import AsyncMock

import pytest

from ..cache import EmbeddingCache
from ..client import LLMGatewayClient
from ..models import EmbeddingCacheConfig, EmbeddingServiceConfig
from ..service import EmbeddingService


@pytest.fixture
def embedding_config() -> EmbeddingServiceConfig:
    """Create a test embedding service configuration."""
    return EmbeddingServiceConfig(
        model="BAAI/bge-large-en-v1.5",
        dimensions=1024,
        max_batch_size=32,
        max_tokens_per_batch=8192,
        normalize_embeddings=True,
        cache_enabled=True,
        cache_ttl_seconds=3600,
        llm_gateway_url="http://localhost:8004",
        max_retries=3,
        timeout_seconds=30.0,
    )


@pytest.fixture
def cache_config() -> EmbeddingCacheConfig:
    """Create a test cache configuration."""
    return EmbeddingCacheConfig(
        redis_url="redis://localhost:6379",
        key_prefix="test_emb:",
        default_ttl=3600,
    )


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Create a mock embedding cache."""
    cache = AsyncMock(spec=EmbeddingCache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.connect = AsyncMock()
    cache.disconnect = AsyncMock()
    return cache


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock LLM Gateway client."""
    client = AsyncMock(spec=LLMGatewayClient)
    client.embed_batch = AsyncMock(return_value=([[0.1] * 1024], 100))
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def embedding_service(embedding_config: EmbeddingServiceConfig) -> EmbeddingService:
    """Create an embedding service for testing (without cache)."""
    return EmbeddingService(config=embedding_config, cache=None)


@pytest.fixture
def embedding_service_with_cache(
    embedding_config: EmbeddingServiceConfig,
    mock_cache: AsyncMock,
) -> EmbeddingService:
    """Create an embedding service with mock cache for testing."""
    return EmbeddingService(config=embedding_config, cache=mock_cache)
