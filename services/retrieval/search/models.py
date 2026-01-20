"""Data models for search module."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field

from shared.config.urls import get_opensearch_url, get_qdrant_url


class SearchResultItem(BaseModel):
    """Individual search result."""

    chunk_id: UUID
    document_id: UUID
    content: str
    score: float = Field(ge=0.0)  # Raw score, normalized after retrieval
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Document info
    title: str | None = None
    source: str | None = None

    # Position info
    chunk_index: int = 0
    total_chunks: int = 1

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Highlighting (for keyword search)
    highlights: dict[str, list[str]] | None = None


class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""

    query_embedding: list[float]
    top_k: int = Field(default=10, ge=1, le=100)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    filters: dict[str, Any] | None = None
    include_metadata: bool = True
    include_vectors: bool = False


class SemanticSearchResponse(BaseModel):
    """Response from semantic search."""

    results: list[SearchResultItem]
    total_found: int
    search_time_ms: float
    query_id: UUID | None = None


class KeywordSearchRequest(BaseModel):
    """Request for keyword search."""

    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None
    fields: list[str] = Field(default_factory=lambda: ["content", "title"])
    field_boosts: dict[str, float] = Field(
        default_factory=lambda: {"title": 2.0, "content": 1.0},
    )
    highlight: bool = True
    min_score: float = 0.0


class KeywordSearchResponse(BaseModel):
    """Response from keyword search."""

    results: list[SearchResultItem]
    total_found: int
    search_time_ms: float
    query_id: UUID | None = None


class QdrantConfig(BaseModel):
    """Qdrant connection configuration."""

    url: str = Field(default_factory=get_qdrant_url)
    api_key: str | None = None
    collection_name: str = "documents"
    timeout: float = 30.0

    # HNSW parameters for recall tuning
    hnsw_ef: int = 128  # Higher = better recall, slower search
    exact_search: bool = False  # Use exact search instead of HNSW

    # Quantization
    use_quantization: bool = True
    quantization_rescore: bool = True


class OpenSearchConfig(BaseModel):
    """OpenSearch connection configuration."""

    url: str = Field(default_factory=get_opensearch_url)
    username: str | None = None
    password: str | None = None
    index_name: str = "documents"
    timeout: float = 30.0

    # SSL
    use_ssl: bool = False
    verify_certs: bool = True

    # Search configuration
    default_operator: str = "OR"  # "AND" or "OR"
    fuzziness: str = "AUTO"  # Fuzzy matching
    analyzer: str = "standard"

    # Performance
    track_total_hits: bool = True
    request_timeout: int = 30


class NormalizationMethod(str, Enum):
    """Score normalization methods."""

    MIN_MAX = "min_max"
    Z_SCORE = "z_score"
    RANK = "rank"


class ScoreNormalizer:
    """
    Utilities for normalizing search scores.

    Different search methods produce scores in different ranges.
    Normalization enables fair comparison and fusion.
    """

    @staticmethod
    def min_max(scores: list[float]) -> list[float]:
        """
        Min-max normalization to [0, 1] range.
        """
        if not scores:
            return []

        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            return [1.0] * len(scores)

        return [(s - min_score) / (max_score - min_score) for s in scores]

    @staticmethod
    def z_score(scores: list[float]) -> list[float]:
        """
        Z-score normalization (mean=0, std=1), then sigmoid to [0, 1].
        """
        if not scores or len(scores) == 1:
            return [0.5] * len(scores)

        arr = np.array(scores)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return [0.5] * len(scores)

        # Z-score then sigmoid to [0, 1]
        z_scores = (arr - mean) / std
        return (1 / (1 + np.exp(-z_scores))).tolist()

    @staticmethod
    def rank_based(scores: list[float]) -> list[float]:
        """
        Rank-based normalization (1.0 for best, decreasing linearly).
        """
        if not scores:
            return []

        n = len(scores)
        # Sort indices by score descending
        sorted_indices = sorted(range(n), key=lambda i: scores[i], reverse=True)

        result = [0.0] * n
        for rank, idx in enumerate(sorted_indices):
            result[idx] = 1.0 - (rank / n)

        return result

    @staticmethod
    def normalize_results(
        results: list[SearchResultItem],
        method: str = "min_max",
    ) -> list[SearchResultItem]:
        """
        Normalize scores in a list of results.
        """
        if not results:
            return results

        scores = [r.score for r in results]

        if method == "min_max":
            normalized = ScoreNormalizer.min_max(scores)
        elif method == "z_score":
            normalized = ScoreNormalizer.z_score(scores)
        elif method == "rank":
            normalized = ScoreNormalizer.rank_based(scores)
        else:
            raise ValueError(f"Unknown normalization method: {method}")

        for result, norm_score in zip(results, normalized, strict=True):
            result.score = norm_score

        return results


class AnalyzerConfig:
    """Configuration for custom OpenSearch analyzers."""

    @staticmethod
    def get_index_settings() -> dict:
        """
        Get index settings with custom analyzers.

        Includes:
        - Standard analyzer for general text
        - Technical analyzer for code/API terms
        - Edge n-gram for autocomplete
        """
        return {
            "settings": {
                "analysis": {
                    "analyzer": {
                        "technical": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": [
                                "lowercase",
                                "technical_synonyms",
                                "asciifolding",
                            ],
                        },
                        "autocomplete": {
                            "type": "custom",
                            "tokenizer": "autocomplete_tokenizer",
                            "filter": ["lowercase"],
                        },
                    },
                    "tokenizer": {
                        "autocomplete_tokenizer": {
                            "type": "edge_ngram",
                            "min_gram": 2,
                            "max_gram": 20,
                            "token_chars": ["letter", "digit"],
                        },
                    },
                    "filter": {
                        "technical_synonyms": {
                            "type": "synonym",
                            "synonyms": [
                                "api, endpoint, interface",
                                "auth, authentication, login",
                                "db, database, datastore",
                                "k8s, kubernetes",
                                "ml, machine learning",
                                "ai, artificial intelligence",
                            ],
                        },
                    },
                },
            },
            "mappings": {
                "properties": {
                    "content": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {"technical": {"type": "text", "analyzer": "technical"}},
                    },
                    "title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "document_id": {"type": "keyword"},
                    "chunk_id": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "allowed_groups": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "chunk_index": {"type": "integer"},
                    "total_chunks": {"type": "integer"},
                },
            },
        }
