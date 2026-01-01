# US-3.2: Semantic Search

> **Story ID:** US-3.2  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-3.1 (Query Preprocessor), US-3.6 (ACL Filter)

## User Story

**As a** developer  
**I want** vector similarity search  
**So that** semantically relevant documents are retrieved

## Context

Semantic search uses vector embeddings to find documents that are conceptually similar to the query, even when they don't share exact keywords. Per the architecture, Qdrant is the vector database with HNSW indexing for fast approximate nearest neighbor search. The semantic search component integrates with ACL filtering to ensure users only see documents they're authorized to access.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── search/
    ├── __init__.py
    ├── base.py              # Search interface
    ├── semantic.py          # Qdrant vector search
    ├── models.py            # Pydantic models
    └── exceptions.py        # Custom exceptions
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

class SearchResultItem(BaseModel):
    """Individual search result."""
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = {}
    
    # Document info
    title: Optional[str] = None
    source: Optional[str] = None
    
    # Position info
    chunk_index: int = 0
    total_chunks: int = 1
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""
    query_embedding: list[float]
    top_k: int = Field(default=10, ge=1, le=100)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    filters: Optional[dict[str, Any]] = None
    include_metadata: bool = True
    include_vectors: bool = False

class SemanticSearchResponse(BaseModel):
    """Response from semantic search."""
    results: list[SearchResultItem]
    total_found: int
    search_time_ms: float
    query_id: Optional[UUID] = None

class QdrantConfig(BaseModel):
    """Qdrant connection configuration."""
    url: str = "http://localhost:6333"
    api_key: Optional[str] = None
    collection_name: str = "documents"
    timeout: float = 30.0
    
    # HNSW parameters for recall tuning
    hnsw_ef: int = 128  # Higher = better recall, slower search
    exact_search: bool = False  # Use exact search instead of HNSW
    
    # Quantization
    use_quantization: bool = True
    quantization_rescore: bool = True
```

### Base Search Interface

```python
from abc import ABC, abstractmethod
from typing import Optional, Any

class BaseSearcher(ABC):
    """Abstract base class for search implementations."""
    
    @abstractmethod
    async def search(
        self,
        query: Any,
        top_k: int = 10,
        filters: Optional[dict] = None,
        **kwargs
    ) -> list[SearchResultItem]:
        """Execute search and return results."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if search backend is healthy."""
        pass
    
    @abstractmethod
    async def close(self):
        """Close connections."""
        pass
```

### Semantic Search Implementation

```python
import time
from typing import Optional, Any
from uuid import UUID
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    Range,
    SearchParams,
    QuantizationSearchParams
)

