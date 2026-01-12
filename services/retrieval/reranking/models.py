"""Data models for reranking module."""

from uuid import UUID

from pydantic import BaseModel


class RerankRequest(BaseModel):
    """Request for reranking."""

    query: str
    documents: list[str]  # Document contents to rerank
    document_ids: list[UUID]  # Corresponding IDs
    top_k: int | None = None  # Return top k after reranking
    return_documents: bool = False  # Include document text in response


class RerankResult(BaseModel):
    """Single reranked result."""

    document_id: UUID
    index: int  # Original index in input
    relevance_score: float  # Cross-encoder score
    document: str | None = None  # If return_documents=True


class RerankResponse(BaseModel):
    """Response from reranking."""

    results: list[RerankResult]
    model: str
    processing_time_ms: float


class RerankerConfig(BaseModel):
    """Reranker configuration."""

    # Model
    model: str = "BAAI/bge-reranker-v2-m3"

    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"
    rerank_endpoint: str = "/v1/rerank"

    # Batching
    max_batch_size: int = 32

    # Limits
    max_documents: int = 100
    max_query_length: int = 512  # In tokens (approx)
    max_document_length: int = 512  # In tokens (approx)

    # Performance
    timeout_seconds: float = 30.0

    # Score threshold
    score_threshold: float = 0.0  # Minimum score to include

    # Retry
    max_retries: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0
