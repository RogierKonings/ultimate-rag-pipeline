# US-3.5: Reranker Integration

> **Story ID:** US-3.5  
> **Epic:** Retrieval Service  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-3.4 (Hybrid Fusion)

## User Story

**As a** developer  
**I want** cross-encoder reranking  
**So that** results are ordered by true relevance

## Context

Reranking uses a cross-encoder model to score query-document pairs directly, providing more accurate relevance scores than bi-encoder embeddings. Per the architecture, the reranker model is `BAAI/bge-reranker-v2-m3`, served via the LLM Gateway. Reranking is applied to the top-k results from hybrid fusion to improve final ordering while maintaining low latency.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── reranking/
    ├── __init__.py
    ├── reranker.py          # Reranker service
    ├── client.py            # LLM gateway client
    └── models.py            # Pydantic models
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

class RerankRequest(BaseModel):
    """Request for reranking."""
    query: str
    documents: list[str]  # Document contents to rerank
    document_ids: list[UUID]  # Corresponding IDs
    top_k: Optional[int] = None  # Return top k after reranking
    return_documents: bool = False  # Include document text in response

class RerankResult(BaseModel):
    """Single reranked result."""
    document_id: UUID
    index: int  # Original index in input
    relevance_score: float  # Cross-encoder score
    document: Optional[str] = None  # If return_documents=True

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
    max_query_length: int = 512
    max_document_length: int = 512
    
    # Performance
    timeout_seconds: float = 30.0
    
    # Score threshold
    score_threshold: float = 0.0  # Minimum score to include
    
    # Retry
    max_retries: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0
