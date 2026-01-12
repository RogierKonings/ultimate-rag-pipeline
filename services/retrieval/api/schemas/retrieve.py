"""Request and response schemas for retrieval endpoints."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """Search mode options."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class RetrieveRequest(BaseModel):
    """
    Main retrieval request.

    Supports hybrid, semantic-only, or keyword-only search
    with filtering, reranking, and pagination.
    """

    query: str = Field(..., min_length=1, max_length=2000)

    # Search configuration
    mode: SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)

    # Hybrid search weights (only used in HYBRID mode)
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)

    # Reranking
    rerank: bool = True
    rerank_top_k: int = Field(default=20, ge=1, le=100)

    # Filtering
    filters: dict[str, Any] | None = None

    # Score threshold
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # Response options
    include_metadata: bool = True
    include_highlights: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "How does machine learning work?",
                "mode": "hybrid",
                "top_k": 10,
                "rerank": True,
                "filters": {"source_type": "documentation"},
            },
        },
    }


class MultiQueryRequest(BaseModel):
    """
    Request for multi-query retrieval.

    Useful for complex queries that benefit from
    multiple query variations.
    """

    queries: list[str] = Field(..., min_length=1, max_length=5)
    aggregation: str = Field(default="rrf", pattern="^(max|avg|rrf)$")
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None
    rerank: bool = True


class RetrievedDocument(BaseModel):
    """Single retrieved document/chunk."""

    chunk_id: UUID
    document_id: UUID
    content: str
    score: float = Field(ge=0.0, le=1.0)

    # Document metadata
    title: str | None = None
    source: str | None = None
    source_type: str | None = None

    # Chunk position
    chunk_index: int = 0
    total_chunks: int = 1

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Score breakdown
    semantic_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None

    # Additional metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Highlights (if enabled)
    highlights: list[str] | None = None


class SearchMetrics(BaseModel):
    """Metrics for the search operation."""

    query_preprocessing_ms: float = 0.0
    embedding_ms: float | None = None
    semantic_search_ms: float | None = None
    keyword_search_ms: float | None = None
    fusion_ms: float | None = None
    rerank_ms: float | None = None
    total_ms: float

    semantic_results_count: int = 0
    keyword_results_count: int = 0
    fused_results_count: int = 0
    final_results_count: int = 0


class DebugInfo(BaseModel):
    """Debug information for the retrieval pipeline (US-3.10).

    Includes:
    - Counts per stage
    - Latency breakdown
    - Model names
    - Pipeline configuration
    """

    # Stage counts
    semantic_candidates: int = 0
    keyword_candidates: int = 0
    after_fusion: int = 0
    after_rerank: int = 0
    after_acl: int = 0

    # Latency breakdown (ms)
    preprocessing_latency_ms: float = 0.0
    embedding_latency_ms: float = 0.0
    semantic_search_latency_ms: float = 0.0
    keyword_search_latency_ms: float = 0.0
    fusion_latency_ms: float = 0.0
    rerank_latency_ms: float = 0.0
    acl_filter_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    # Models used
    embedding_model: str | None = None
    rerank_model: str | None = None

    # Pipeline configuration
    fusion_method: str = "rrf"
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3
    rrf_k: int = 60
    top_k_semantic: int = 50
    top_k_keyword: int = 50
    rerank_top_k: int = 10


class RetrieveResponse(BaseModel):
    """Response from retrieval endpoint."""

    results: list[RetrievedDocument]
    total_results: int
    query: str
    mode: SearchMode
    metrics: SearchMetrics

    # Query info
    query_id: UUID
    processed_at: datetime

    # Debug info (US-3.10)
    debug: DebugInfo | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "results": [
                    {
                        "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
                        "document_id": "550e8400-e29b-41d4-a716-446655440001",
                        "content": "Machine learning is a subset of AI...",
                        "score": 0.92,
                        "title": "ML Guide",
                        "source": "docs/ml-intro.md",
                    },
                ],
                "total_results": 1,
                "query": "How does machine learning work?",
                "mode": "hybrid",
            },
        },
    }


class ExplainResponse(BaseModel):
    """Response from explain endpoint."""

    chunk_id: UUID
    query: str
    explanation: dict[str, Any]
