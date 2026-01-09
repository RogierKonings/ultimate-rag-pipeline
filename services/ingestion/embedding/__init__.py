"""Embedding service for generating vector representations of document chunks."""

from .cache import EmbeddingCache
from .client import LLMGatewayClient, LLMGatewayError
from .models import (
    BatchEmbeddingResult,
    EmbeddingCacheConfig,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingServiceConfig,
)
from .service import (
    EmbeddingService,
    ParallelEmbedder,
    create_embedding_service,
)

__all__ = [
    # Models
    "EmbeddingRequest",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    "EmbeddingServiceConfig",
    "EmbeddingCacheConfig",
    # Cache
    "EmbeddingCache",
    # Client
    "LLMGatewayClient",
    "LLMGatewayError",
    # Service
    "EmbeddingService",
    "ParallelEmbedder",
    "create_embedding_service",
]
