# US-2.4: Embedding Service

> **Story ID:** US-2.4  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-2.3 (Chunking Engine)

## User Story

**As a** developer  
**I want** efficient embedding generation  
**So that** documents can be vectorized for search

## Context

The embedding service generates vector representations of document chunks for semantic search. Per the architecture, the primary model is `BAAI/bge-large-en-v1.5` (1024 dimensions). The service must support batching for efficiency, Redis-based caching to avoid redundant computation, and retry logic for reliability.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── embedding/
    ├── __init__.py
    ├── service.py        # Embedding generation service
    ├── cache.py          # Redis-based embedding cache
    ├── models.py         # Pydantic models
    └── client.py         # LLM gateway client
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

class EmbeddingRequest(BaseModel):
    texts: list[str]
    model: str = "BAAI/bge-large-en-v1.5"
    normalize: bool = True
    prefix: Optional[str] = None  # BGE models use "query: " or "passage: " prefix

class EmbeddingResult(BaseModel):
    chunk_id: UUID
    embedding: list[float]
    model: str
    dimensions: int
    cached: bool = False

class BatchEmbeddingResult(BaseModel):
    results: list[EmbeddingResult]
    total_tokens: int
    processing_time_ms: float
    cache_hits: int
    cache_misses: int
```

### Embedding Service

```python
import asyncio
import hashlib
import time
from typing import Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class EmbeddingServiceConfig(BaseModel):
    model: str = "BAAI/bge-large-en-v1.5"
    dimensions: int = 1024
    max_batch_size: int = 32
    max_tokens_per_batch: int = 8192
    normalize_embeddings: bool = True
    cache_enabled: bool = True
    cache_ttl_seconds: int = 86400 * 7  # 7 days
    
    # LLM Gateway settings (architecture: port 8004)
    llm_gateway_url: str = "http://localhost:8004"
    embedding_endpoint: str = "/v1/embeddings"
    
    # Retry settings
    max_retries: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0
    
    # Request timeout
    timeout_seconds: float = 60.0

class EmbeddingService:
    """
    Service for generating embeddings with batching and caching.
    
    Uses the LLM Gateway which serves embedding models via OpenAI-compatible API.
    """
    
    def __init__(
        self,
        config: EmbeddingServiceConfig = EmbeddingServiceConfig(),
        cache: Optional["EmbeddingCache"] = None
    ):
        self.config = config
        self.cache = cache
        self._client = httpx.AsyncClient(
            base_url=config.llm_gateway_url,
            timeout=config.timeout_seconds
        )
    
    async def embed_texts(
        self,
        texts: list[str],
        chunk_ids: list[UUID],
        prefix: Optional[str] = "passage: "  # BGE prefix for documents
    ) -> BatchEmbeddingResult:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed
            chunk_ids: Corresponding chunk IDs for each text
            prefix: Prefix to add to texts (BGE models use "query: " or "passage: ")
        
        Returns:
            BatchEmbeddingResult with embeddings and metadata
        """
        start_time = time.time()
        results = []
        cache_hits = 0
        cache_misses = 0
        total_tokens = 0
        
        # Add prefix to texts
        prefixed_texts = [f"{prefix}{t}" if prefix else t for t in texts]
        
        # Check cache for existing embeddings
        texts_to_embed = []
        chunk_ids_to_embed = []
        cached_results = {}
        
        if self.cache and self.config.cache_enabled:
            for i, (text, chunk_id) in enumerate(zip(prefixed_texts, chunk_ids)):
                cache_key = self._get_cache_key(text)
                cached = await self.cache.get(cache_key)
                if cached is not None:
                    cache_hits += 1
                    cached_results[i] = EmbeddingResult(
                        chunk_id=chunk_id,
                        embedding=cached,
                        model=self.config.model,
                        dimensions=self.config.dimensions,
                        cached=True
                    )
                else:
                    cache_misses += 1
                    texts_to_embed.append(text)
                    chunk_ids_to_embed.append((i, chunk_id))
        else:
            texts_to_embed = prefixed_texts
            chunk_ids_to_embed = list(enumerate(chunk_ids))
            cache_misses = len(texts)
        
        # Generate embeddings for uncached texts in batches
        if texts_to_embed:
            batches = self._create_batches(texts_to_embed, chunk_ids_to_embed)
            
            for batch_texts, batch_ids in batches:
                embeddings, tokens = await self._embed_batch(batch_texts)
                total_tokens += tokens
                
                for (original_idx, chunk_id), embedding in zip(batch_ids, embeddings):
                    # Normalize if configured
                    if self.config.normalize_embeddings:
                        embedding = self._normalize(embedding)
                    
                    result = EmbeddingResult(
                        chunk_id=chunk_id,
                        embedding=embedding,
                        model=self.config.model,
                        dimensions=self.config.dimensions,
                        cached=False
                    )
                    cached_results[original_idx] = result
                    
                    # Store in cache
                    if self.cache and self.config.cache_enabled:
                        cache_key = self._get_cache_key(batch_texts[batch_ids.index((original_idx, chunk_id))])
                        await self.cache.set(
                            cache_key,
                            embedding,
                            ttl=self.config.cache_ttl_seconds
                        )
        
        # Reconstruct results in original order
        results = [cached_results[i] for i in range(len(texts))]
        
        processing_time = (time.time() - start_time) * 1000
        
        return BatchEmbeddingResult(
            results=results,
            total_tokens=total_tokens,
            processing_time_ms=processing_time,
            cache_hits=cache_hits,
            cache_misses=cache_misses
        )
    
    def _create_batches(
        self,
        texts: list[str],
        chunk_ids: list[tuple[int, UUID]]
    ) -> list[tuple[list[str], list[tuple[int, UUID]]]]:
        """Split texts into batches respecting size limits."""
        batches = []
        current_batch_texts = []
        current_batch_ids = []
        current_tokens = 0
        
        for text, chunk_id in zip(texts, chunk_ids):
            # Estimate tokens (rough: 4 chars per token)
            text_tokens = len(text) // 4
            
            if (len(current_batch_texts) >= self.config.max_batch_size or
                current_tokens + text_tokens > self.config.max_tokens_per_batch):
                if current_batch_texts:
                    batches.append((current_batch_texts, current_batch_ids))
                current_batch_texts = [text]
                current_batch_ids = [chunk_id]
                current_tokens = text_tokens
            else:
                current_batch_texts.append(text)
                current_batch_ids.append(chunk_id)
                current_tokens += text_tokens
        
        if current_batch_texts:
            batches.append((current_batch_texts, current_batch_ids))
        
        return batches
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    async def _embed_batch(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """
        Call LLM Gateway to generate embeddings for a batch.
        Uses OpenAI-compatible API format.
        """
        response = await self._client.post(
            self.config.embedding_endpoint,
            json={
                "input": texts,
                "model": self.config.model
            }
        )
        response.raise_for_status()
        
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        total_tokens = data.get("usage", {}).get("total_tokens", 0)
        
        return embeddings, total_tokens
    
    def _normalize(self, embedding: list[float]) -> list[float]:
        """L2 normalize the embedding vector."""
        import math
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            return [x / norm for x in embedding]
        return embedding
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text content and model."""
        content = f"{self.config.model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def embed_query(self, query: str) -> list[float]:
        """
        Embed a single query text.
        Uses "query: " prefix for BGE models.
        """
        result = await self.embed_texts(
            texts=[query],
            chunk_ids=[UUID(int=0)],  # Dummy ID for queries
            prefix="query: "
        )
        return result.results[0].embedding
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### Redis Embedding Cache

