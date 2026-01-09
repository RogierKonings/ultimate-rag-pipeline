# US-3.1: Query Preprocessor

> **Story ID:** US-3.1  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Epic 1 (Infrastructure Setup)

## User Story

**As a** developer  
**I want** query preprocessing and rewriting  
**So that** queries are optimized for retrieval

## Context

The query preprocessor is the entry point of the retrieval pipeline. It normalizes, expands, and embeds user queries before search. Advanced techniques like HyDE (Hypothetical Document Embeddings) and multi-query generation improve retrieval quality for complex or ambiguous queries.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── query/
    ├── __init__.py
    ├── preprocessor.py      # Main preprocessor class
    ├── expander.py          # Query expansion with synonyms
    ├── hyde.py              # HyDE implementation
    ├── multi_query.py       # Multi-query generation
    └── models.py            # Pydantic models
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from uuid import UUID, uuid4

class QueryType(str, Enum):
    SIMPLE = "simple"           # Basic keyword query
    QUESTION = "question"       # Natural language question
    SEMANTIC = "semantic"       # Conceptual/semantic query
    HYBRID = "hybrid"           # Mixed intent

class ProcessedQuery(BaseModel):
    """Result of query preprocessing."""
    query_id: UUID = Field(default_factory=uuid4)
    original_query: str
    normalized_query: str
    expanded_queries: list[str] = []
    hyde_document: Optional[str] = None
    embedding: list[float]
    query_type: QueryType = QueryType.SIMPLE
    tokens: int = 0
    processing_time_ms: float = 0.0
    metadata: dict = {}

