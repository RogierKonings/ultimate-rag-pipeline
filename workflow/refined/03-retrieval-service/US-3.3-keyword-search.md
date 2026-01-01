# US-3.3: Keyword Search

> **Story ID:** US-3.3  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-3.1 (Query Preprocessor), US-3.6 (ACL Filter)

## User Story

**As a** developer  
**I want** BM25 keyword search  
**So that** exact term matches are found

## Context

Keyword search complements semantic search by finding documents with exact term matches. BM25 (Best Matching 25) is the standard algorithm for lexical search, scoring documents based on term frequency and inverse document frequency. Per the architecture, OpenSearch provides the keyword search backend with support for custom analyzers and field boosting.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── search/
    ├── __init__.py
    ├── base.py              # Search interface (shared with semantic)
    ├── keyword.py           # OpenSearch BM25 search
    └── models.py            # Shared models
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID

class KeywordSearchRequest(BaseModel):
    """Request for keyword search."""
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: Optional[dict[str, Any]] = None
    fields: list[str] = ["content", "title"]
    field_boosts: dict[str, float] = {"title": 2.0, "content": 1.0}
    highlight: bool = True
    min_score: float = 0.0

class KeywordSearchResponse(BaseModel):
    """Response from keyword search."""
    results: list["SearchResultItem"]  # Reuse from semantic
    total_found: int
    search_time_ms: float
    query_id: Optional[UUID] = None

class OpenSearchConfig(BaseModel):
    """OpenSearch connection configuration."""
    url: str = "http://localhost:9200"
    username: Optional[str] = None
    password: Optional[str] = None
    index_name: str = "documents"
    timeout: float = 30.0
    
    # BM25 parameters
    use_ssl: bool = False
    verify_certs: bool = True
    
    # Search configuration
    default_operator: str = "OR"  # "AND" or "OR"
    fuzziness: str = "AUTO"  # Fuzzy matching
    analyzer: str = "standard"
    
    # Performance
    track_total_hits: bool = True
    request_timeout: int = 30
```

### Keyword Search Implementation

```python
import time
from typing import Optional, Any
from uuid import UUID
from opensearchpy import AsyncOpenSearch

