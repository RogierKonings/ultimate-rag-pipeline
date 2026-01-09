# US-3.4: Hybrid Fusion

> **Story ID:** US-3.4  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** US-3.2 (Semantic Search), US-3.3 (Keyword Search)

## User Story

**As a** developer  
**I want** result fusion from multiple search methods  
**So that** I get the best of both semantic and keyword search

## Context

Hybrid search combines the strengths of semantic search (understanding meaning) and keyword search (exact matches). Reciprocal Rank Fusion (RRF) is the standard algorithm for combining ranked lists from different sources. Per the architecture, the default weights are 0.7 semantic / 0.3 keyword, but these should be configurable.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── search/
    ├── __init__.py
    ├── fusion.py            # Hybrid fusion algorithms
    └── hybrid.py            # Hybrid search orchestrator
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
from enum import Enum

class FusionMethod(str, Enum):
    RRF = "rrf"                    # Reciprocal Rank Fusion
    LINEAR = "linear"              # Linear weighted combination
    CONVEX = "convex"              # Convex combination (weights sum to 1)
    DBSF = "dbsf"                  # Distribution-Based Score Fusion

class HybridSearchConfig(BaseModel):
    """Configuration for hybrid search."""
    # Weights
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    
    # Fusion method
    fusion_method: FusionMethod = FusionMethod.RRF
    
    # RRF parameters
    rrf_k: int = 60  # Constant to prevent high-ranked items from dominating
    
    # Result limits
    top_k: int = Field(default=10, ge=1, le=100)
    semantic_top_k: int = Field(default=50, ge=1, le=200)  # Fetch more for fusion
    keyword_top_k: int = Field(default=50, ge=1, le=200)
    
    # Score thresholds
    min_score: float = 0.0
    
    # Deduplication
    deduplicate: bool = True
    
    def model_post_init(self, __context) -> None:
        """Validate that weights are sensible."""
        if self.fusion_method == FusionMethod.CONVEX:
            total = self.semantic_weight + self.keyword_weight
            if abs(total - 1.0) > 0.001:
                raise ValueError("Convex fusion requires weights to sum to 1.0")

class HybridSearchRequest(BaseModel):
    """Request for hybrid search."""
    query: str
    query_embedding: list[float]
    top_k: int = 10
    filters: Optional[dict] = None
    config: Optional[HybridSearchConfig] = None

class FusedResult(BaseModel):
    """A single fused result with provenance."""
    chunk_id: UUID
    document_id: UUID
    content: str
    fused_score: float
    semantic_score: Optional[float] = None
    semantic_rank: Optional[int] = None
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None
    metadata: dict = {}
    title: Optional[str] = None
    source: Optional[str] = None

class HybridSearchResponse(BaseModel):
    """Response from hybrid search."""
    results: list[FusedResult]
    total_semantic: int
    total_keyword: int
    search_time_ms: float
    fusion_method: FusionMethod