```python
import json
from typing import Optional
import redis.asyncio as redis

class EmbeddingCacheConfig(BaseModel):
    redis_url: str = "redis://localhost:6379"
    key_prefix: str = "emb:"
    default_ttl: int = 86400 * 7  # 7 days

class EmbeddingCache:
    """
    Redis-based cache for embeddings.
    
    Stores embeddings as compressed JSON to reduce memory usage.
    """
    
    def __init__(self, config: EmbeddingCacheConfig = EmbeddingCacheConfig()):
        self.config = config
        self._redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Establish Redis connection."""
        self._redis = redis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
    
    async def get(self, key: str) -> Optional[list[float]]:
        """
        Retrieve embedding from cache.
        
        Returns None if not found or expired.
        """
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.config.key_prefix}{key}"
        data = await self._redis.get(full_key)
        
        if data is None:
            return None
        
        return json.loads(data)
    
    async def set(
        self,
        key: str,
        embedding: list[float],
        ttl: Optional[int] = None
    ):
        """
        Store embedding in cache.
        
        Args:
            key: Cache key
            embedding: Embedding vector
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.config.key_prefix}{key}"
        data = json.dumps(embedding)
        
        await self._redis.setex(
            full_key,
            ttl or self.config.default_ttl,
            data
        )
    
    async def delete(self, key: str):
        """Delete embedding from cache."""
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.config.key_prefix}{key}"
        await self._redis.delete(full_key)
    
    async def clear_all(self):
        """Clear all embeddings (use with caution)."""
        if not self._redis:
            await self.connect()
        
        cursor = 0
        pattern = f"{self.config.key_prefix}*"
        
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        if not self._redis:
            await self.connect()
        
        info = await self._redis.info("memory")
        pattern = f"{self.config.key_prefix}*"
        
        # Count keys (expensive for large caches)
        cursor = 0
        count = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=1000)
            count += len(keys)
            if cursor == 0:
                break
        
        return {
            "cached_embeddings": count,
            "used_memory": info.get("used_memory_human"),
            "key_prefix": self.config.key_prefix
        }
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

### Parallel Embedding Processing

For high-throughput ingestion:

```python
import asyncio
from typing import AsyncIterator

