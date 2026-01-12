"""Pydantic models for the embedding service."""

from uuid import UUID

from pydantic import BaseModel


class EmbeddingRequest(BaseModel):
    """Request model for embedding generation."""

    texts: list[str]
    model: str = "BAAI/bge-large-en-v1.5"
    normalize: bool = True
    prefix: str | None = None  # BGE models use "query: " or "passage: " prefix


class EmbeddingResult(BaseModel):
    """Result for a single embedding."""

    chunk_id: UUID
    embedding: list[float]
    model: str
    dimensions: int
    cached: bool = False


class BatchEmbeddingResult(BaseModel):
    """Result for a batch of embeddings."""

    results: list[EmbeddingResult]
    total_tokens: int
    processing_time_ms: float
    cache_hits: int
    cache_misses: int


class EmbeddingServiceConfig(BaseModel):
    """Configuration for the embedding service."""

    model: str = "BAAI/bge-large-en-v1.5"
    dimensions: int = 1024
    max_batch_size: int = 32
    max_tokens_per_batch: int = 8192
    normalize_embeddings: bool = True
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86400 * 7  # 7 days

    # LLM Gateway settings (architecture: port 8004)
    llm_gateway_url: str = "http://localhost:8004"
    embedding_endpoint: str = "/v1/embeddings"

    # Retry settings
    max_retries: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0

    # Request timeout
    timeout_seconds: float = 60.0


class EmbeddingCacheConfig(BaseModel):
    """Configuration for the embedding cache."""

    redis_url: str = "redis://localhost:6379"
    key_prefix: str = "emb:"
    default_ttl: int = 86400 * 7  # 7 days