class KeywordSearcher(BaseSearcher):
    """
    Keyword search using OpenSearch BM25.
    
    Supports multi-field search with boosting, custom analyzers,
    fuzzy matching, and highlighting.
    """
    
    def __init__(self, config: OpenSearchConfig = OpenSearchConfig()):
        self.config = config
        self._client: Optional[AsyncOpenSearch] = None
    
    async def connect(self):
        """Establish connection to OpenSearch."""
        auth = None
        if self.config.username and self.config.password:
            auth = (self.config.username, self.config.password)
        
        self._client = AsyncOpenSearch(
            hosts=[self.config.url],
            http_auth=auth,
            use_ssl=self.config.use_ssl,
            verify_certs=self.config.verify_certs,
            timeout=self.config.timeout
        )
    
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
        fields: Optional[list[str]] = None,
        field_boosts: Optional[dict[str, float]] = None,
        highlight: bool = True,
        min_score: float = 0.0
    ) -> KeywordSearchResponse:
        """
        Execute BM25 keyword search.
        
        Args:
            query: Search query string
            top_k: Number of results to return
            filters: OpenSearch filter dict (built by ACLFilter)
            fields: Fields to search (default: content, title)
            field_boosts: Field boost weights
            highlight: Enable result highlighting
            min_score: Minimum BM25 score threshold
        
        Returns:
            KeywordSearchResponse with ranked results
        """
        if not self._client:
            await self.connect()
        
        start_time = time.time()
        
        # Build query
        search_fields = fields or ["content", "title"]
        boosts = field_boosts or {"title": 2.0, "content": 1.0}
        
        # Apply boosts to field list
        boosted_fields = [
            f"{field}^{boosts.get(field, 1.0)}"
            for field in search_fields
        ]
        
        # Build OpenSearch query
        es_query = self._build_query(query, boosted_fields, filters)
        
        # Add highlighting
        highlight_config = None
        if highlight:
            highlight_config = {
                "fields": {field: {} for field in search_fields},
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fragment_size": 150,
                "number_of_fragments": 3
            }
        
        # Execute search
        response = await self._client.search(
            index=self.config.index_name,
            body={
                "query": es_query,
                "size": top_k,
                "min_score": min_score if min_score > 0 else None,
                "highlight": highlight_config,
                "track_total_hits": self.config.track_total_hits,
                "_source": True
            }
        )
        
        search_time = (time.time() - start_time) * 1000
        
        # Convert to response model
        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total
        
        items = [self._convert_hit(hit) for hit in hits]
        
        # Normalize scores
        if items:
            items = self._normalize_scores(items)
        
        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time
        )
    
    def _build_query(
        self,
        query: str,
        boosted_fields: list[str],
        filters: Optional[dict] = None
    ) -> dict:
        """
        Build OpenSearch query with bool structure.
        
        Uses multi_match for text search with BM25 scoring.
        """
        # Base text query
        text_query = {
            "multi_match": {
                "query": query,
                "fields": boosted_fields,
                "type": "best_fields",
                "operator": self.config.default_operator.lower(),
                "fuzziness": self.config.fuzziness,
                "prefix_length": 2,  # Require first 2 chars to match exactly
                "analyzer": self.config.analyzer
            }
        }
        
        # If no filters, return simple query
        if not filters:
            return text_query
        
        # Build bool query with filters
        filter_clauses = self._build_filter_clauses(filters)
        
        return {
            "bool": {
                "must": [text_query],
                "filter": filter_clauses
            }
        }
    
    def _build_filter_clauses(self, filters: dict) -> list[dict]:
        """
        Build OpenSearch filter clauses from filter dict.
        
        Supports nested bool structure matching ACL filter format.
        """
        clauses = []
        
        for key, value in filters.items():
            if key == "must":
                for condition in value:
                    clauses.append(self._build_filter_condition(condition))
            elif key == "should":
                # Wrap should conditions in a bool
                should_clauses = [
                    self._build_filter_condition(c) for c in value
                ]
                clauses.append({
                    "bool": {
                        "should": should_clauses,
                        "minimum_should_match": 1
                    }
                })
            elif key == "must_not":
                must_not_clauses = [
                    self._build_filter_condition(c) for c in value
                ]
                clauses.append({
                    "bool": {
                        "must_not": must_not_clauses
                    }
                })
            else:
                # Simple key-value filter
                clauses.append({"term": {key: value}})
        
        return clauses
    
    def _build_filter_condition(self, condition: dict) -> dict:
        """Build a single filter condition."""
        key = condition.get("key")
        
        if "match" in condition:
            match_spec = condition["match"]
            if "value" in match_spec:
                return {"term": {key: match_spec["value"]}}
            elif "any" in match_spec:
                return {"terms": {key: match_spec["any"]}}
        elif "range" in condition:
            range_spec = condition["range"]
            return {"range": {key: range_spec}}
        
        raise ValueError(f"Unsupported condition: {condition}")
    
    def _convert_hit(self, hit: dict) -> "SearchResultItem":
        """Convert OpenSearch hit to SearchResultItem."""
        source = hit["_source"]
        highlights = hit.get("highlight", {})
        
        # Use highlighted content if available
        content = source.get("content", "")
        if "content" in highlights:
            content = " ... ".join(highlights["content"])
        
        return SearchResultItem(
            chunk_id=UUID(hit["_id"]) if self._is_uuid(hit["_id"]) else UUID(int=hash(hit["_id"]) & ((1 << 128) - 1)),
            document_id=UUID(source.get("document_id", "00000000-0000-0000-0000-000000000000")),
            content=content,
            score=hit["_score"],
            metadata={
                k: v for k, v in source.items()
                if k not in ["content", "document_id", "chunk_id", "embedding"]
            },
            title=source.get("title"),
            source=source.get("source"),
            chunk_index=source.get("chunk_index", 0),
            total_chunks=source.get("total_chunks", 1),
            created_at=source.get("created_at"),
            updated_at=source.get("updated_at")
        )
    
    def _is_uuid(self, value: str) -> bool:
        """Check if string is a valid UUID."""
        try:
            UUID(value)
            return True
        except (ValueError, TypeError):
            return False
    
    def _normalize_scores(
        self,
        results: list["SearchResultItem"]
    ) -> list["SearchResultItem"]:
        """
        Normalize BM25 scores to 0-1 range.
        
        BM25 scores are unbounded, so we use min-max normalization.
        """
        if not results:
            return results
        
        scores = [r.score for r in results]
        min_score = min(scores)
        max_score = max(scores)
        
        if max_score == min_score:
            for r in results:
                r.score = 1.0
            return results
        
        for r in results:
            r.score = (r.score - min_score) / (max_score - min_score)
        
        return results
    
    async def search_phrase(
        self,
        phrase: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
        slop: int = 0
    ) -> KeywordSearchResponse:
        """
        Execute phrase search for exact or near-exact matches.
        
        Args:
            phrase: Exact phrase to search for
            top_k: Number of results
            filters: ACL and metadata filters
            slop: Number of positions allowed between terms
        
        Returns:
            KeywordSearchResponse with phrase matches
        """
        if not self._client:
            await self.connect()
        
        start_time = time.time()
        
        query = {
            "bool": {
                "must": [
                    {
                        "match_phrase": {
                            "content": {
                                "query": phrase,
                                "slop": slop
                            }
                        }
                    }
                ]
            }
        }
        
        if filters:
            query["bool"]["filter"] = self._build_filter_clauses(filters)
        
        response = await self._client.search(
            index=self.config.index_name,
            body={
                "query": query,
                "size": top_k,
                "_source": True
            }
        )
        
        search_time = (time.time() - start_time) * 1000
        
        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total
        
        items = [self._convert_hit(hit) for hit in hits]
        items = self._normalize_scores(items)
        
        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time
        )
    
    async def search_with_expansion(
        self,
        queries: list[str],
        top_k: int = 10,
        filters: Optional[dict] = None
    ) -> KeywordSearchResponse:
        """
        Search with multiple query variations (from query expansion).
        
        Combines results using a should clause (OR).
        """
        if not self._client:
            await self.connect()
        
        start_time = time.time()
        
        # Build multi-query with should
        should_clauses = []
        for q in queries:
            should_clauses.append({
                "multi_match": {
                    "query": q,
                    "fields": ["content", "title^2"],
                    "type": "best_fields",
                    "fuzziness": self.config.fuzziness
                }
            })
        
        query = {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1
            }
        }
        
        if filters:
            query["bool"]["filter"] = self._build_filter_clauses(filters)
        
        response = await self._client.search(
            index=self.config.index_name,
            body={
                "query": query,
                "size": top_k,
                "_source": True
            }
        )
        
        search_time = (time.time() - start_time) * 1000
        
        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total
        
        items = [self._convert_hit(hit) for hit in hits]
        items = self._normalize_scores(items)
        
        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time
        )
    
    async def get_index_info(self) -> dict:
        """Get index statistics."""
        if not self._client:
            await self.connect()
        
        stats = await self._client.indices.stats(index=self.config.index_name)
        index_stats = stats["indices"][self.config.index_name]["total"]
        
        return {
            "name": self.config.index_name,
            "docs_count": index_stats["docs"]["count"],
            "docs_deleted": index_stats["docs"]["deleted"],
            "store_size": index_stats["store"]["size_in_bytes"],
            "store_size_human": self._format_bytes(index_stats["store"]["size_in_bytes"])
        }
    
    def _format_bytes(self, size: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
    
    async def health_check(self) -> bool:
        """Check if OpenSearch is healthy."""
        try:
            if not self._client:
                await self.connect()
            
            health = await self._client.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False
    
    async def close(self):
        """Close OpenSearch client."""
        if self._client:
            await self._client.close()
            self._client = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

### Custom Analyzer Configuration

```python
class AnalyzerConfig(BaseModel):
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
                                "asciifolding"
                            ]
                        },
                        "autocomplete": {
                            "type": "custom",
                            "tokenizer": "autocomplete_tokenizer",
                            "filter": ["lowercase"]
                        }
                    },
                    "tokenizer": {
                        "autocomplete_tokenizer": {
                            "type": "edge_ngram",
                            "min_gram": 2,
                            "max_gram": 20,
                            "token_chars": ["letter", "digit"]
                        }
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
                                "ai, artificial intelligence"
                            ]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "content": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "technical": {
                                "type": "text",
                                "analyzer": "technical"
                            }
                        }
                    },
                    "title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "keyword": {
                                "type": "keyword"
                            }
                        }
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
                    "total_chunks": {"type": "integer"}
                }
            }
        }
```

## Acceptance Criteria

- [ ] KeywordSearcher connects to OpenSearch successfully
- [ ] BM25 search returns relevant keyword matches
- [ ] Multi-field search with configurable boosting (title^2, content^1)
- [ ] Fuzzy matching handles typos and variations
- [ ] Phrase search finds exact matches with configurable slop
- [ ] ACL filters correctly applied to queries
- [ ] Metadata filters work (by tenant, source, date range)
- [ ] Highlighting marks matched terms in results
- [ ] Scores normalized to 0-1 range
- [ ] Query expansion search combines multiple queries
- [ ] Index info retrievable for monitoring
- [ ] Health check validates OpenSearch connectivity
- [ ] Search latency < 50ms for 10 results

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def searcher():
    return KeywordSearcher()

@pytest.fixture
def mock_opensearch_response():
    """Mock OpenSearch search response."""
    return {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {
                    "_id": str(uuid4()),
                    "_score": 15.5,
                    "_source": {
                        "content": "Machine learning is transforming AI",
                        "document_id": str(uuid4()),
                        "title": "ML Guide",
                        "source": "docs/ml.md",
                        "tenant_id": "tenant-123"
                    },
                    "highlight": {
                        "content": ["<mark>Machine learning</mark> is transforming AI"]
                    }
                },
                {
                    "_id": str(uuid4()),
                    "_score": 12.3,
                    "_source": {
                        "content": "Deep learning is a subset of ML",
                        "document_id": str(uuid4()),
                        "title": "Deep Learning",
                        "source": "docs/dl.md",
                        "tenant_id": "tenant-123"
                    }
                }
            ]
        }
    }