```

### Reciprocal Rank Fusion Implementation

```python
from typing import Optional
from uuid import UUID
from collections import defaultdict

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
        semantic_results: list["SearchResultItem"],
        keyword_results: list["SearchResultItem"],
        top_k: int = 10
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
                    "source": result.source
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
                    "source": result.source
                }
        
        # Sort by RRF score
        sorted_chunks = sorted(
            rrf_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        # Build fused results
        results = []
        for chunk_id, rrf_score in sorted_chunks:
            item = items[chunk_id]
            sem_score, sem_rank = semantic_info.get(chunk_id, (None, None))
            kw_score, kw_rank = keyword_info.get(chunk_id, (None, None))
            
            results.append(FusedResult(
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
                source=item["source"]
            ))
        
        return results


class LinearFusion:
    """
    Linear weighted combination of scores.
    
    Combines normalized scores from both search methods using
    configurable weights: fused = w_sem * sem_score + w_kw * kw_score
    """
    
    def __init__(
        self,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3
    ):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
    
    def fuse(
        self,
        semantic_results: list["SearchResultItem"],
        keyword_results: list["SearchResultItem"],
        top_k: int = 10
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
                    "source": result.source
                }
        
        for result in keyword_results:
            keyword_scores[result.chunk_id] = result.score
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source
                }
        
        # Calculate fused scores
        all_chunks = set(semantic_scores.keys()) | set(keyword_scores.keys())
        fused_scores: dict[UUID, float] = {}
        
        for chunk_id in all_chunks:
            sem_score = semantic_scores.get(chunk_id, 0.0)
            kw_score = keyword_scores.get(chunk_id, 0.0)
            
            fused = (
                self.semantic_weight * sem_score +
                self.keyword_weight * kw_score
            )
            fused_scores[chunk_id] = fused
        
        # Sort and build results
        sorted_chunks = sorted(
            fused_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        results = []
        for chunk_id, fused_score in sorted_chunks:
            item = items[chunk_id]
            results.append(FusedResult(
                chunk_id=chunk_id,
                document_id=item["document_id"],
                content=item["content"],
                fused_score=fused_score,
                semantic_score=semantic_scores.get(chunk_id),
                keyword_score=keyword_scores.get(chunk_id),
                metadata=item["metadata"],
                title=item["title"],
                source=item["source"]
            ))
        
        return results


class DistributionBasedScoreFusion:
    """
    Distribution-Based Score Fusion (DBSF).
    
    Normalizes scores based on the score distribution of each
    retriever, then combines. More robust to different score
    distributions than simple linear fusion.
    
    Formula: normalized = (score - μ) / σ, then combine
    """
    
    def __init__(
        self,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3
    ):
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
    
    def fuse(
        self,
        semantic_results: list["SearchResultItem"],
        keyword_results: list["SearchResultItem"],
        top_k: int = 10
    ) -> list[FusedResult]:
        """
        Fuse results using distribution-based normalization.
        """
        import numpy as np
        
        # Extract and normalize semantic scores
        sem_scores = [r.score for r in semantic_results]
        if sem_scores:
            sem_mean = np.mean(sem_scores)
            sem_std = np.std(sem_scores) or 1.0
            sem_normalized = {
                r.chunk_id: (r.score - sem_mean) / sem_std
                for r in semantic_results
            }
        else:
            sem_normalized = {}
        
        # Extract and normalize keyword scores
        kw_scores = [r.score for r in keyword_results]
        if kw_scores:
            kw_mean = np.mean(kw_scores)
            kw_std = np.std(kw_scores) or 1.0
            kw_normalized = {
                r.chunk_id: (r.score - kw_mean) / kw_std
                for r in keyword_results
            }
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
                    "source": result.source
                }
            original_scores[result.chunk_id] = (result.score, None)
        
        for result in keyword_results:
            if result.chunk_id not in items:
                items[result.chunk_id] = {
                    "document_id": result.document_id,
                    "content": result.content,
                    "metadata": result.metadata,
                    "title": result.title,
                    "source": result.source
                }
            if result.chunk_id in original_scores:
                original_scores[result.chunk_id] = (
                    original_scores[result.chunk_id][0],
                    result.score
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
        sorted_chunks = sorted(
            fused_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        results = []
        for chunk_id, fused_score in sorted_chunks:
            item = items[chunk_id]
            sem_orig, kw_orig = original_scores.get(chunk_id, (None, None))
            
            results.append(FusedResult(
                chunk_id=chunk_id,
                document_id=item["document_id"],
                content=item["content"],
                fused_score=float(fused_score),
                semantic_score=sem_orig,
                keyword_score=kw_orig,
                metadata=item["metadata"],
                title=item["title"],
                source=item["source"]
            ))
        
        return results
```

### Hybrid Search Orchestrator

```python
import asyncio
import time
from typing import Optional

class HybridSearcher:
    """
    Orchestrates hybrid search by running semantic and keyword
    search in parallel, then fusing results.
    """
    
    def __init__(
        self,
        semantic_searcher: "SemanticSearcher",
        keyword_searcher: "KeywordSearcher",
        config: HybridSearchConfig = HybridSearchConfig()
    ):
        self.semantic = semantic_searcher
        self.keyword = keyword_searcher
        self.config = config
        
        # Initialize fusion algorithm
        self._fusion = self._create_fusion()
    
    def _create_fusion(self):
        """Create fusion algorithm based on config."""
        if self.config.fusion_method == FusionMethod.RRF:
            return ReciprocalRankFusion(k=self.config.rrf_k)
        elif self.config.fusion_method == FusionMethod.LINEAR:
            return LinearFusion(
                semantic_weight=self.config.semantic_weight,
                keyword_weight=self.config.keyword_weight
            )
        elif self.config.fusion_method == FusionMethod.DBSF:
            return DistributionBasedScoreFusion(
                semantic_weight=self.config.semantic_weight,
                keyword_weight=self.config.keyword_weight
            )
        else:
            raise ValueError(f"Unknown fusion method: {self.config.fusion_method}")
    
    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: Optional[int] = None,
        filters: Optional[dict] = None,
        config: Optional[HybridSearchConfig] = None
    ) -> HybridSearchResponse:
        """
        Execute hybrid search combining semantic and keyword search.
        
        Args:
            query: Text query for keyword search
            query_embedding: Query embedding for semantic search
            top_k: Number of final results (overrides config)
            filters: ACL and metadata filters
            config: Override default config for this search
        
        Returns:
            HybridSearchResponse with fused results
        """
        start_time = time.time()
        
        # Use provided config or default
        cfg = config or self.config
        final_top_k = top_k or cfg.top_k
        
        # Update fusion if config changed
        if config:
            self._fusion = self._create_fusion()
        
        # Run both searches in parallel
        semantic_task = self.semantic.search(
            query_embedding=query_embedding,
            top_k=cfg.semantic_top_k,
            filters=filters,
            score_threshold=0.0
        )
        
        keyword_task = self.keyword.search(
            query=query,
            top_k=cfg.keyword_top_k,
            filters=filters,
            min_score=0.0
        )
        
        semantic_response, keyword_response = await asyncio.gather(
            semantic_task,
            keyword_task
        )
        
        # Fuse results
        fused_results = self._fusion.fuse(
            semantic_results=semantic_response.results,
            keyword_results=keyword_response.results,
            top_k=final_top_k
        )
        
        # Apply score threshold
        if cfg.min_score > 0:
            fused_results = [
                r for r in fused_results
                if r.fused_score >= cfg.min_score
            ]
        
        # Deduplicate if needed (by document_id, keeping highest scored chunk)
        if cfg.deduplicate:
            fused_results = self._deduplicate(fused_results)
        
        search_time = (time.time() - start_time) * 1000
        
        return HybridSearchResponse(
            results=fused_results,
            total_semantic=semantic_response.total_found,
            total_keyword=keyword_response.total_found,
            search_time_ms=search_time,
            fusion_method=cfg.fusion_method
        )
    
    def _deduplicate(
        self,
        results: list[FusedResult]
    ) -> list[FusedResult]:
        """
        Remove duplicate chunks from the same document.
        
        Keeps the highest-scored chunk from each document.
        """
        seen_docs: dict[UUID, FusedResult] = {}
        
        for result in results:
            doc_id = result.document_id
            if doc_id not in seen_docs:
                seen_docs[doc_id] = result
            elif result.fused_score > seen_docs[doc_id].fused_score:
                seen_docs[doc_id] = result
        
        # Maintain score order
        return sorted(
            seen_docs.values(),
            key=lambda r: r.fused_score,
            reverse=True
        )
    
    async def search_semantic_only(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None
    ) -> HybridSearchResponse:
        """
        Bypass hybrid fusion and use semantic search only.
        
        Useful for queries where exact keywords don't matter.
        """
        start_time = time.time()
        
        response = await self.semantic.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters
        )
        
        # Convert to FusedResult format
        fused_results = [
            FusedResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                content=r.content,
                fused_score=r.score,
                semantic_score=r.score,
                semantic_rank=i + 1,
                metadata=r.metadata,
                title=r.title,
                source=r.source
            )
            for i, r in enumerate(response.results)
        ]
        
        search_time = (time.time() - start_time) * 1000
        
        return HybridSearchResponse(
            results=fused_results,
            total_semantic=response.total_found,
            total_keyword=0,
            search_time_ms=search_time,
            fusion_method=FusionMethod.RRF  # N/A but required
        )
    
    async def search_keyword_only(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None
    ) -> HybridSearchResponse:
        """
        Bypass hybrid fusion and use keyword search only.
        
        Useful for exact term lookups.
        """
        start_time = time.time()
        
        response = await self.keyword.search(
            query=query,
            top_k=top_k,
            filters=filters
        )
        
        # Convert to FusedResult format
        fused_results = [
            FusedResult(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                content=r.content,
                fused_score=r.score,
                keyword_score=r.score,
                keyword_rank=i + 1,
                metadata=r.metadata,
                title=r.title,
                source=r.source
            )
            for i, r in enumerate(response.results)
        ]
        
        search_time = (time.time() - start_time) * 1000
        
        return HybridSearchResponse(
            results=fused_results,
            total_semantic=0,
            total_keyword=response.total_found,
            search_time_ms=search_time,
            fusion_method=FusionMethod.RRF
        )
