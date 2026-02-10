"""
Shared configuration defaults for RAG pipeline.

All services should import from this module to ensure consistency.
Use factory functions (get_*_config) to obtain config instances,
which check environment variables and apply overrides.
"""

import os
from typing import Any

from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """Configuration for text chunking."""

    target_tokens: int = Field(default=300, description="Target chunk size in tokens")
    max_tokens: int = Field(default=512, description="Maximum chunk size (hard limit)")
    chunk_overlap: int = Field(default=50, description="Token overlap between chunks")
    min_chunk_size: int = Field(default=50, description="Minimum tokens per chunk")
    separators: list[str] = Field(
        default=["\n\n", "\n", ". ", " "],
        description="Separators for recursive splitting",
    )
    tokenizer: str = Field(
        default="cl100k_base",
        description="Tokenizer to use (cl100k_base compatible with BGE)",
    )
    preserve_sentences: bool = Field(default=True, description="Avoid splitting mid-sentence")
    preserve_paragraphs: bool = Field(default=False, description="Avoid splitting paragraphs")

    @property
    def chunk_size(self) -> int:
        """Alias for target_tokens for backward compatibility."""
        return self.target_tokens

    @property
    def overlap_tokens(self) -> int:
        """Alias for chunk_overlap for backward compatibility."""
        return self.chunk_overlap


class EmbeddingConfig(BaseModel):
    """Configuration for embedding model."""

    model_name: str = Field(
        default="BAAI/bge-small-en-v1.5", description="Embedding model identifier"
    )
    dimensions: int = Field(default=384, description="Embedding vector dimensions")
    batch_size: int = Field(default=32, ge=1, le=256, description="Batch size for embedding")
    normalize: bool = Field(default=True, description="Normalize embeddings for cosine similarity")
    query_prefix: str = Field(
        default="",
        description="Prefix added to queries (not documents)",
    )
    max_sequence_length: int = Field(
        default=512, ge=1, le=8192, description="Maximum input sequence length"
    )


class RetrievalConfig(BaseModel):
    """Configuration for hybrid retrieval."""

    semantic_top_k: int = Field(
        default=50, ge=1, le=200, description="Candidates from semantic search"
    )
    keyword_top_k: int = Field(
        default=50, ge=1, le=200, description="Candidates from keyword search"
    )
    rrf_k: int = Field(
        default=60, ge=1, description="RRF constant (prevents high-ranked dominance)"
    )
    semantic_weight: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Weight for semantic results"
    )
    keyword_weight: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Weight for keyword results"
    )
    rerank_top_k: int = Field(default=10, ge=1, le=100, description="Final results after reranking")
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3", description="Cross-encoder reranker model"
    )


def _get_env(key: str, default: Any, type_fn: type) -> Any:
    """Get environment variable with type conversion."""
    value = os.environ.get(key)
    if value is None:
        return default
    if type_fn is bool:
        return value.lower() in ("true", "1", "yes")
    return type_fn(value)


def get_chunking_config(**overrides: Any) -> ChunkingConfig:
    """
    Get chunking configuration.

    Priority: explicit overrides > environment variables > defaults.

    Environment variables:
        CHUNKING_TARGET_TOKENS, CHUNKING_MAX_TOKENS, CHUNKING_CHUNK_OVERLAP
    """
    values = {
        "target_tokens": _get_env("CHUNKING_TARGET_TOKENS", 300, int),
        "max_tokens": _get_env("CHUNKING_MAX_TOKENS", 512, int),
        "chunk_overlap": _get_env("CHUNKING_CHUNK_OVERLAP", 50, int),
    }
    values.update(overrides)
    return ChunkingConfig(**values)


def get_embedding_config(**overrides: Any) -> EmbeddingConfig:
    """
    Get embedding configuration.

    Priority: explicit overrides > environment variables > defaults.

    Environment variables:
        EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, EMBEDDING_BATCH_SIZE,
        EMBEDDING_NORMALIZE, EMBEDDING_QUERY_PREFIX
    """
    values = {
        "model_name": _get_env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5", str),
        "dimensions": _get_env("EMBEDDING_DIMENSIONS", 384, int),
        "batch_size": _get_env("EMBEDDING_BATCH_SIZE", 32, int),
        "normalize": _get_env("EMBEDDING_NORMALIZE", True, bool),
        "query_prefix": _get_env(
            "EMBEDDING_QUERY_PREFIX",
            "",
            str,
        ),
    }
    values.update(overrides)
    return EmbeddingConfig(**values)


def get_retrieval_config(**overrides: Any) -> RetrievalConfig:
    """
    Get retrieval configuration.

    Priority: explicit overrides > environment variables > defaults.

    Environment variables:
        RETRIEVAL_SEMANTIC_TOP_K, RETRIEVAL_KEYWORD_TOP_K, RETRIEVAL_RRF_K,
        RETRIEVAL_SEMANTIC_WEIGHT, RETRIEVAL_KEYWORD_WEIGHT,
        RETRIEVAL_RERANK_TOP_K, RETRIEVAL_RERANKER_MODEL
    """
    values = {
        "semantic_top_k": _get_env("RETRIEVAL_SEMANTIC_TOP_K", 50, int),
        "keyword_top_k": _get_env("RETRIEVAL_KEYWORD_TOP_K", 50, int),
        "rrf_k": _get_env("RETRIEVAL_RRF_K", 60, int),
        "semantic_weight": _get_env("RETRIEVAL_SEMANTIC_WEIGHT", 0.7, float),
        "keyword_weight": _get_env("RETRIEVAL_KEYWORD_WEIGHT", 0.3, float),
        "rerank_top_k": _get_env("RETRIEVAL_RERANK_TOP_K", 10, int),
        "reranker_model": _get_env("RETRIEVAL_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3", str),
    }
    values.update(overrides)
    return RetrievalConfig(**values)


def validate_all_configs() -> list[str]:
    """
    Validate configuration consistency at startup.

    Returns:
        List of warning/error messages. Empty list means all valid.
    """
    errors: list[str] = []

    chunking = get_chunking_config()
    embedding = get_embedding_config()
    retrieval = get_retrieval_config()

    # Chunking validation
    if chunking.chunk_overlap >= chunking.target_tokens:
        errors.append(
            f"Chunking: chunk_overlap ({chunking.chunk_overlap}) must be less than "
            f"target_tokens ({chunking.target_tokens})"
        )

    if chunking.target_tokens > chunking.max_tokens:
        errors.append(
            f"Chunking: target_tokens ({chunking.target_tokens}) exceeds "
            f"max_tokens ({chunking.max_tokens})"
        )

    # Embedding validation
    known_dimensions = {384, 768, 1024}
    if embedding.dimensions not in known_dimensions:
        errors.append(
            f"Embedding: unusual dimensions ({embedding.dimensions}), "
            f"expected one of {known_dimensions}"
        )

    # Retrieval validation
    weight_sum = retrieval.semantic_weight + retrieval.keyword_weight
    if abs(weight_sum - 1.0) > 0.001:
        errors.append(
            f"Retrieval: semantic_weight ({retrieval.semantic_weight}) + "
            f"keyword_weight ({retrieval.keyword_weight}) = {weight_sum}, expected 1.0"
        )

    if retrieval.rerank_top_k > retrieval.semantic_top_k:
        errors.append(
            f"Retrieval: rerank_top_k ({retrieval.rerank_top_k}) exceeds "
            f"semantic_top_k ({retrieval.semantic_top_k})"
        )

    return errors