class SemanticSearcher(BaseSearcher):
    """
    Semantic search using Qdrant vector database.
    
    Uses HNSW indexing for fast approximate nearest neighbor search.
    Supports filtering by metadata and ACL fields.
    """
    
    def __init__(self, config: QdrantConfig = QdrantConfig()):
        self.config = config
        self._client: Optional[AsyncQdrantClient] = None
    
    async def connect(self):
        """Establish connection to Qdrant."""
        self._client = AsyncQdrantClient(
            url=self.config.url,
            api_key=self.config.api_key,
            timeout=self.config.timeout
        )
    
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None,
        score_threshold: float = 0.0,
        include_metadata: bool = True,
        include_vectors: bool = False
    ) -> SemanticSearchResponse:
        """
        Execute vector similarity search.
        
        Args:
            query_embedding: Query vector (1024 dimensions for BGE)
            top_k: Number of results to return
            filters: Qdrant filter dict (built by ACLFilter)
            score_threshold: Minimum similarity score (0-1)
            include_metadata: Include payload in results
            include_vectors: Include vectors in results
        
        Returns:
            SemanticSearchResponse with ranked results
        """
        if not self._client:
            await self.connect()
        
        start_time = time.time()
        
        # Build Qdrant filter from dict
        qdrant_filter = self._build_filter(filters) if filters else None
        
        # Configure search parameters
        search_params = SearchParams(
            hnsw_ef=self.config.hnsw_ef,
            exact=self.config.exact_search
        )
        
        # Add quantization params if enabled
        if self.config.use_quantization:
            search_params.quantization = QuantizationSearchParams(
                rescore=self.config.quantization_rescore
            )
        
        # Execute search
        results = await self._client.search(
            collection_name=self.config.collection_name,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=include_metadata,
            with_vectors=include_vectors,
            search_params=search_params
        )
        
        search_time = (time.time() - start_time) * 1000
        
        # Convert to response model
        items = [self._convert_result(r) for r in results]
        
        return SemanticSearchResponse(
            results=items,
            total_found=len(items),
            search_time_ms=search_time
        )
    
    def _build_filter(self, filter_dict: dict) -> Filter:
        """
        Build Qdrant Filter from dictionary specification.
        
        Supports nested must/should/must_not conditions.
        """
        conditions = []
        should_conditions = []
        must_not_conditions = []
        
        for key, value in filter_dict.items():
            if key == "must":
                for condition in value:
                    conditions.append(self._build_condition(condition))
            elif key == "should":
                for condition in value:
                    should_conditions.append(self._build_condition(condition))
            elif key == "must_not":
                for condition in value:
                    must_not_conditions.append(self._build_condition(condition))
            else:
                # Simple key-value filter
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
        
        return Filter(
            must=conditions if conditions else None,
            should=should_conditions if should_conditions else None,
            must_not=must_not_conditions if must_not_conditions else None
        )
    
    def _build_condition(self, condition: dict) -> FieldCondition:
        """Build a single field condition."""
        key = condition.get("key")
        
        if "match" in condition:
            match_spec = condition["match"]
            if "value" in match_spec:
                return FieldCondition(
                    key=key,
                    match=MatchValue(value=match_spec["value"])
                )
            elif "any" in match_spec:
                return FieldCondition(
                    key=key,
                    match=MatchAny(any=match_spec["any"])
                )
        elif "range" in condition:
            range_spec = condition["range"]
            return FieldCondition(
                key=key,
                range=Range(
                    gte=range_spec.get("gte"),
                    gt=range_spec.get("gt"),
                    lte=range_spec.get("lte"),
                    lt=range_spec.get("lt")
                )
            )
        
        raise ValueError(f"Unsupported condition: {condition}")
    
    def _convert_result(self, result) -> SearchResultItem:
        """Convert Qdrant result to SearchResultItem."""
        payload = result.payload or {}
        
        return SearchResultItem(
            chunk_id=UUID(result.id) if isinstance(result.id, str) else UUID(int=result.id),
            document_id=UUID(payload.get("document_id", "00000000-0000-0000-0000-000000000000")),
            content=payload.get("content", ""),
            score=self._normalize_score(result.score),
            metadata={
                k: v for k, v in payload.items()
                if k not in ["content", "document_id", "chunk_id"]
            },
            title=payload.get("title"),
            source=payload.get("source"),
            chunk_index=payload.get("chunk_index", 0),
            total_chunks=payload.get("total_chunks", 1),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at")
        )
    
    def _normalize_score(self, score: float) -> float:
        """
        Normalize score to 0-1 range.
        
        Qdrant cosine similarity is already in [-1, 1] range.
        Map to [0, 1] for consistency.
        """
        # Cosine similarity: -1 to 1 -> 0 to 1
        return (score + 1) / 2
    
    async def search_multi_vector(
        self,
        query_embeddings: list[list[float]],
        top_k: int = 10,
        filters: Optional[dict] = None,
        aggregation: str = "max"  # "max", "avg", or "rrf"
    ) -> SemanticSearchResponse:
        """
        Search with multiple query vectors (for multi-query expansion).
        
        Args:
            query_embeddings: List of query vectors
            top_k: Number of final results
            filters: ACL and metadata filters
            aggregation: How to combine scores from multiple queries
        
        Returns:
            Aggregated search results
        """
        if not self._client:
            await self.connect()
        
        start_time = time.time()
        
        # Execute searches for all query embeddings
        all_results = []
        for embedding in query_embeddings:
            response = await self.search(
                query_embedding=embedding,
                top_k=top_k * 2,  # Get more to allow for deduplication
                filters=filters,
                score_threshold=0.0
            )
            all_results.append(response.results)
        
        # Aggregate results
        aggregated = self._aggregate_results(all_results, aggregation, top_k)
        
        search_time = (time.time() - start_time) * 1000
        
        return SemanticSearchResponse(
            results=aggregated,
            total_found=len(aggregated),
            search_time_ms=search_time
        )
    
    def _aggregate_results(
        self,
        result_lists: list[list[SearchResultItem]],
        method: str,
        top_k: int
    ) -> list[SearchResultItem]:
        """
        Aggregate results from multiple queries.
        """
        # Track scores by chunk_id
        scores: dict[UUID, list[float]] = {}
        items: dict[UUID, SearchResultItem] = {}
        
        for results in result_lists:
            for item in results:
                if item.chunk_id not in scores:
                    scores[item.chunk_id] = []
                    items[item.chunk_id] = item
                scores[item.chunk_id].append(item.score)
        
        # Aggregate scores
        final_scores: dict[UUID, float] = {}
        
        if method == "max":
            for chunk_id, score_list in scores.items():
                final_scores[chunk_id] = max(score_list)
        elif method == "avg":
            for chunk_id, score_list in scores.items():
                final_scores[chunk_id] = sum(score_list) / len(score_list)
        elif method == "rrf":
            # Reciprocal Rank Fusion
            for chunk_id in scores:
                rrf_score = 0.0
                for results in result_lists:
                    for rank, item in enumerate(results, 1):
                        if item.chunk_id == chunk_id:
                            rrf_score += 1 / (60 + rank)
                            break
                final_scores[chunk_id] = rrf_score
        
        # Sort by final score and return top_k
        sorted_chunks = sorted(
            final_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        result = []
        for chunk_id, score in sorted_chunks:
            item = items[chunk_id].model_copy()
            item.score = score if method != "rrf" else min(score, 1.0)
            result.append(item)
        
        return result
    
    async def get_collection_info(self) -> dict:
        """Get collection statistics."""
        if not self._client:
            await self.connect()
        
        info = await self._client.get_collection(self.config.collection_name)
        
        return {
            "name": self.config.collection_name,
            "vectors_count": info.vectors_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "status": info.status.value
        }
    
    async def health_check(self) -> bool:
        """Check if Qdrant is healthy."""
        try:
            if not self._client:
                await self.connect()
            
            # Try to get collection info
            await self._client.get_collection(self.config.collection_name)
            return True
        except Exception:
            return False
    
    async def close(self):
        """Close Qdrant client."""
        if self._client:
            await self._client.close()
            self._client = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### Score Normalization Utilities

```python
import numpy as np
from typing import Callable

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
        
        return [
            (s - min_score) / (max_score - min_score)
            for s in scores
        ]
    
    @staticmethod
    def z_score(scores: list[float]) -> list[float]:
        """
        Z-score normalization (mean=0, std=1).
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
        method: str = "min_max"
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
        
        for result, norm_score in zip(results, normalized):
            result.score = norm_score
        
        return results
```

## Acceptance Criteria

- [ ] SemanticSearcher connects to Qdrant successfully
- [ ] Vector search returns top-k most similar documents
- [ ] HNSW parameters configurable (hnsw_ef for recall tuning)
- [ ] Score threshold filtering excludes low-relevance results
- [ ] ACL filters correctly applied to queries
- [ ] Metadata filters work (by tenant, source, date range, etc.)
- [ ] Scores normalized to 0-1 range
- [ ] Multi-vector search aggregates results correctly
- [ ] Collection info retrievable for monitoring
- [ ] Health check validates Qdrant connectivity
- [ ] Search latency < 50ms for 10 results (excluding network)

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

@pytest.fixture
def searcher():
    return SemanticSearcher()

@pytest.fixture
def mock_qdrant_results():
    """Mock Qdrant search results."""
    class MockResult:
        def __init__(self, id, score, payload):
            self.id = id
            self.score = score
            self.payload = payload
    
    return [
        MockResult(
            id=str(uuid4()),
            score=0.95,
            payload={
                "content": "Document about machine learning",
                "document_id": str(uuid4()),
                "title": "ML Guide",
                "source": "docs/ml.md"
            }
        ),
        MockResult(
            id=str(uuid4()),
            score=0.85,
            payload={
                "content": "Neural networks are a type of ML",
                "document_id": str(uuid4()),
                "title": "Neural Networks",
                "source": "docs/nn.md"
            }
        )
    ]

@pytest.mark.asyncio
async def test_search_returns_results(searcher, mock_qdrant_results):
    """Test that search returns properly formatted results."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value=mock_qdrant_results)
        
        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10
        )
        
        assert len(response.results) == 2
        assert response.results[0].score >= response.results[1].score
        assert response.results[0].content == "Document about machine learning"

@pytest.mark.asyncio
async def test_score_normalization(searcher, mock_qdrant_results):
    """Test that scores are normalized to 0-1 range."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value=mock_qdrant_results)
        
        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10
        )
        
        for result in response.results:
            assert 0.0 <= result.score <= 1.0