class QueryPreprocessorConfig(BaseModel):
    """Configuration for query preprocessing."""
    # Normalization
    lowercase: bool = True
    strip_whitespace: bool = True
    remove_special_chars: bool = False
    
    # Expansion
    enable_expansion: bool = True
    max_expansions: int = 3
    expansion_model: str = "synonym"  # "synonym" or "llm"
    
    # HyDE
    enable_hyde: bool = False  # Disabled by default (adds latency)
    hyde_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    hyde_max_tokens: int = 256
    
    # Multi-query
    enable_multi_query: bool = False
    max_generated_queries: int = 3
    
    # Embedding
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_prefix: str = "query: "  # BGE query prefix
    
    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"
    embedding_endpoint: str = "/v1/embeddings"
    completion_endpoint: str = "/v1/completions"
    
    # Cache
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour
```

### Query Preprocessor Implementation

```python
import re
import time
import hashlib
from typing import Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class QueryPreprocessor:
    """
    Preprocesses queries for optimal retrieval.
    
    Pipeline:
    1. Normalize (lowercase, whitespace, special chars)
    2. Classify query type
    3. Expand with synonyms (optional)
    4. Generate HyDE document (optional)
    5. Generate query embedding
    """
    
    def __init__(
        self,
        config: QueryPreprocessorConfig = QueryPreprocessorConfig(),
        cache: Optional["QueryCache"] = None
    ):
        self.config = config
        self.cache = cache
        self._http_client = httpx.AsyncClient(
            base_url=config.llm_gateway_url,
            timeout=30.0
        )
        self._expander: Optional["QueryExpander"] = None
        self._hyde: Optional["HyDEGenerator"] = None
    
    async def process(self, query: str) -> ProcessedQuery:
        """
        Process a raw query through the preprocessing pipeline.
        
        Args:
            query: Raw user query string
        
        Returns:
            ProcessedQuery with normalized query, expansions, and embedding
        """
        start_time = time.time()
        
        # Check cache first
        if self.cache and self.config.cache_enabled:
            cache_key = self._get_cache_key(query)
            cached = await self.cache.get(cache_key)
            if cached:
                cached.metadata["cached"] = True
                return cached
        
        # 1. Normalize
        normalized = self._normalize(query)
        
        # 2. Classify query type
        query_type = self._classify_query(normalized)
        
        # 3. Expand (optional)
        expanded_queries = []
        if self.config.enable_expansion:
            expanded_queries = await self._expand_query(normalized)
        
        # 4. HyDE (optional)
        hyde_document = None
        if self.config.enable_hyde and query_type == QueryType.QUESTION:
            hyde_document = await self._generate_hyde(normalized)
        
        # 5. Generate embedding
        # If HyDE is enabled, embed the hypothetical document instead
        text_to_embed = hyde_document if hyde_document else normalized
        embedding, tokens = await self._generate_embedding(text_to_embed)
        
        processing_time = (time.time() - start_time) * 1000
        
        result = ProcessedQuery(
            original_query=query,
            normalized_query=normalized,
            expanded_queries=expanded_queries,
            hyde_document=hyde_document,
            embedding=embedding,
            query_type=query_type,
            tokens=tokens,
            processing_time_ms=processing_time
        )
        
        # Cache result
        if self.cache and self.config.cache_enabled:
            await self.cache.set(cache_key, result, ttl=self.config.cache_ttl)
        
        return result
    
    def _normalize(self, query: str) -> str:
        """
        Normalize query text.
        
        - Lowercase (if configured)
        - Strip whitespace
        - Collapse multiple spaces
        - Remove special characters (if configured)
        """
        result = query
        
        if self.config.strip_whitespace:
            result = result.strip()
            result = re.sub(r'\s+', ' ', result)
        
        if self.config.lowercase:
            result = result.lower()
        
        if self.config.remove_special_chars:
            # Keep alphanumeric, spaces, and basic punctuation
            result = re.sub(r'[^a-zA-Z0-9\s\.\?\!\,\-]', '', result)
        
        return result
    
    def _classify_query(self, query: str) -> QueryType:
        """
        Classify query type based on patterns.
        
        - Questions start with who/what/when/where/why/how
        - Semantic queries contain conceptual terms
        - Simple queries are short keyword phrases
        """
        query_lower = query.lower()
        
        # Question patterns
        question_starters = [
            'who', 'what', 'when', 'where', 'why', 'how',
            'is', 'are', 'can', 'could', 'would', 'should',
            'do', 'does', 'did', 'will'
        ]
        
        if any(query_lower.startswith(q) for q in question_starters):
            return QueryType.QUESTION
        
        if query_lower.endswith('?'):
            return QueryType.QUESTION
        
        # Semantic indicators (looking for conceptual queries)
        semantic_indicators = [
            'explain', 'describe', 'compare', 'difference',
            'relationship', 'similar', 'like', 'meaning'
        ]
        
        if any(indicator in query_lower for indicator in semantic_indicators):
            return QueryType.SEMANTIC
        
        # Short queries are typically keyword searches
        word_count = len(query.split())
        if word_count <= 3:
            return QueryType.SIMPLE
        
        return QueryType.HYBRID
    
    async def _expand_query(self, query: str) -> list[str]:
        """
        Expand query with synonyms or related terms.
        
        Returns list of expanded query variations.
        """
        if not self._expander:
            self._expander = QueryExpander(self.config)
        
        return await self._expander.expand(query)
    
    async def _generate_hyde(self, query: str) -> str:
        """
        Generate Hypothetical Document Embedding (HyDE).
        
        Uses LLM to generate a hypothetical document that would
        answer the query, then embeds that instead of the query.
        """
        if not self._hyde:
            self._hyde = HyDEGenerator(
                llm_gateway_url=self.config.llm_gateway_url,
                model=self.config.hyde_model,
                max_tokens=self.config.hyde_max_tokens
            )
        
        return await self._hyde.generate(query)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    async def _generate_embedding(self, text: str) -> tuple[list[float], int]:
        """
        Generate embedding for text using LLM Gateway.
        
        Uses BGE query prefix for query embeddings.
        """
        prefixed_text = f"{self.config.embedding_prefix}{text}"
        
        response = await self._http_client.post(
            self.config.embedding_endpoint,
            json={
                "input": [prefixed_text],
                "model": self.config.embedding_model
            }
        )
        response.raise_for_status()
        
        data = response.json()
        embedding = data["data"][0]["embedding"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        
        return embedding, tokens
    
    def _get_cache_key(self, query: str) -> str:
        """Generate deterministic cache key."""
        # Include config that affects output
        config_hash = hashlib.md5(
            f"{self.config.enable_expansion}:{self.config.enable_hyde}".encode()
        ).hexdigest()[:8]
        
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        return f"query:{config_hash}:{query_hash}"
    
    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### Query Expander

```python
from typing import Optional

class SynonymDatabase:
    """
    Simple synonym lookup for query expansion.
    
    In production, consider using WordNet, a domain-specific
    thesaurus, or LLM-based expansion.
    """
    
    def __init__(self):
        # Domain-specific synonyms - extend for your use case
        self._synonyms = {
            "error": ["bug", "issue", "problem", "fault", "exception"],
            "create": ["make", "build", "generate", "construct"],
            "delete": ["remove", "drop", "destroy", "erase"],
            "update": ["modify", "change", "edit", "alter"],
            "find": ["search", "locate", "discover", "lookup"],
            "fast": ["quick", "rapid", "speedy", "high-performance"],
            "slow": ["sluggish", "delayed", "latent"],
            "user": ["customer", "client", "member", "account"],
            "authentication": ["auth", "login", "sign-in", "credential"],
            "database": ["db", "datastore", "storage"],
            "api": ["endpoint", "interface", "service"],
            # Add more domain-specific synonyms
        }
    
    def get_synonyms(self, word: str) -> list[str]:
        """Get synonyms for a word."""
        return self._synonyms.get(word.lower(), [])


class QueryExpander:
    """
    Expands queries with synonyms and related terms.
    """
    
    def __init__(self, config: QueryPreprocessorConfig):
        self.config = config
        self._synonym_db = SynonymDatabase()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def expand(self, query: str) -> list[str]:
        """
        Generate expanded versions of the query.
        
        Returns up to max_expansions alternative queries.
        """
        if self.config.expansion_model == "synonym":
            return self._expand_with_synonyms(query)
        elif self.config.expansion_model == "llm":
            return await self._expand_with_llm(query)
        
        return []
    
    def _expand_with_synonyms(self, query: str) -> list[str]:
        """
        Expand query using synonym substitution.
        
        Strategy:
        1. Tokenize query
        2. Find words with synonyms
        3. Generate variations by substituting one word at a time
        """
        words = query.lower().split()
        expansions = []
        
        for i, word in enumerate(words):
            synonyms = self._synonym_db.get_synonyms(word)
            
            for synonym in synonyms[:self.config.max_expansions]:
                # Create variation with this synonym
                new_words = words.copy()
                new_words[i] = synonym
                expansion = " ".join(new_words)
                
                if expansion != query.lower() and expansion not in expansions:
                    expansions.append(expansion)
                
                if len(expansions) >= self.config.max_expansions:
                    return expansions
        
        return expansions
    
    async def _expand_with_llm(self, query: str) -> list[str]:
        """
        Expand query using LLM to generate semantically similar queries.
        """
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                base_url=self.config.llm_gateway_url,
                timeout=30.0
            )
        
        prompt = f"""Generate {self.config.max_expansions} alternative search queries 
that are semantically similar to the following query. Each alternative should 
capture the same intent but use different words or phrasing.

Original query: {query}

Return only the alternative queries, one per line, without numbering or explanations."""
        
        response = await self._http_client.post(
            self.config.completion_endpoint,
            json={
                "model": self.config.hyde_model,
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.7
            }
        )
        response.raise_for_status()
        
        data = response.json()
        text = data["choices"][0]["text"].strip()
        
        # Parse response into list of queries
        expansions = [
            line.strip() 
            for line in text.split("\n") 
            if line.strip() and line.strip() != query
        ]
        
        return expansions[:self.config.max_expansions]
```

### HyDE Generator

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class HyDEGenerator:
    """
    Generates Hypothetical Document Embeddings.
    
    HyDE improves retrieval by:
    1. Using LLM to generate a hypothetical document that answers the query
    2. Embedding that document instead of the query
    3. Searching for real documents similar to the hypothetical one
    
    This helps bridge the vocabulary gap between queries and documents.
    
    Reference: https://arxiv.org/abs/2212.10496
    """
    
    def __init__(
        self,
        llm_gateway_url: str = "http://localhost:8004",
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_tokens: int = 256
    ):
        self.llm_gateway_url = llm_gateway_url
        self.model = model
        self.max_tokens = max_tokens
        self._http_client = httpx.AsyncClient(
            base_url=llm_gateway_url,
            timeout=30.0
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    async def generate(self, query: str) -> str:
        """
        Generate a hypothetical document that would answer the query.
        
        Args:
            query: User's search query
        
        Returns:
            Hypothetical document text
        """
        prompt = self._build_prompt(query)
        
        response = await self._http_client.post(
            "/v1/completions",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": self.max_tokens,
                "temperature": 0.7,
                "stop": ["\n\n", "---", "Query:"]
            }
        )
        response.raise_for_status()
        
        data = response.json()
        hypothetical_doc = data["choices"][0]["text"].strip()
        
        return hypothetical_doc
    
    def _build_prompt(self, query: str) -> str:
        """
        Build prompt for hypothetical document generation.
        
        The prompt instructs the LLM to write a document passage
        that would be a relevant answer to the query.
        """
        return f"""You are a helpful assistant that writes document passages.
Given a search query, write a short, factual document passage that would 
directly answer or be highly relevant to the query. Write as if you are 
writing part of a technical document or knowledge base article.

Query: {query}

Document passage:"""
    
    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()


class MultiQueryGenerator:
    """
    Generates multiple query variations for improved recall.
    
    Useful for complex or ambiguous queries where different
    phrasings might match different relevant documents.
    """
    
    def __init__(
        self,
        llm_gateway_url: str = "http://localhost:8004",
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_queries: int = 3
    ):
        self.llm_gateway_url = llm_gateway_url
        self.model = model
        self.max_queries = max_queries
        self._http_client = httpx.AsyncClient(
            base_url=llm_gateway_url,
            timeout=30.0
        )
    
    async def generate(self, query: str) -> list[str]:
        """
        Generate multiple query variations.
        
        Args:
            query: Original user query
        
        Returns:
            List of query variations including the original
        """
        prompt = f"""You are a helpful assistant that generates search queries.
Given an original query, generate {self.max_queries} alternative versions 
that express the same information need but using different words or structure.

Original query: {query}

Generate {self.max_queries} alternative queries, one per line:"""
        
        response = await self._http_client.post(
            "/v1/completions",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.7
            }
        )
        response.raise_for_status()
        
        data = response.json()
        text = data["choices"][0]["text"].strip()
        
        # Parse and include original query
        variations = [query]  # Always include original
        for line in text.split("\n"):
            cleaned = line.strip().lstrip("0123456789.-) ")
            if cleaned and cleaned != query:
                variations.append(cleaned)
        
        return variations[:self.max_queries + 1]  # +1 for original
    
    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()