```

## Acceptance Criteria

- [ ] RRF fusion correctly combines ranked lists
- [ ] Linear weighted fusion combines normalized scores
- [ ] DBSF handles different score distributions
- [ ] Semantic and keyword searches run in parallel
- [ ] Configurable weights (default 0.7 semantic / 0.3 keyword)
- [ ] Configurable RRF k parameter (default 60)
- [ ] Score threshold filtering removes low-scored results
- [ ] Deduplication keeps highest-scored chunk per document
- [ ] FusedResult includes provenance (original scores and ranks)
- [ ] Semantic-only and keyword-only modes available
- [ ] Total search time < sum of individual search times (parallel)

## Testing Requirements

```python
import pytest
from uuid import uuid4

@pytest.fixture
def sample_semantic_results():
    """Sample semantic search results."""
    return [
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="A", score=0.95),
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="B", score=0.85),
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="C", score=0.75),
    ]

@pytest.fixture
def sample_keyword_results():
    """Sample keyword search results."""
    return [
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="B2", score=0.90),
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="D", score=0.80),
        SearchResultItem(chunk_id=uuid4(), document_id=uuid4(), content="C2", score=0.70),
    ]

def test_rrf_fusion_basic():
    """Test basic RRF fusion."""
    rrf = ReciprocalRankFusion(k=60)
    
    # Create results with known IDs
    chunk_a = uuid4()
    chunk_b = uuid4()
    
    semantic = [
        SearchResultItem(chunk_id=chunk_a, document_id=uuid4(), content="A", score=0.9),
        SearchResultItem(chunk_id=chunk_b, document_id=uuid4(), content="B", score=0.8),
    ]
    keyword = [
        SearchResultItem(chunk_id=chunk_b, document_id=uuid4(), content="B", score=0.9),  # B is #1 here
        SearchResultItem(chunk_id=chunk_a, document_id=uuid4(), content="A", score=0.7),
    ]
    
    results = rrf.fuse(semantic, keyword, top_k=10)
    
    # B should rank higher (ranked #2 semantic + #1 keyword vs #1 + #2)
    assert results[0].chunk_id == chunk_b