class ParallelEmbedder:
    """
    Process embeddings in parallel with controlled concurrency.
    """
    
    def __init__(
        self,
        service: EmbeddingService,
        max_concurrent: int = 4
    ):
        self.service = service
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def embed_chunks_parallel(
        self,
        chunks: list[Chunk]
    ) -> AsyncIterator[EmbeddingResult]:
        """
        Embed chunks in parallel with concurrency control.
        """
        async def embed_batch(batch_chunks):
            async with self.semaphore:
                texts = [c.content for c in batch_chunks]
                ids = [c.chunk_id for c in batch_chunks]
                result = await self.service.embed_texts(texts, ids)
                return result.results
        
        # Split into batches
        batch_size = self.service.config.max_batch_size
        batches = [
            chunks[i:i + batch_size]
            for i in range(0, len(chunks), batch_size)
        ]
        
        # Process batches in parallel
        tasks = [embed_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks)
        
        for batch_results in results:
            for result in batch_results:
                yield result
```

## Acceptance Criteria

- [ ] `EmbeddingService` generates embeddings via LLM Gateway
- [ ] Batch processing respects `max_batch_size` (default 32)
- [ ] Batch processing respects `max_tokens_per_batch` (default 8192)
- [ ] `EmbeddingCache` stores/retrieves from Redis
- [ ] Cache key generation is deterministic (same text = same key)
- [ ] Cache TTL configurable (default 7 days)
- [ ] Retry logic with exponential backoff (3 retries, 1-10s wait)
- [ ] Embeddings normalized to unit length when configured
- [ ] BGE prefix support ("query: " for queries, "passage: " for documents)
- [ ] `ParallelEmbedder` for concurrent batch processing
- [ ] Metrics tracked: cache hits/misses, processing time, token usage

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def embedding_service():
    return EmbeddingService()

@pytest.fixture
async def embedding_cache():
    cache = EmbeddingCache()
    await cache.connect()
    yield cache
    await cache.clear_all()
    await cache.disconnect()

@pytest.mark.asyncio
async def test_embed_texts_returns_correct_dimensions(embedding_service):
    with patch.object(embedding_service, '_embed_batch') as mock:
        mock.return_value = ([[0.1] * 1024], 100)
        
        result = await embedding_service.embed_texts(
            texts=["test text"],
            chunk_ids=[uuid4()]
        )
        
        assert len(result.results) == 1
        assert len(result.results[0].embedding) == 1024

@pytest.mark.asyncio
async def test_cache_prevents_redundant_calls(embedding_service, embedding_cache):
    embedding_service.cache = embedding_cache
    
    with patch.object(embedding_service, '_embed_batch') as mock:
        mock.return_value = ([[0.1] * 1024], 100)
        
        chunk_id = uuid4()
        
        # First call should hit the API
        result1 = await embedding_service.embed_texts(
            texts=["test text"],
            chunk_ids=[chunk_id]
        )
        assert result1.cache_misses == 1
        assert result1.cache_hits == 0
        
        # Second call should hit the cache
        result2 = await embedding_service.embed_texts(
            texts=["test text"],
            chunk_ids=[chunk_id]
        )
        assert result2.cache_hits == 1
        assert result2.cache_misses == 0
        
        # API should only be called once
        assert mock.call_count == 1

@pytest.mark.asyncio
async def test_batching_splits_large_requests(embedding_service):
    embedding_service.config.max_batch_size = 2
    
    with patch.object(embedding_service, '_embed_batch') as mock:
        mock.return_value = ([[0.1] * 1024, [0.2] * 1024], 200)
        
        result = await embedding_service.embed_texts(
            texts=["text1", "text2", "text3", "text4"],
            chunk_ids=[uuid4() for _ in range(4)]
        )
        
        # Should split into 2 batches
        assert mock.call_count == 2

@pytest.mark.asyncio
async def test_normalization_produces_unit_vectors(embedding_service):
    import math
    
    embedding = [3.0, 4.0]  # 3-4-5 triangle
    normalized = embedding_service._normalize(embedding)
    
    # Should have length 1
    length = math.sqrt(sum(x * x for x in normalized))
    assert abs(length - 1.0) < 0.0001
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_service_with_real_llm_gateway():
    """Integration test with actual LLM Gateway."""
    config = EmbeddingServiceConfig(
        llm_gateway_url="http://localhost:8004"
    )
    
    async with EmbeddingService(config) as service:
        result = await service.embed_texts(
            texts=["The quick brown fox jumps over the lazy dog."],
            chunk_ids=[uuid4()]
        )
        
        assert len(result.results) == 1
        assert len(result.results[0].embedding) == 1024
        assert result.results[0].model == "BAAI/bge-large-en-v1.5"
```

## Dependencies

- `httpx>=0.25.0`
- `redis>=5.0.0`
- `tenacity>=8.2.0`
- `pydantic>=2.0.0`

## Performance Requirements

- Batch 32 chunks in < 500ms (excluding network latency)
- Cache lookup < 5ms
- Cache storage < 10ms
- Handle 1000+ chunks per minute with parallel processing

## Definition of Done

- [ ] Embedding service implemented with all features
- [ ] Redis cache operational with TTL support
- [ ] Retry logic tested with simulated failures
- [ ] Normalization produces valid unit vectors
- [ ] BGE prefixes correctly applied
- [ ] Parallel embedder handles high throughput
- [ ] >90% test coverage
- [ ] Integration test passes with LLM Gateway
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