```

### Query Cache

```python
import json
from typing import Optional
import redis.asyncio as redis

class QueryCache:
    """
    Redis cache for processed queries.
    
    Caches the full ProcessedQuery including embeddings to avoid
    redundant embedding generation for repeated queries.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "query_cache:"
    ):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Establish Redis connection."""
        self._redis = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
    
    async def get(self, key: str) -> Optional[ProcessedQuery]:
        """Retrieve processed query from cache."""
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.key_prefix}{key}"
        data = await self._redis.get(full_key)
        
        if data is None:
            return None
        
        return ProcessedQuery.model_validate_json(data)
    
    async def set(
        self,
        key: str,
        query: ProcessedQuery,
        ttl: int = 3600
    ):
        """Store processed query in cache."""
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.key_prefix}{key}"
        data = query.model_dump_json()
        
        await self._redis.setex(full_key, ttl, data)
    
    async def delete(self, key: str):
        """Delete query from cache."""
        if not self._redis:
            await self.connect()
        
        full_key = f"{self.key_prefix}{key}"
        await self._redis.delete(full_key)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

## Acceptance Criteria

- [ ] Query normalization handles lowercase, whitespace, special characters
- [ ] Query classification identifies SIMPLE, QUESTION, SEMANTIC, HYBRID types
- [ ] Synonym-based query expansion generates up to 3 variations
- [ ] LLM-based query expansion works when configured
- [ ] HyDE generates plausible hypothetical documents
- [ ] Multi-query generation creates semantically similar alternatives
- [ ] Query embeddings use BGE "query: " prefix
- [ ] Redis cache prevents redundant embedding calls
- [ ] Retry logic handles transient LLM Gateway failures
- [ ] Processing time tracked in response

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def preprocessor():
    config = QueryPreprocessorConfig(
        enable_expansion=True,
        enable_hyde=False,
        cache_enabled=False
    )
    return QueryPreprocessor(config)