def test_rrf_score_calculation():
    """Test RRF score calculation formula."""
    rrf = ReciprocalRankFusion(k=60)
    
    chunk_id = uuid4()
    
    semantic = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=0.9)
    ]
    keyword = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=0.9)
    ]
    
    results = rrf.fuse(semantic, keyword, top_k=10)
    
    # Expected: 1/(60+1) + 1/(60+1) = 2/61
    expected_score = 2 / 61
    assert abs(results[0].fused_score - expected_score) < 0.0001

def test_linear_fusion():
    """Test linear weighted fusion."""
    fusion = LinearFusion(semantic_weight=0.7, keyword_weight=0.3)
    
    chunk_id = uuid4()
    
    semantic = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=1.0)
    ]
    keyword = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=0.5)
    ]
    
    results = fusion.fuse(semantic, keyword, top_k=10)
    
    # Expected: 0.7 * 1.0 + 0.3 * 0.5 = 0.85
    assert abs(results[0].fused_score - 0.85) < 0.0001

def test_deduplication():
    """Test document deduplication."""
    doc_id = uuid4()
    
    results = [
        FusedResult(chunk_id=uuid4(), document_id=doc_id, content="C1", fused_score=0.9),
        FusedResult(chunk_id=uuid4(), document_id=doc_id, content="C2", fused_score=0.95),  # Higher
        FusedResult(chunk_id=uuid4(), document_id=uuid4(), content="D", fused_score=0.8),
    ]
    
    from search.hybrid import HybridSearcher
    deduped = HybridSearcher._deduplicate(None, results)
    
    assert len(deduped) == 2
    assert deduped[0].fused_score == 0.95  # Kept higher scored chunk