```

### Reranker Service Implementation

```python
import time
from typing import Optional
from uuid import UUID
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class RerankerService:
    """
    Cross-encoder reranking service.
    
    Uses BGE-reranker-v2-m3 via LLM Gateway to score query-document
    pairs directly. Cross-encoders are more accurate than bi-encoders
    but slower, so we only rerank top candidates.
    
    The model jointly encodes query and document, attending to both
    simultaneously, which captures fine-grained relevance signals.
    """
    
    def __init__(self, config: RerankerConfig = RerankerConfig()):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.llm_gateway_url,
            timeout=config.timeout_seconds
        )
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        document_ids: list[UUID],
        top_k: Optional[int] = None,
        return_documents: bool = False
    ) -> RerankResponse:
        """
        Rerank documents by relevance to query.
        
        Args:
            query: Search query
            documents: List of document contents
            document_ids: Corresponding document/chunk IDs
            top_k: Number of top results to return (None = all)
            return_documents: Include document text in response
        
        Returns:
            RerankResponse with reordered results
        """
        start_time = time.time()
        
        if len(documents) != len(document_ids):
            raise ValueError("documents and document_ids must have same length")
        
        if len(documents) > self.config.max_documents:
            raise ValueError(f"Too many documents: {len(documents)} > {self.config.max_documents}")
        
        if not documents:
            return RerankResponse(
                results=[],
                model=self.config.model,
                processing_time_ms=0.0
            )
        
        # Truncate query and documents if needed
        truncated_query = self._truncate(query, self.config.max_query_length)
        truncated_docs = [
            self._truncate(doc, self.config.max_document_length)
            for doc in documents
        ]
        
        # Call reranker in batches if needed
        all_scores = []
        for batch_start in range(0, len(truncated_docs), self.config.max_batch_size):
            batch_end = min(batch_start + self.config.max_batch_size, len(truncated_docs))
            batch_docs = truncated_docs[batch_start:batch_end]
            
            batch_scores = await self._rerank_batch(truncated_query, batch_docs)
            all_scores.extend(batch_scores)
        
        # Build results with original indices
        results = []
        for idx, (doc_id, score) in enumerate(zip(document_ids, all_scores)):
            if score >= self.config.score_threshold:
                results.append(RerankResult(
                    document_id=doc_id,
                    index=idx,
                    relevance_score=score,
                    document=documents[idx] if return_documents else None
                ))
        
        # Sort by score descending
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # Apply top_k limit
        if top_k is not None:
            results = results[:top_k]
        
        processing_time = (time.time() - start_time) * 1000
        
        return RerankResponse(
            results=results,
            model=self.config.model,
            processing_time_ms=processing_time
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    async def _rerank_batch(
        self,
        query: str,
        documents: list[str]
    ) -> list[float]:
        """
        Call LLM Gateway rerank endpoint for a batch.
        
        The API is modeled after Cohere's rerank API format.
        """
        response = await self._client.post(
            self.config.rerank_endpoint,
            json={
                "model": self.config.model,
                "query": query,
                "documents": documents,
                "return_documents": False
            }
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Extract scores, maintaining order
        # Response format: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
        scores = [0.0] * len(documents)
        for result in data["results"]:
            scores[result["index"]] = result["relevance_score"]
        
        return scores
    
    def _truncate(self, text: str, max_length: int) -> str:
        """
        Truncate text to max length (approximate token count).
        
        Uses character-based estimation: ~4 chars per token.
        """
        max_chars = max_length * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars]
    
    async def rerank_fused_results(
        self,
        query: str,
        fused_results: list["FusedResult"],
        top_k: Optional[int] = None
    ) -> list["FusedResult"]:
        """
        Convenience method to rerank FusedResult objects.
        
        Preserves all metadata and updates scores based on reranking.
        """
        if not fused_results:
            return []
        
        # Extract content and IDs
        documents = [r.content for r in fused_results]
        document_ids = [r.chunk_id for r in fused_results]
        
        # Rerank
        rerank_response = await self.rerank(
            query=query,
            documents=documents,
            document_ids=document_ids,
            top_k=top_k
        )
        
        # Build ID to result mapping
        result_map = {r.chunk_id: r for r in fused_results}
        
        # Rebuild results with rerank scores
        reranked = []
        for rr in rerank_response.results:
            original = result_map[rr.document_id]
            # Create new result with rerank score
            reranked_result = original.model_copy()
            reranked_result.fused_score = rr.relevance_score
            reranked_result.metadata["rerank_score"] = rr.relevance_score
            reranked_result.metadata["original_fused_score"] = original.fused_score
            reranked.append(reranked_result)
        
        return reranked
    
    async def health_check(self) -> bool:
        """Check if reranker service is healthy."""
        try:
            # Try a simple rerank call
            await self._rerank_batch("test", ["test document"])
            return True
        except Exception:
            return False
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### LLM Gateway Client (Fallback Local Inference)

```python
from typing import Optional
import numpy as np

class LocalRerankerFallback:
    """
    Fallback local reranker using transformers.
    
    Use when LLM Gateway is unavailable or for development.
    Requires: transformers, torch
    """
    
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cpu"
    ):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._tokenizer = None
    
    def _load_model(self):
        """Lazy load model."""
        if self._model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch
            
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name
            )
            self._model.to(self.device)
            self._model.eval()
    
    def rerank_sync(
        self,
        query: str,
        documents: list[str],
        top_k: Optional[int] = None
    ) -> list[tuple[int, float]]:
        """
        Synchronous reranking for local inference.
        
        Returns:
            List of (original_index, score) tuples, sorted by score descending
        """
        import torch
        
        self._load_model()
        
        # Create query-document pairs
        pairs = [[query, doc] for doc in documents]
        
        # Tokenize
        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt"
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        # Get scores
        with torch.no_grad():
            outputs = self._model(**inputs)
            scores = outputs.logits.squeeze(-1).cpu().numpy()
        
        # Apply sigmoid for probability-like scores
        scores = 1 / (1 + np.exp(-scores))
        
        # Sort by score
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        
        if top_k:
            indexed_scores = indexed_scores[:top_k]
        
        return indexed_scores


class HybridReranker:
    """
    Reranker that tries LLM Gateway first, falls back to local.
    """
    
    def __init__(
        self,
        config: RerankerConfig = RerankerConfig(),
        enable_fallback: bool = True
    ):
        self.primary = RerankerService(config)
        self.fallback = LocalRerankerFallback() if enable_fallback else None
        self._use_fallback = False
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        document_ids: list[UUID],
        top_k: Optional[int] = None
    ) -> RerankResponse:
        """
        Rerank with automatic fallback.
        """
        import time
        import asyncio
        
        start_time = time.time()
        
        if not self._use_fallback:
            try:
                return await self.primary.rerank(
                    query=query,
                    documents=documents,
                    document_ids=document_ids,
                    top_k=top_k
                )
            except Exception as e:
                if self.fallback:
                    self._use_fallback = True
                    # Log warning about fallback
                else:
                    raise
        
        # Use fallback (run in thread pool to not block)
        if self.fallback:
            loop = asyncio.get_event_loop()
            indexed_scores = await loop.run_in_executor(
                None,
                self.fallback.rerank_sync,
                query,
                documents,
                top_k
            )
            
            results = [
                RerankResult(
                    document_id=document_ids[idx],
                    index=idx,
                    relevance_score=float(score)
                )
                for idx, score in indexed_scores
            ]
            
            processing_time = (time.time() - start_time) * 1000
            
            return RerankResponse(
                results=results,
                model=self.fallback.model_name + " (local)",
                processing_time_ms=processing_time
            )
        
        raise RuntimeError("No reranker available")
    
    async def close(self):
        """Close resources."""
        await self.primary.close()
```

### Reranker with Caching

```python
import hashlib
import json
from typing import Optional
import redis.asyncio as redis

class CachedReranker:
    """
    Reranker with Redis caching for repeated queries.
    
    Caches query-document pair scores to avoid redundant
    cross-encoder inference.
    """
    
    def __init__(
        self,
        reranker: RerankerService,
        redis_url: str = "redis://localhost:6379",
        cache_ttl: int = 3600,
        key_prefix: str = "rerank:"
    ):
        self.reranker = reranker
        self.redis_url = redis_url
        self.cache_ttl = cache_ttl
        self.key_prefix = key_prefix
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis
    
    def _cache_key(self, query: str, document: str) -> str:
        """Generate cache key for query-document pair."""
        content = f"{self.reranker.config.model}:{query}:{document}"
        hash_val = hashlib.sha256(content.encode()).hexdigest()
        return f"{self.key_prefix}{hash_val}"
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        document_ids: list[UUID],
        top_k: Optional[int] = None
    ) -> RerankResponse:
        """
        Rerank with caching.
        """
        import time
        
        start_time = time.time()
        r = await self._get_redis()
        
        # Check cache for each document
        cached_scores: dict[int, float] = {}
        uncached_indices: list[int] = []
        uncached_docs: list[str] = []
        
        for i, doc in enumerate(documents):
            key = self._cache_key(query, doc)
            cached = await r.get(key)
            
            if cached is not None:
                cached_scores[i] = float(cached)
            else:
                uncached_indices.append(i)
                uncached_docs.append(doc)
        
        # Rerank uncached documents
        if uncached_docs:
            uncached_ids = [document_ids[i] for i in uncached_indices]
            response = await self.reranker.rerank(
                query=query,
                documents=uncached_docs,
                document_ids=uncached_ids,
                top_k=None  # Get all, we'll filter later
            )
            
            # Cache new scores
            for result in response.results:
                original_idx = uncached_indices[result.index]
                cached_scores[original_idx] = result.relevance_score
                
                key = self._cache_key(query, documents[original_idx])
                await r.setex(key, self.cache_ttl, str(result.relevance_score))
        
        # Build final results
        results = []
        for idx in range(len(documents)):
            score = cached_scores.get(idx, 0.0)
            if score >= self.reranker.config.score_threshold:
                results.append(RerankResult(
                    document_id=document_ids[idx],
                    index=idx,
                    relevance_score=score
                ))
        
        # Sort and limit
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        if top_k:
            results = results[:top_k]
        
        processing_time = (time.time() - start_time) * 1000
        
        return RerankResponse(
            results=results,
            model=self.reranker.config.model,
            processing_time_ms=processing_time
        )
    
    async def close(self):
        """Close resources."""
        if self._redis:
            await self._redis.close()
        await self.reranker.close()
```

## Acceptance Criteria

- [ ] RerankerService calls LLM Gateway rerank endpoint
- [ ] BGE-reranker-v2-m3 model used by default
- [ ] Batch processing for large document sets (max 32 per batch)
- [ ] Query and document truncation to max length
- [ ] Score threshold filtering (configurable, default 0.0)
- [ ] Top-k limiting after reranking
- [ ] Retry logic with exponential backoff
- [ ] Latency < 100ms for 20 documents
- [ ] Convenience method for reranking FusedResult objects
- [ ] Local fallback reranker available
- [ ] Optional Redis caching for repeated queries
- [ ] Health check endpoint

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def reranker():
    return RerankerService()

@pytest.fixture
def mock_rerank_response():
    """Mock LLM Gateway rerank response."""
    return {
        "results": [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.75},
            {"index": 2, "relevance_score": 0.45}
        ]
    }