@pytest.mark.asyncio
async def test_filter_building(searcher):
    """Test Qdrant filter construction."""
    filter_dict = {
        "must": [
            {"key": "tenant_id", "match": {"value": "tenant-123"}}
        ],
        "should": [
            {"key": "visibility", "match": {"value": "public"}},
            {"key": "allowed_groups", "match": {"any": ["group-1", "group-2"]}}
        ]
    }
    
    qdrant_filter = searcher._build_filter(filter_dict)
    
    assert qdrant_filter.must is not None
    assert len(qdrant_filter.must) == 1
    assert qdrant_filter.should is not None
    assert len(qdrant_filter.should) == 2

@pytest.mark.asyncio
async def test_score_threshold_filtering(searcher):
    """Test that low scores are filtered out."""
    class MockResult:
        def __init__(self, id, score):
            self.id = str(uuid4())
            self.score = score
            self.payload = {"content": f"Score {score}", "document_id": str(uuid4())}
    
    mock_results = [
        MockResult(1, 0.9),
        MockResult(2, 0.5),
        MockResult(3, 0.2)
    ]
    
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value=mock_results)
        
        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=10,
            score_threshold=0.6  # Should filter out scores below 0.6
        )
        
        # Qdrant handles threshold internally
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs['score_threshold'] == 0.6

