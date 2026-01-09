"""
Pydantic models for the Reranker Service API.
"""

from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DocumentPair(BaseModel):
    """A query-document pair for reranking."""

    query: str
    document: str
    doc_id: Optional[str] = None
    metadata: Optional[dict] = None


class RerankRequest(BaseModel):
    """
    Request to rerank documents for a query.

    Supports either:
    - Single query with list of documents
    - List of pre-formed query-document pairs
    """

    model: str = "BAAI/bge-reranker-v2-m3"

    # Option 1: Query + documents
    query: Optional[str] = None
    documents: Optional[list[str]] = None

    # Option 2: Pre-formed pairs
    pairs: Optional[list[DocumentPair]] = None

    # Reranking options
    top_k: Optional[int] = None  # Return only top K results
    min_score: Optional[float] = None  # Minimum score threshold
    return_documents: bool = True  # Include documents in response

    # Request metadata
    request_id: UUID = Field(default_factory=uuid4)


class ScoredDocument(BaseModel):
    """A document with its relevance score."""

    index: int
    score: float
    document: Optional[str] = None
    doc_id: Optional[str] = None
    metadata: Optional[dict] = None


class RerankResponse(BaseModel):
    """Response from reranking request."""

    model: str
    results: list[ScoredDocument]
    usage: dict  # Token counts
    processing_time_ms: float


class BatchRerankRequest(BaseModel):
    """Batch reranking for internal use."""

    queries: list[str]
    documents: list[str]
    doc_ids: Optional[list[str]] = None


class BatchRerankResult(BaseModel):
    """Batch reranking result."""

    scores: list[float]
    processing_time_ms: float


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "unhealthy", "degraded"]
    model_loaded: bool
    model_name: str
    device: str
    gpu_available: bool
    gpu_memory_used_mb: Optional[float] = None
    queue_size: int
    uptime_seconds: float


class ModelInfo(BaseModel):
    """Model information for /v1/models endpoint."""

    id: str
    object: str = "model"
    owned_by: str = "bge"
    type: str = "reranker"


class ModelsResponse(BaseModel):
    """Response for /v1/models endpoint."""

    object: str = "list"
    data: list[ModelInfo]
