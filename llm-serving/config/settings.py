"""
Shared configuration settings for LLM Serving Layer.

This module provides centralized configuration management for all services
in the LLM serving layer including vLLM, embedding, and reranker services.
"""

from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional, Literal
from functools import lru_cache


class VLLMSettings(BaseSettings):
    """vLLM service configuration."""

    # Model settings - using non-gated model for easier access
    model_name: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct",
        description="HuggingFace model ID"
    )
    served_model_name: Optional[str] = Field(
        default=None,
        description="Override model name in API responses"
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # Memory settings
    gpu_memory_utilization: float = Field(default=0.90, ge=0.1, le=0.99)
    max_model_len: int = 8192

    # Parallelism
    tensor_parallel_size: int = 1

    # Batching
    max_num_seqs: int = 256

    # KV cache
    block_size: int = 16
    swap_space: int = 4  # GB

    # Quantization
    quantization: Optional[Literal["awq", "gptq", "squeezellm"]] = None

    model_config = {"env_prefix": "VLLM_"}


class EmbeddingSettings(BaseSettings):
    """Embedding service configuration."""

    # Model settings
    model_name: str = Field(
        default="BAAI/bge-large-en-v1.5",
        description="Sentence-transformers model ID"
    )
    embedding_dim: int = 1024
    max_sequence_length: int = 512

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8001

    # Batching
    max_batch_size: int = 32
    max_batch_tokens: int = 8192
    batch_timeout_ms: float = 50.0

    # GPU settings
    device: str = "cuda"
    use_fp16: bool = True
    normalize_embeddings: bool = True

    # Queue
    max_queue_size: int = 1000
    worker_count: int = 1

    model_config = {"env_prefix": "EMBEDDING_"}


class RerankerSettings(BaseSettings):
    """Reranker service configuration."""

    # Model settings
    model_name: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="Cross-encoder model ID"
    )
    max_sequence_length: int = 512

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8002

    # Batching
    max_batch_size: int = 32
    batch_timeout_ms: float = 50.0

    # GPU settings
    device: str = "cuda"
    use_fp16: bool = True
    normalize_scores: bool = False

    # Queue
    max_queue_size: int = 1000
    worker_count: int = 1

    model_config = {"env_prefix": "RERANKER_"}


class GatewaySettings(BaseSettings):
    """Gateway service configuration."""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8004

    # Backend URLs
    vllm_url: str = "http://vllm:8000"
    embedding_url: str = "http://embedding-service:8001"
    reranker_url: str = "http://reranker-service:8002"

    # Timeouts
    request_timeout: float = 120.0
    connect_timeout: float = 10.0

    # Connection pool
    max_connections: int = 100
    max_keepalive_connections: int = 20

    model_config = {"env_prefix": "GATEWAY_"}


@lru_cache()
def get_vllm_settings() -> VLLMSettings:
    """Get cached vLLM settings."""
    return VLLMSettings()


@lru_cache()
def get_embedding_settings() -> EmbeddingSettings:
    """Get cached embedding settings."""
    return EmbeddingSettings()


@lru_cache()
def get_reranker_settings() -> RerankerSettings:
    """Get cached reranker settings."""
    return RerankerSettings()


@lru_cache()
def get_gateway_settings() -> GatewaySettings:
    """Get cached gateway settings."""
    return GatewaySettings()