def test_provenance_tracking():
    """Test that fusion tracks original scores and ranks."""
    rrf = ReciprocalRankFusion(k=60)
    
    chunk_id = uuid4()
    
    semantic = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=0.9)
    ]
    keyword = [
        SearchResultItem(chunk_id=chunk_id, document_id=uuid4(), content="A", score=0.8)
    ]
    
    results = rrf.fuse(semantic, keyword, top_k=10)
    
    assert results[0].semantic_score == 0.9
    assert results[0].semantic_rank == 1
    assert results[0].keyword_score == 0.8
    assert results[0].keyword_rank == 1

@pytest.mark.asyncio
async def test_parallel_search():
    """Test that searches run in parallel."""
    import time
    from unittest.mock import AsyncMock
    
    # Create mock searchers with delays
    semantic = AsyncMock()
    keyword = AsyncMock()
    
    async def slow_semantic(*args, **kwargs):
        await asyncio.sleep(0.1)
        return SemanticSearchResponse(results=[], total_found=0, search_time_ms=100)
    
    async def slow_keyword(*args, **kwargs):
        await asyncio.sleep(0.1)
        return KeywordSearchResponse(results=[], total_found=0, search_time_ms=100)
    
    semantic.search = slow_semantic
    keyword.search = slow_keyword
    
    hybrid = HybridSearcher(semantic, keyword)
    
    start = time.time()
    await hybrid.search("test", [0.1] * 1024)
    elapsed = time.time() - start
    
    # Should take ~0.1s (parallel), not ~0.2s (sequential)
    assert elapsed < 0.15
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_end_to_end():
    """Integration test with real Qdrant and OpenSearch."""
    from search.semantic import SemanticSearcher, QdrantConfig
    from search.keyword import KeywordSearcher, OpenSearchConfig
    
    semantic = SemanticSearcher(QdrantConfig(url="http://localhost:6333"))
    keyword = KeywordSearcher(OpenSearchConfig(url="http://localhost:9200"))
    
    config = HybridSearchConfig(
        semantic_weight=0.7,
        keyword_weight=0.3,
        fusion_method=FusionMethod.RRF
    )
    
    async with semantic, keyword:
        hybrid = HybridSearcher(semantic, keyword, config)
        
        response = await hybrid.search(
            query="machine learning",
            query_embedding=[0.1] * 1024,
            top_k=10
        )
        
        assert response.fusion_method == FusionMethod.RRF
        assert response.search_time_ms > 0
        # Results depend on indexed data
```

## Dependencies

- `numpy>=1.26.0` (for DBSF)
- `pydantic>=2.0.0`

## Performance Requirements

- Fusion computation: < 5ms for 100 results
- Total hybrid search: < 100ms (dominated by search backends)
- Parallel search speedup: ~2x vs sequential

## Definition of Done

- [ ] RRF fusion implemented with configurable k
- [ ] Linear weighted fusion implemented
- [ ] DBSF fusion implemented
- [ ] HybridSearcher orchestrates parallel search
- [ ] Configurable weights (0.7/0.3 default)
- [ ] Score threshold filtering
- [ ] Document deduplication
- [ ] Provenance tracking (original scores/ranks)
- [ ] Semantic-only and keyword-only modes
- [ ] >90% test coverage
- [ ] Integration test passes
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
