"""Search module for retrieval service.

Provides semantic (vector) and keyword (BM25) search implementations,
along with hybrid fusion algorithms.
"""

from search.base import BaseSearcher
from search.exceptions import (
    SearchConfigError,
    SearchConnectionError,
    SearchError,
    SearchFilterError,
    SearchTimeoutError,
)
from search.fusion import (
    DistributionBasedScoreFusion,
    FusedResult,
    FusionMethod,
    HybridSearchConfig,
    HybridSearchResponse,
    LinearFusion,
    ReciprocalRankFusion,
)
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher
from search.models import (
    KeywordSearchRequest,
    KeywordSearchResponse,
    OpenSearchConfig,
    QdrantConfig,
    ScoreNormalizer,
    SearchResultItem,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from search.resilient_hybrid import ResilientHybridSearcher
from search.semantic import SemanticSearcher

__all__ = [
    # Base
    "BaseSearcher",
    # Models
    "SearchResultItem",
    "SemanticSearchRequest",
    "SemanticSearchResponse",
    "KeywordSearchRequest",
    "KeywordSearchResponse",
    "QdrantConfig",
    "OpenSearchConfig",
    "ScoreNormalizer",
    # Searchers
    "SemanticSearcher",
    "KeywordSearcher",
    "HybridSearcher",
    "ResilientHybridSearcher",
    # Fusion
    "FusionMethod",
    "FusedResult",
    "HybridSearchConfig",
    "HybridSearchResponse",
    "ReciprocalRankFusion",
    "LinearFusion",
    "DistributionBasedScoreFusion",
    # Exceptions
    "SearchError",
    "SearchConnectionError",
    "SearchTimeoutError",
    "SearchFilterError",
    "SearchConfigError",
]