@pytest.mark.asyncio
async def test_normalization(preprocessor):
    """Test query normalization."""
    result = preprocessor._normalize("  Hello   WORLD  ")
    assert result == "hello world"

@pytest.mark.asyncio
async def test_query_classification_question(preprocessor):
    """Test question detection."""
    assert preprocessor._classify_query("what is machine learning") == QueryType.QUESTION
    assert preprocessor._classify_query("how does it work?") == QueryType.QUESTION

@pytest.mark.asyncio
async def test_query_classification_simple(preprocessor):
    """Test simple query detection."""
    assert preprocessor._classify_query("python tutorial") == QueryType.SIMPLE

@pytest.mark.asyncio
async def test_synonym_expansion():
    """Test synonym-based expansion."""
    config = QueryPreprocessorConfig(max_expansions=3)
    expander = QueryExpander(config)
    
    expansions = expander._expand_with_synonyms("fix the error")
    
    assert len(expansions) <= 3
    assert any("bug" in e or "issue" in e or "problem" in e for e in expansions)

@pytest.mark.asyncio
async def test_process_returns_embedding(preprocessor):
    """Test that process returns embedding."""
    with patch.object(preprocessor, '_generate_embedding') as mock:
        mock.return_value = ([0.1] * 1024, 10)
        
        result = await preprocessor.process("test query")
        
        assert len(result.embedding) == 1024
        assert result.normalized_query == "test query"
        assert result.tokens == 10