@pytest.mark.asyncio
async def test_multi_vector_aggregation():
    """Test multi-vector search aggregation."""
    searcher = SemanticSearcher()
    
    # Create mock results for two queries
    result1 = SearchResultItem(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Doc A",
        score=0.9
    )
    result2 = SearchResultItem(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Doc B",
        score=0.8
    )
    
    # Test max aggregation
    aggregated = searcher._aggregate_results(
        [[result1, result2], [result1]],  # result1 appears in both
        method="max",
        top_k=10
    )
    
    # result1 should have higher final score
    assert aggregated[0].chunk_id == result1.chunk_id
    assert aggregated[0].score == 0.9

def test_score_normalizer_min_max():
    """Test min-max score normalization."""
    scores = [0.5, 0.7, 0.9]
    normalized = ScoreNormalizer.min_max(scores)
    
    assert normalized[0] == 0.0  # Min
    assert normalized[2] == 1.0  # Max
    assert 0.0 < normalized[1] < 1.0  # Middle
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_search_with_real_qdrant():
    """Integration test with actual Qdrant instance."""
    config = QdrantConfig(
        url="http://localhost:6333",
        collection_name="test_documents"
    )
    
    async with SemanticSearcher(config) as searcher:
        # Verify connection
        assert await searcher.health_check()
        
        # Get collection info
        info = await searcher.get_collection_info()
        assert info["name"] == "test_documents"
        
        # Execute search with dummy embedding
        response = await searcher.search(
            query_embedding=[0.1] * 1024,
            top_k=5
        )
        
        assert response.search_time_ms > 0
        # Results depend on what's in the collection
```

## Dependencies

- `qdrant-client>=1.7.0`
- `numpy>=1.26.0`
- `pydantic>=2.0.0`

## Performance Requirements

- Search latency: < 50ms for 10 results (excluding network)
- Support for 1M+ vectors
- HNSW ef parameter tunable for recall/speed tradeoff
- Batch search support for multi-query

## Definition of Done

- [ ] SemanticSearcher implemented with all methods
- [ ] Qdrant connection management (connect, close, context manager)
- [ ] Filter building for ACL and metadata
- [ ] Score normalization to 0-1 range
- [ ] Multi-vector search with aggregation
- [ ] Health check and collection info
- [ ] >90% test coverage
- [ ] Integration test passes with Qdrant
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
