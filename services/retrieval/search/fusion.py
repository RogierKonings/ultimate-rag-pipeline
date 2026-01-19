"""Hybrid fusion algorithms for combining search results."""

from collections import defaultdict
from enum import Enum
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field, model_validator

from search.models import SearchResultItem
from shared.config.defaults import get_retrieval_config

# Load shared defaults once at module load
_retrieval_defaults = get_retrieval_config()


class FusionMethod(str, Enum):
    """Fusion method selection."""

    RRF = "rrf"  # Reciprocal Rank Fusion
    LINEAR = "linear"  # Linear weighted combination
    CONVEX = "convex"  # Convex combination (weights sum to 1)
    DBSF = "dbsf"  # Distribution-Based Score Fusion


class FusedResult(BaseModel):
    """A single fused result with provenance."""

    chunk_id: UUID
    document_id: UUID
    content: str
    fused_score: float
    semantic_score: float | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    source: str | None = None


class HybridSearchConfig(BaseModel):
    """Configuration for hybrid search.

    Default values are loaded from shared.config.defaults.RetrievalConfig
    to ensure consistency across services.
    """

    # Weights (from shared config)
    semantic_weight: float = Field(
        default=_retrieval_defaults.semantic_weight, ge=0.0, le=1.0
    )
    keyword_weight: float = Field(
        default=_retrieval_defaults.keyword_weight, ge=0.0, le=1.0
    )

    # Fusion method
    fusion_method: FusionMethod = FusionMethod.RRF

    # RRF parameters (from shared config)
    rrf_k: int = _retrieval_defaults.rrf_k

    # Result limits (from shared config)
    top_k: int = Field(default=_retrieval_defaults.rerank_top_k, ge=1, le=100)
    semantic_top_k: int = Field(
        default=_retrieval_defaults.semantic_top_k, ge=1, le=200
    )
    keyword_top_k: int = Field(
        default=_retrieval_defaults.keyword_top_k, ge=1, le=200
    )

    # Score thresholds
    min_score: float = 0.0

    # Deduplication
    deduplicate: bool = True

    @model_validator(mode="after")
    def validate_convex_weights(self) -> "HybridSearchConfig":
        """Validate that convex weights sum to 1.0."""
        if self.fusion_method == FusionMethod.CONVEX:
            total = self.semantic_weight + self.keyword_weight
            if abs(total - 1.0) > 0.001:
                raise ValueError("Convex fusion requires weights to sum to 1.0")
        return self


class HybridSearchResponse(BaseModel):
    """Response from hybrid search."""

    results: list[FusedResult]
    total_semantic: int
    total_keyword: int
    search_time_ms: float
    fusion_method: FusionMethod
    # Degradation fields (optional, set by ResilientHybridSearcher)
    degradation_mode: str | None = None
    components_used: list[str] = Field(default_factory=list)
    components_skipped: list[str] = Field(default_factory=list)


class ReciprocalRankFusion:
    """
    Reciprocal Rank Fusion (RRF) algorithm.

    RRF combines ranked lists by summing 1/(k + rank) for each item
    across all lists. This gives higher weight to items ranked highly
    in multiple lists without being dominated by any single list.

    Formula: RRF_score(d) = Σ 1 / (k + rank_i(d))

    Reference: Cormack et al., "Reciprocal Rank Fusion outperforms
    Condorcet and individual Rank Learning Methods" (2009)
    """

    def __init__(self, k: int = 60):
        """
        Initialize RRF with constant k.

        Args:
            k: Ranking constant (default 60). Higher k reduces
               the impact of high ranks, making fusion more equal.
        """
        self.k = k

    def fuse(
        self,
        semantic_results: list[SearchResultItem],
        keyword_results: list[SearchResultItem],
        top_k: int = 10,
    ) -> list[FusedResult]:
        """
        Fuse semantic and keyword results using RRF.

        Args:
            semantic_results: Results from vector search
            keyword_results: Results from BM25 search
            top_k: Number of final results to return

        Returns:
            List of FusedResult ordered by RRF score
        """
        # Track scores and metadata by chunk_id
        rrf_scores: dict[UUID, float] = defaultdict(float)
        items: dict[UUID, dict] = {}
        semantic_info: dict[UUID, tuple[float, int]] = {}
        keyword_info: dict[UUID, tuple[float, int]] = {}

        # Process semantic results
        for rank, result in enumerate(semantic_results, start=1):
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] += 1 / (self.k + rank)
            semantic_info[chunk_id] = (result.score, rank)

            if chunk_id not in items:
                items[chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }

        # Process keyword results
        for rank, result in enumerate(keyword_results, start=1):
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] += 1 / (self.k + rank)
            keyword_info[chunk_id] = (result.score, rank)

            if chunk_id not in items:
                items[chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }

        # Sort by RRF score
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        # Build fused results
        results = []
        for chunk_id, rrf_score in sorted_chunks:
            item = items[chunk_id]
            sem_score, sem_rank = semantic_info.get(chunk_id, (None, None))
            kw_score, kw_rank = keyword_info.get(chunk_id, (None, None))

            results.append(
                FusedResult(
                    chunk_id=chunk_id,
                    document_id=item["document_id"],
                    content=item["content"],
                    fused_score=rrf_score,
                    semantic_score=sem_score,
                    semantic_rank=sem_rank,
                    keyword_score=kw_score,
                    keyword_rank=kw_rank,
                    metadata=item["metadata"],
                    title=item["title"],
                    source=item["source"],
                ),
            )

        return results