@pytest.mark.asyncio
async def test_rerank_returns_sorted_results(reranker, mock_rerank_response):
    """Test that rerank returns results sorted by score."""
    with patch.object(reranker._client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_rerank_response
        )
        mock.return_value.raise_for_status = lambda: None
        
        response = await reranker.rerank(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            document_ids=[uuid4(), uuid4(), uuid4()]
        )
        
        assert len(response.results) == 3
        assert response.results[0].relevance_score == 0.95
        assert response.results[1].relevance_score == 0.75
        assert response.results[2].relevance_score == 0.45

@pytest.mark.asyncio
async def test_top_k_limits_results(reranker, mock_rerank_response):
    """Test that top_k limits returned results."""
    with patch.object(reranker._client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_rerank_response
        )
        mock.return_value.raise_for_status = lambda: None
        
        response = await reranker.rerank(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            document_ids=[uuid4(), uuid4(), uuid4()],
            top_k=2
        )
        
        assert len(response.results) == 2

@pytest.mark.asyncio
async def test_score_threshold_filtering(reranker):
    """Test that low scores are filtered."""
    reranker.config.score_threshold = 0.5
    
    mock_response = {
        "results": [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.3}  # Below threshold
        ]
    }
    
    with patch.object(reranker._client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_response
        )
        mock.return_value.raise_for_status = lambda: None
        
        response = await reranker.rerank(
            query="test",
            documents=["doc1", "doc2"],
            document_ids=[uuid4(), uuid4()]
        )
        
        assert len(response.results) == 1
        assert response.results[0].relevance_score == 0.95