@pytest.mark.asyncio
async def test_search_returns_results(searcher, mock_opensearch_response):
    """Test that search returns properly formatted results."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value=mock_opensearch_response)
        
        response = await searcher.search(
            query="machine learning",
            top_k=10
        )
        
        assert len(response.results) == 2
        assert response.total_found == 2
        assert response.search_time_ms > 0

@pytest.mark.asyncio
async def test_highlighting_in_results(searcher, mock_opensearch_response):
    """Test that highlighted content is used when available."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value=mock_opensearch_response)
        
        response = await searcher.search(
            query="machine learning",
            top_k=10,
            highlight=True
        )
        
        # First result should have highlighted content
        assert "<mark>" in response.results[0].content

@pytest.mark.asyncio
async def test_field_boosting(searcher):
    """Test that field boosts are applied correctly."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value={
            "hits": {"total": {"value": 0}, "hits": []}
        })
        
        await searcher.search(
            query="test",
            fields=["content", "title"],
            field_boosts={"title": 3.0, "content": 1.0}
        )
        
        call_body = mock_client.search.call_args.kwargs["body"]
        query = call_body["query"]["multi_match"]
        
        assert "title^3.0" in query["fields"]
        assert "content^1.0" in query["fields"]

@pytest.mark.asyncio
async def test_filter_building(searcher):
    """Test OpenSearch filter construction."""
    filter_dict = {
        "must": [
            {"key": "tenant_id", "match": {"value": "tenant-123"}}
        ],
        "should": [
            {"key": "visibility", "match": {"value": "public"}},
            {"key": "allowed_groups", "match": {"any": ["group-1", "group-2"]}}
        ]
    }
    
    clauses = searcher._build_filter_clauses(filter_dict)
    
    assert len(clauses) == 2  # One for must, one bool for should
    assert clauses[0] == {"term": {"tenant_id": "tenant-123"}}

@pytest.mark.asyncio
async def test_score_normalization(searcher):
    """Test that BM25 scores are normalized to 0-1 range."""
    results = [
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="A",
            score=20.0
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="B",
            score=10.0
        ),
        SearchResultItem(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="C",
            score=5.0
        )
    ]
    
    normalized = searcher._normalize_scores(results)
    
    assert normalized[0].score == 1.0  # Max
    assert normalized[2].score == 0.0  # Min
    assert 0.0 < normalized[1].score < 1.0

@pytest.mark.asyncio
async def test_phrase_search(searcher):
    """Test phrase search with slop."""
    with patch.object(searcher, '_client') as mock_client:
        mock_client.search = AsyncMock(return_value={
            "hits": {"total": {"value": 0}, "hits": []}
        })
        
        await searcher.search_phrase(
            phrase="machine learning models",
            slop=2
        )
        
        call_body = mock_client.search.call_args.kwargs["body"]
        phrase_query = call_body["query"]["bool"]["must"][0]["match_phrase"]
        
        assert phrase_query["content"]["query"] == "machine learning models"
        assert phrase_query["content"]["slop"] == 2
```

## Integration Test

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_keyword_search_with_real_opensearch():
    """Integration test with actual OpenSearch instance."""
    config = OpenSearchConfig(
        url="http://localhost:9200",
        index_name="test_documents"
    )
    
    async with KeywordSearcher(config) as searcher:
        # Verify connection
        assert await searcher.health_check()
        
        # Get index info
        info = await searcher.get_index_info()
        assert info["name"] == "test_documents"
        
        # Execute search
        response = await searcher.search(
            query="machine learning",
            top_k=5
        )
        
        assert response.search_time_ms > 0
        # Results depend on what's in the index
```

## Dependencies

- `opensearch-py>=2.4.0`
- `pydantic>=2.0.0`

## Performance Requirements

- Search latency: < 50ms for 10 results
- Support for millions of documents
- BM25 parameters tunable
- Highlight generation < 10ms overhead

## Definition of Done

- [ ] KeywordSearcher implemented with all methods
- [ ] OpenSearch connection management (connect, close, context manager)
- [ ] Multi-field search with boosting
- [ ] Fuzzy matching for typo tolerance
- [ ] Phrase search with slop
- [ ] Filter building for ACL and metadata
- [ ] Score normalization to 0-1 range
- [ ] Highlighting support
- [ ] Query expansion search
- [ ] Health check and index info
- [ ] Custom analyzer configuration documented
- [ ] >90% test coverage
- [ ] Integration test passes with OpenSearch
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
