"""Pydantic models for query preprocessing.

This module defines the data models used for query preprocessing,
expansion, and embedding generation.
"""

from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Classification of query types.

    Used to determine optimal processing strategy for each query.
    """

    SIMPLE = "simple"  # Basic keyword query (1-3 words)
    QUESTION = "question"  # Natural language question
    SEMANTIC = "semantic"  # Conceptual/semantic query
    HYBRID = "hybrid"  # Mixed intent


class ProcessedQuery(BaseModel):
    """Result of query preprocessing.

    Contains the original query, normalized version, expansions,
    embedding, and processing metadata.
    """

    query_id: UUID = Field(
        default_factory=uuid4, description="Unique identifier for this query"
    )
    original_query: str = Field(..., description="Original user query")
    normalized_query: str = Field(..., description="Normalized/cleaned query")
    expanded_queries: list[str] = Field(
        default_factory=list, description="Alternative query formulations"
    )
    hyde_document: Optional[str] = Field(
        default=None, description="Hypothetical document for HyDE"
    )
    embedding: list[float] = Field(..., description="Query embedding vector")
    query_type: QueryType = Field(
        default=QueryType.SIMPLE, description="Classified query type"
    )
    tokens: int = Field(default=0, description="Token count for embedding")
    processing_time_ms: float = Field(
        default=0.0, description="Total preprocessing time in milliseconds"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class QueryPreprocessorConfig(BaseModel):
    """Configuration for query preprocessing.

    Controls all aspects of query preprocessing including normalization,
    expansion, HyDE, and embedding generation.
    """

    # Normalization options
    lowercase: bool = Field(default=True, description="Convert query to lowercase")
    strip_whitespace: bool = Field(
        default=True, description="Strip and collapse whitespace"
    )
    remove_special_chars: bool = Field(
        default=False, description="Remove special characters"
    )

    # Expansion options
    enable_expansion: bool = Field(
        default=True, description="Enable query expansion"
    )
    max_expansions: int = Field(
        default=3, description="Maximum number of expanded queries"
    )
    expansion_model: str = Field(
        default="synonym", description="Expansion method: 'synonym' or 'llm'"
    )

    # HyDE options
    enable_hyde: bool = Field(
        default=False, description="Enable HyDE (adds latency)"
    )
    hyde_model: str = Field(
        default="meta-llama/Llama-3.1-8B-Instruct",
        description="Model for HyDE generation",
    )
    hyde_max_tokens: int = Field(
        default=256, description="Max tokens for HyDE document"
    )

    # Multi-query options
    enable_multi_query: bool = Field(
        default=False, description="Enable multi-query generation"
    )
    max_generated_queries: int = Field(
        default=3, description="Max generated query variations"
    )

    # Embedding options
    embedding_model: str = Field(
        default="BAAI/bge-large-en-v1.5", description="Embedding model name"
    )
    embedding_prefix: str = Field(
        default="query: ", description="Prefix for query embeddings (BGE requires this)"
    )
    embedding_dimension: int = Field(
        default=1024, description="Expected embedding dimension"
    )

    # LLM Gateway options
    llm_gateway_url: str = Field(
        default="http://localhost:8004", description="LLM Gateway base URL"
    )
    embedding_endpoint: str = Field(
        default="/v1/embeddings", description="Embedding API endpoint"
    )
    completion_endpoint: str = Field(
        default="/v1/completions", description="Completion API endpoint"
    )

    # Cache options
    cache_enabled: bool = Field(default=True, description="Enable query caching")
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds")

    # Timeout and retry options
    request_timeout: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_min_wait: float = Field(default=1.0, description="Minimum retry wait time")
    retry_max_wait: float = Field(default=10.0, description="Maximum retry wait time")