@pytest.mark.asyncio
async def test_cache_prevents_duplicate_embedding():
    """Test that cache prevents duplicate embedding calls."""
    cache = QueryCache()
    await cache.connect()
    
    config = QueryPreprocessorConfig(cache_enabled=True)
    preprocessor = QueryPreprocessor(config, cache=cache)
    
    with patch.object(preprocessor, '_generate_embedding') as mock:
        mock.return_value = ([0.1] * 1024, 10)
        
        # First call
        result1 = await preprocessor.process("test query")
        assert mock.call_count == 1
        
        # Second call should hit cache
        result2 = await preprocessor.process("test query")
        assert mock.call_count == 1  # Still 1, cache hit
        assert result2.metadata.get("cached") is True
    
    await cache.disconnect()

@pytest.mark.asyncio
async def test_hyde_generation():
    """Test HyDE document generation."""
    hyde = HyDEGenerator()
    
    with patch.object(hyde._http_client, 'post') as mock:
        mock.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "choices": [{"text": "Machine learning is a subset of AI..."}]
            }
        )
        mock.return_value.raise_for_status = lambda: None
        
        result = await hyde.generate("what is machine learning")
        
        assert "machine learning" in result.lower() or "ai" in result.lower()
    
    await hyde.close()
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_preprocessor_with_real_llm_gateway():
    """Integration test with actual LLM Gateway."""
    config = QueryPreprocessorConfig(
        llm_gateway_url="http://localhost:8004",
        enable_expansion=True,
        enable_hyde=True
    )
    
    async with QueryPreprocessor(config) as preprocessor:
        result = await preprocessor.process("What is retrieval augmented generation?")
        
        assert len(result.embedding) == 1024
        assert result.query_type == QueryType.QUESTION
        assert len(result.expanded_queries) > 0
        assert result.hyde_document is not None
        assert "retrieval" in result.hyde_document.lower() or "rag" in result.hyde_document.lower()
```

## Dependencies

- `httpx>=0.25.0`
- `redis>=5.0.0`
- `tenacity>=8.2.0`
- `pydantic>=2.0.0`

## Performance Requirements

- Query normalization: < 1ms
- Query classification: < 1ms
- Synonym expansion: < 5ms
- HyDE generation: < 500ms (LLM call)
- Embedding generation: < 100ms
- Cache lookup: < 5ms
- Total processing (without HyDE): < 150ms
- Total processing (with HyDE): < 700ms

## Definition of Done

- [ ] QueryPreprocessor implemented with all pipeline stages
- [ ] Query normalization handles edge cases
- [ ] Query classification works for all types
- [ ] Synonym expansion provides useful alternatives
- [ ] HyDE generates coherent hypothetical documents
- [ ] Multi-query generation creates diverse variations
- [ ] Redis cache operational
- [ ] Retry logic tested with simulated failures
- [ ] >90% test coverage
- [ ] Integration test passes with LLM Gateway
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