class LinearFusion:
    """
    Linear weighted combination of scores.

    Combines normalized scores from both search methods using
    configurable weights: fused = w_sem * sem_score + w_kw * kw_score
    """

    def __init__(self, semantic_weight: float = 0.7, keyword_weight: float = 0.3):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight

    def fuse(
        self,
        semantic_results: list[SearchResultItem],
        keyword_results: list[SearchResultItem],
        top_k: int = 10,
    ) -> list[FusedResult]:
        """
        Fuse results using linear weighted combination.

        Scores must be normalized to [0, 1] before fusion.
        """
        # Build lookup dicts
        items: dict[UUID, dict] = {}
        semantic_scores: dict[UUID, float] = {}
        keyword_scores: dict[UUID, float] = {}

        for result in semantic_results:
            semantic_scores[result.chunk_id] = result.score
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }

        for result in keyword_results:
            keyword_scores[result.chunk_id] = result.score
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }

        # Calculate fused scores
        all_chunks = set(semantic_scores.keys()) | set(keyword_scores.keys())
        fused_scores: dict[UUID, float] = {}

        for chunk_id in all_chunks:
            sem_score = semantic_scores.get(chunk_id, 0.0)
            kw_score = keyword_scores.get(chunk_id, 0.0)

            fused = self.semantic_weight * sem_score + self.keyword_weight * kw_score
            fused_scores[chunk_id] = fused

        # Sort and build results
        sorted_chunks = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for chunk_id, fused_score in sorted_chunks:
            item = items[chunk_id]
            results.append(
                FusedResult(
                    chunk_id=chunk_id,
                    document_id=item["document_id"],
                    content=item["content"],
                    fused_score=fused_score,
                    semantic_score=semantic_scores.get(chunk_id),
                    keyword_score=keyword_scores.get(chunk_id),
                    metadata=item["metadata"],
                    title=item["title"],
                    source=item["source"],
                ),
            )

        return results


class DistributionBasedScoreFusion:
    """
    Distribution-Based Score Fusion (DBSF).

    Normalizes scores based on the score distribution of each
    retriever, then combines. More robust to different score
    distributions than simple linear fusion.

    Formula: normalized = (score - μ) / σ, then combine
    """

    def __init__(self, semantic_weight: float = 0.7, keyword_weight: float = 0.3):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight

    def fuse(
        self,
        semantic_results: list[SearchResultItem],
        keyword_results: list[SearchResultItem],
        top_k: int = 10,
    ) -> list[FusedResult]:
        """
        Fuse results using distribution-based normalization.
        """
        # Extract and normalize semantic scores
        sem_scores = [r.score for r in semantic_results]
        if sem_scores:
            sem_mean = np.mean(sem_scores)
            sem_std = np.std(sem_scores) or 1.0
            sem_normalized = {r.chunk_id: (r.score - sem_mean) / sem_std for r in semantic_results}
        else:
            sem_normalized = {}

        # Extract and normalize keyword scores
        kw_scores = [r.score for r in keyword_results]
        if kw_scores:
            kw_mean = np.mean(kw_scores)
            kw_std = np.std(kw_scores) or 1.0
            kw_normalized = {r.chunk_id: (r.score - kw_mean) / kw_std for r in keyword_results}
        else:
            kw_normalized = {}

        # Build items dict
        items: dict[UUID, dict] = {}
        original_scores: dict[UUID, tuple] = {}

        for result in semantic_results:
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }
            original_scores[result.chunk_id] = (result.score, None)

        for result in keyword_results:
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source,
                }
            if result.chunk_id in original_scores:
                original_scores[result.chunk_id] = (
                    original_scores[result.chunk_id][0],
                    result.score,
                )
            else:
                original_scores[result.chunk_id] = (None, result.score)

        # Combine normalized scores
        all_chunks = set(sem_normalized.keys()) | set(kw_normalized.keys())
        fused_scores: dict[UUID, float] = {}

        for chunk_id in all_chunks:
            sem = sem_normalized.get(chunk_id, 0.0)
            kw = kw_normalized.get(chunk_id, 0.0)
            fused = self.semantic_weight * sem + self.keyword_weight * kw
            fused_scores[chunk_id] = fused

        # Apply sigmoid to get [0, 1] scores
        for chunk_id in fused_scores:
            fused_scores[chunk_id] = 1 / (1 + np.exp(-fused_scores[chunk_id]))

        # Sort and build results
        sorted_chunks = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for chunk_id, fused_score in sorted_chunks:
            item = items[chunk_id]
            sem_orig, kw_orig = original_scores.get(chunk_id, (None, None))

            results.append(
                FusedResult(
                    chunk_id=chunk_id,
                    document_id=item["document_id"],
                    content=item["content"],
                    fused_score=float(fused_score),
                    semantic_score=sem_orig,
                    keyword_score=kw_orig,
                    metadata=item["metadata"],
                    title=item["title"],
                    source=item["source"],
                ),
            )

        return results