@pytest.mark.asyncio
async def test_batching_large_document_sets(reranker):
    """Test that large document sets are batched."""
    reranker.config.max_batch_size = 2
    
    # Mock response for each batch
    call_count = 0
    
    def mock_response():
        nonlocal call_count
        call_count += 1
        return {
            "results": [
                {"index": 0, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.8}
            ]
        }
    
    with patch.object(reranker._client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=mock_response
        )
        mock.return_value.raise_for_status = lambda: None
        
        await reranker.rerank(
            query="test",
            documents=["d1", "d2", "d3", "d4"],  # 4 docs, batch size 2
            document_ids=[uuid4() for _ in range(4)]
        )
        
        assert mock.call_count == 2  # 2 batches

@pytest.mark.asyncio
async def test_truncation(reranker):
    """Test that long text is truncated."""
    reranker.config.max_query_length = 10
    reranker.config.max_document_length = 10
    
    # 10 tokens * 4 chars = 40 chars max
    long_text = "a" * 100
    
    truncated = reranker._truncate(long_text, 10)
    
    assert len(truncated) == 40

@pytest.mark.asyncio
async def test_rerank_fused_results(reranker):
    """Test convenience method for FusedResult objects."""
    fused = [
        FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="First document",
            fused_score=0.8
        ),
        FusedResult(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Second document",
            fused_score=0.9
        )
    ]
    
    mock_response = {
        "results": [
            {"index": 0, "relevance_score": 0.6},  # First doc now lower
            {"index": 1, "relevance_score": 0.95}  # Second doc still higher
        ]
    }
    
    with patch.object(reranker._client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_response
        )
        mock.return_value.raise_for_status = lambda: None
        
        reranked = await reranker.rerank_fused_results(
            query="test",
            fused_results=fused
        )
        
        # Should be reordered by rerank score
        assert reranked[0].fused_score == 0.95
        assert reranked[1].fused_score == 0.6

def test_local_reranker_fallback():
    """Test local reranker fallback (requires transformers)."""
    pytest.importorskip("transformers")
    
    fallback = LocalRerankerFallback(device="cpu")
    
    results = fallback.rerank_sync(
        query="What is machine learning?",
        documents=[
            "Machine learning is a type of AI.",
            "The weather is nice today.",
            "ML algorithms learn from data."
        ],
        top_k=2
    )
    
    # ML-related docs should rank higher
    assert len(results) == 2
    assert results[0][1] > results[1][1]
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_reranker_with_real_llm_gateway():
    """Integration test with actual LLM Gateway."""
    config = RerankerConfig(
        llm_gateway_url="http://localhost:8004"
    )
    
    async with RerankerService(config) as reranker:
        response = await reranker.rerank(
            query="What is machine learning?",
            documents=[
                "Machine learning is a subset of artificial intelligence.",
                "The stock market closed higher today.",
                "Deep learning uses neural networks."
            ],
            document_ids=[uuid4() for _ in range(3)]
        )
        
        assert len(response.results) == 3
        assert response.model == "BAAI/bge-reranker-v2-m3"
        # ML-related docs should rank higher
        assert response.results[0].relevance_score > response.results[1].relevance_score
```

## Dependencies

- `httpx>=0.25.0`
- `redis>=5.0.0`
- `tenacity>=8.2.0`
- `pydantic>=2.0.0`
- `transformers>=4.35.0` (optional, for local fallback)
- `torch>=2.0.0` (optional, for local fallback)

## Performance Requirements

- Latency: < 100ms for 20 documents via LLM Gateway
- Batch size: 32 documents per batch
- Max documents: 100 per request
- Cache hit latency: < 10ms

## Definition of Done

- [ ] RerankerService implemented with LLM Gateway integration
- [ ] Batch processing for large document sets
- [ ] Text truncation to model limits
- [ ] Score threshold filtering
- [ ] Top-k limiting
- [ ] Retry logic with exponential backoff
- [ ] Convenience method for FusedResult reranking
- [ ] Local fallback reranker (optional)
- [ ] Redis caching (optional)
- [ ] Health check
- [ ] >90% test coverage
- [ ] Integration test passes with LLM Gateway
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
