# US-3.7: Retrieval API

> **Story ID:** US-3.7  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-3.1-3.6 (All retrieval components)

## User Story

**As an** API consumer  
**I want** REST endpoints for retrieval  
**So that** I can search the document corpus

## Context

The Retrieval API is the external interface to the retrieval service. It exposes REST endpoints for hybrid search with ACL filtering, reranking, and comprehensive response metadata. Per the architecture, the service runs on port 8002 with FastAPI and Pydantic v2 for request/response validation.

## Technical Requirements

### Directory Structure

```
retrieval-service/
├── api/
│   ├── main.py              # FastAPI application
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── retrieve.py      # Main retrieval endpoints
│   │   └── health.py        # Health check endpoints
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── retrieve.py      # Request/response models
│   │   └── common.py        # Shared models
│   └── dependencies.py      # Dependency injection
├── config.py                # Configuration
└── run.py                   # Entry point
```

### API Request/Response Schemas

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

# ============ Request Schemas ============

class SearchMode(str, Enum):
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
    filters: Optional[dict[str, Any]] = None
    
    # Score threshold
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Response options
    include_metadata: bool = True
    include_highlights: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "How does machine learning work?",
                "mode": "hybrid",
                "top_k": 10,
                "rerank": True,
                "filters": {
                    "source_type": "documentation"
                }
            }
        }

class MultiQueryRequest(BaseModel):
    """
    Request for multi-query retrieval.
    
    Useful for complex queries that benefit from
    multiple query variations.
    """
    queries: list[str] = Field(..., min_items=1, max_items=5)
    aggregation: Literal["max", "avg", "rrf"] = "rrf"
    top_k: int = Field(default=10, ge=1, le=100)
    filters: Optional[dict[str, Any]] = None
    rerank: bool = True

# ============ Response Schemas ============

class RetrievedDocument(BaseModel):
    """Single retrieved document/chunk."""
    chunk_id: UUID
    document_id: UUID
    content: str
    score: float = Field(ge=0.0, le=1.0)
    
    # Document metadata
    title: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    
    # Chunk position
    chunk_index: int = 0
    total_chunks: int = 1
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Score breakdown
    semantic_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rerank_score: Optional[float] = None
    
    # Additional metadata
    metadata: dict[str, Any] = {}
    
    # Highlights (if enabled)
    highlights: Optional[list[str]] = None

class SearchMetrics(BaseModel):
    """Metrics for the search operation."""
    query_preprocessing_ms: float
    semantic_search_ms: Optional[float] = None
    keyword_search_ms: Optional[float] = None
    fusion_ms: Optional[float] = None
    rerank_ms: Optional[float] = None
    total_ms: float
    
    semantic_results_count: int = 0
    keyword_results_count: int = 0
    fused_results_count: int = 0
    final_results_count: int = 0

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
    
    class Config:
        json_schema_extra = {
            "example": {
                "results": [
                    {
                        "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
                        "document_id": "550e8400-e29b-41d4-a716-446655440001",
                        "content": "Machine learning is a subset of AI...",
                        "score": 0.92,
                        "title": "ML Guide",
                        "source": "docs/ml-intro.md"
                    }
                ],
                "total_results": 1,
                "query": "How does machine learning work?",
                "mode": "hybrid"
            }
        }

class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    components: dict[str, bool]
    timestamp: datetime
```

### FastAPI Application

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time

from config import RetrievalConfig
from api.routes import retrieve, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    config = RetrievalConfig()
    
    # Initialize components
    from query.preprocessor import QueryPreprocessor, QueryPreprocessorConfig
    from search.semantic import SemanticSearcher, QdrantConfig
    from search.keyword import KeywordSearcher, OpenSearchConfig
    from search.hybrid import HybridSearcher, HybridSearchConfig
    from reranking.reranker import RerankerService, RerankerConfig
    from acl.filter import ACLFilter, ACLFilterConfig
    from acl.context import UserContextExtractor
    
    # Create instances
    preprocessor = QueryPreprocessor(QueryPreprocessorConfig(
        llm_gateway_url=config.llm_gateway_url
    ))
    
    semantic = SemanticSearcher(QdrantConfig(
        url=config.qdrant_url,
        collection_name=config.qdrant_collection
    ))
    await semantic.connect()
    
    keyword = KeywordSearcher(OpenSearchConfig(
        url=config.opensearch_url,
        index_name=config.opensearch_index
    ))
    await keyword.connect()
    
    hybrid = HybridSearcher(
        semantic,
        keyword,
        HybridSearchConfig(
            semantic_weight=config.semantic_weight,
            keyword_weight=config.keyword_weight
        )
    )
    
    reranker = RerankerService(RerankerConfig(
        llm_gateway_url=config.llm_gateway_url
    ))
    
    acl_filter = ACLFilter(ACLFilterConfig())
    user_extractor = UserContextExtractor(config.jwt_secret)
    
    # Store in app state
    app.state.preprocessor = preprocessor
    app.state.hybrid = hybrid
    app.state.reranker = reranker
    app.state.acl_filter = acl_filter
    app.state.user_extractor = user_extractor
    app.state.config = config
    
    yield
    
    # Shutdown
    await preprocessor.close()
    await semantic.close()
    await keyword.close()
    await reranker.close()

def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="Retrieval Service",
        description="Hybrid search retrieval service for RAG pipeline",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )
    
    # Request timing middleware
    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        process_time = (time.time() - start) * 1000
        response.headers["X-Process-Time-Ms"] = str(process_time)
        return response
    
    # Exception handler
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc) if app.state.config.debug else None
            }
        )
    
    # Routes
    app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
    app.include_router(health.router, tags=["Health"])
    
    return app

app = create_app()
```

### Retrieval Routes

```python
from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import uuid4
from datetime import datetime
import time

from api.schemas.retrieve import (
    RetrieveRequest,
    RetrieveResponse,
    RetrievedDocument,
    SearchMetrics,
    SearchMode,
    MultiQueryRequest
)
from acl.models import UserContext

router = APIRouter()

async def get_user_context(request: Request) -> UserContext:
    """Dependency to extract user context from JWT."""
    return await request.app.state.user_extractor.extract(request)

@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    request: Request,
    body: RetrieveRequest,
    user: UserContext = Depends(get_user_context)
):
    """
    Retrieve relevant documents for a query.
    
    Performs hybrid search (semantic + keyword) with ACL filtering
    and optional reranking.
    
    **Search Modes:**
    - `hybrid`: Combines semantic and keyword search (default)
    - `semantic`: Vector similarity search only
    - `keyword`: BM25 keyword search only
    
    **Reranking:**
    When enabled, top results are reranked using a cross-encoder
    model for improved relevance ordering.
    
    **Filters:**
    Additional filters can be applied to narrow results by metadata
    (e.g., source_type, date range, custom fields).
    """
    start_time = time.time()
    query_id = uuid4()
    
    # Get components from app state
    preprocessor = request.app.state.preprocessor
    hybrid = request.app.state.hybrid
    reranker = request.app.state.reranker
    acl_filter = request.app.state.acl_filter
    
    # Build ACL filter
    filters = acl_filter.build_filter(user, body.filters)
    
    # Preprocess query
    preprocess_start = time.time()
    processed = await preprocessor.process(body.query)
    preprocess_time = (time.time() - preprocess_start) * 1000
    
    # Execute search based on mode
    semantic_time = None
    keyword_time = None
    fusion_time = None
    
    if body.mode == SearchMode.HYBRID:
        # Update hybrid config with request weights
        from search.hybrid import HybridSearchConfig
        config = HybridSearchConfig(
            semantic_weight=body.semantic_weight,
            keyword_weight=body.keyword_weight,
            top_k=body.rerank_top_k if body.rerank else body.top_k
        )
        
        search_response = await hybrid.search(
            query=body.query,
            query_embedding=processed.embedding,
            filters=filters,
            config=config
        )
        
        semantic_count = search_response.total_semantic
        keyword_count = search_response.total_keyword
        fused_count = len(search_response.results)
        
    elif body.mode == SearchMode.SEMANTIC:
        search_response = await hybrid.search_semantic_only(
            query_embedding=processed.embedding,
            top_k=body.rerank_top_k if body.rerank else body.top_k,
            filters=filters
        )
        semantic_count = search_response.total_semantic
        keyword_count = 0
        fused_count = len(search_response.results)
        
    else:  # KEYWORD
        search_response = await hybrid.search_keyword_only(
            query=body.query,
            top_k=body.rerank_top_k if body.rerank else body.top_k,
            filters=filters
        )
        semantic_count = 0
        keyword_count = search_response.total_keyword
        fused_count = len(search_response.results)
    
    # Rerank if enabled
    rerank_time = None
    results = search_response.results
    
    if body.rerank and results:
        rerank_start = time.time()
        results = await reranker.rerank_fused_results(
            query=body.query,
            fused_results=results,
            top_k=body.top_k
        )
        rerank_time = (time.time() - rerank_start) * 1000
    
    # Apply score threshold
    if body.min_score > 0:
        results = [r for r in results if r.fused_score >= body.min_score]
    
    # Limit to top_k
    results = results[:body.top_k]
    
    # Convert to response format
    response_results = [
        RetrievedDocument(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            content=r.content,
            score=r.fused_score,
            title=r.title,
            source=r.source,
            source_type=r.metadata.get("source_type"),
            chunk_index=r.metadata.get("chunk_index", 0),
            total_chunks=r.metadata.get("total_chunks", 1),
            created_at=r.metadata.get("created_at"),
            updated_at=r.metadata.get("updated_at"),
            semantic_score=r.semantic_score,
            keyword_score=r.keyword_score,
            rerank_score=r.metadata.get("rerank_score"),
            metadata={
                k: v for k, v in r.metadata.items()
                if k not in ["chunk_index", "total_chunks", "created_at", 
                            "updated_at", "rerank_score", "source_type"]
            } if body.include_metadata else {}
        )
        for r in results
    ]
    
    total_time = (time.time() - start_time) * 1000
    
    return RetrieveResponse(
        results=response_results,
        total_results=len(response_results),
        query=body.query,
        mode=body.mode,
        metrics=SearchMetrics(
            query_preprocessing_ms=preprocess_time,
            semantic_search_ms=semantic_time,
            keyword_search_ms=keyword_time,
            fusion_ms=fusion_time,
            rerank_ms=rerank_time,
            total_ms=total_time,
            semantic_results_count=semantic_count,
            keyword_results_count=keyword_count,
            fused_results_count=fused_count,
            final_results_count=len(response_results)
        ),
        query_id=query_id,
        processed_at=datetime.utcnow()
    )


@router.post("/retrieve/multi", response_model=RetrieveResponse)
async def retrieve_multi(
    request: Request,
    body: MultiQueryRequest,
    user: UserContext = Depends(get_user_context)
):
    """
    Retrieve using multiple query variations.
    
    Useful for complex queries where different phrasings
    might match different relevant documents.
    
    **Aggregation Methods:**
    - `max`: Use maximum score across queries
    - `avg`: Average scores across queries
    - `rrf`: Reciprocal Rank Fusion
    """
    start_time = time.time()
    query_id = uuid4()
    
    preprocessor = request.app.state.preprocessor
    hybrid = request.app.state.hybrid
    reranker = request.app.state.reranker
    acl_filter = request.app.state.acl_filter
    
    filters = acl_filter.build_filter(user, body.filters)
    
    # Process all queries
    processed_queries = []
    for q in body.queries:
        processed = await preprocessor.process(q)
        processed_queries.append(processed)
    
    # Search with multiple embeddings
    from search.semantic import SemanticSearcher
    embeddings = [p.embedding for p in processed_queries]
    
    # Use multi-vector search
    search_response = await hybrid.semantic.search_multi_vector(
        query_embeddings=embeddings,
        top_k=body.top_k * 2,  # Get more for reranking
        filters=filters,
        aggregation=body.aggregation
    )
    
    results = search_response.results
    
    # Rerank
    if body.rerank and results:
        # Use first query for reranking
        results = await reranker.rerank_fused_results(
            query=body.queries[0],
            fused_results=results,
            top_k=body.top_k
        )
    
    results = results[:body.top_k]
    
    # Convert to response
    response_results = [
        RetrievedDocument(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            content=r.content,
            score=r.fused_score if hasattr(r, 'fused_score') else r.score,
            title=r.title,
            source=r.source,
            metadata=r.metadata
        )
        for r in results
    ]
    
    total_time = (time.time() - start_time) * 1000
    
    return RetrieveResponse(
        results=response_results,
        total_results=len(response_results),
        query="; ".join(body.queries),
        mode=SearchMode.SEMANTIC,
        metrics=SearchMetrics(
            query_preprocessing_ms=0,
            total_ms=total_time,
            final_results_count=len(response_results)
        ),
        query_id=query_id,
        processed_at=datetime.utcnow()
    )


@router.get("/retrieve/explain/{chunk_id}")
async def explain_retrieval(
    request: Request,
    chunk_id: str,
    query: str,
    user: UserContext = Depends(get_user_context)
):
    """
    Explain why a specific chunk was retrieved for a query.
    
    Returns score breakdown and relevance analysis.
    """
    preprocessor = request.app.state.preprocessor
    reranker = request.app.state.reranker
    
    # Get chunk content from vector store
    hybrid = request.app.state.hybrid
    # ... implementation would fetch chunk and compute scores
    
    return {
        "chunk_id": chunk_id,
        "query": query,
        "explanation": {
            "semantic_similarity": 0.85,
            "keyword_matches": ["machine", "learning"],
            "rerank_score": 0.92,
            "matching_terms": ["ML", "artificial intelligence"]
        }
    }
```

### Health Check Routes

```python
from fastapi import APIRouter, Request
from datetime import datetime
from api.schemas.retrieve import HealthResponse

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """
    Check service health.
    
    Returns status of all dependent components.
    """
    components = {}
    
    # Check Qdrant
    try:
        await request.app.state.hybrid.semantic.health_check()
        components["qdrant"] = True
    except:
        components["qdrant"] = False
    
    # Check OpenSearch
    try:
        await request.app.state.hybrid.keyword.health_check()
        components["opensearch"] = True
    except:
        components["opensearch"] = False
    
    # Check Reranker
    try:
        await request.app.state.reranker.health_check()
        components["reranker"] = True
    except:
        components["reranker"] = False
    
    # Determine overall status
    all_healthy = all(components.values())
    any_healthy = any(components.values())
    
    if all_healthy:
        status = "healthy"
    elif any_healthy:
        status = "degraded"
    else:
        status = "unhealthy"
    
    return HealthResponse(
        status=status,
        version="1.0.0",
        components=components,
        timestamp=datetime.utcnow()
    )

@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "alive"}

@router.get("/health/ready")
async def readiness(request: Request):
    """Kubernetes readiness probe."""
    # Check if we can handle requests
    try:
        await request.app.state.hybrid.semantic.health_check()
        return {"status": "ready"}
    except:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Service not ready")
```

### Entry Point

```python
# run.py
import uvicorn
from config import RetrievalConfig

def main():
    config = RetrievalConfig()
    
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=config.service_port,
        reload=config.debug,
        log_level="debug" if config.debug else "info"
    )

if __name__ == "__main__":
    main()
```

## OpenAPI Documentation

The API automatically generates OpenAPI documentation available at:
- Swagger UI: `http://localhost:8002/docs`
- ReDoc: `http://localhost:8002/redoc`
- OpenAPI JSON: `http://localhost:8002/openapi.json`

## Acceptance Criteria

- [ ] POST `/api/v1/retrieve` endpoint works with hybrid search
- [ ] Supports semantic-only and keyword-only modes
- [ ] Configurable fusion weights per request
- [ ] Reranking toggle with configurable top-k
- [ ] Metadata filters passed to search
- [ ] ACL filtering applied based on JWT
- [ ] Score threshold filtering
- [ ] Response includes score breakdown
- [ ] Response includes timing metrics
- [ ] Multi-query endpoint supports query variations
- [ ] Explain endpoint provides relevance breakdown
- [ ] Health endpoints for monitoring
- [ ] Kubernetes readiness/liveness probes
- [ ] OpenAPI documentation generated
- [ ] P95 latency < 200ms

## Testing Requirements

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from uuid import uuid4

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def auth_header():
    from jose import jwt
    token = jwt.encode({
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "groups": ["users"],
        "roles": ["user"]
    }, "test-secret")
    return {"Authorization": f"Bearer {token}"}

def test_retrieve_endpoint(client, auth_header):
    """Test main retrieve endpoint."""
    response = client.post(
        "/api/v1/retrieve",
        json={
            "query": "machine learning",
            "top_k": 10,
            "mode": "hybrid"
        },
        headers=auth_header
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "metrics" in data
    assert data["mode"] == "hybrid"

def test_retrieve_semantic_only(client, auth_header):
    """Test semantic-only mode."""
    response = client.post(
        "/api/v1/retrieve",
        json={
            "query": "machine learning",
            "mode": "semantic"
        },
        headers=auth_header
    )
    
    assert response.status_code == 200
    assert response.json()["mode"] == "semantic"

def test_retrieve_with_filters(client, auth_header):
    """Test retrieval with metadata filters."""
    response = client.post(
        "/api/v1/retrieve",
        json={
            "query": "test",
            "filters": {
                "source_type": "documentation"
            }
        },
        headers=auth_header
    )
    
    assert response.status_code == 200

def test_retrieve_requires_auth(client):
    """Test that auth is required."""
    response = client.post(
        "/api/v1/retrieve",
        json={"query": "test"}
    )
    
    assert response.status_code == 401

def test_health_endpoint(client):
    """Test health check."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "components" in data

def test_liveness_probe(client):
    """Test liveness probe."""
    response = client.get("/health/live")
    assert response.status_code == 200

def test_query_validation(client, auth_header):
    """Test request validation."""
    # Empty query
    response = client.post(
        "/api/v1/retrieve",
        json={"query": ""},
        headers=auth_header
    )
    assert response.status_code == 422
    
    # top_k out of range
    response = client.post(
        "/api/v1/retrieve",
        json={"query": "test", "top_k": 1000},
        headers=auth_header
    )
    assert response.status_code == 422

def test_response_includes_metrics(client, auth_header):
    """Test that response includes timing metrics."""
    response = client.post(
        "/api/v1/retrieve",
        json={"query": "test"},
        headers=auth_header
    )
    
    data = response.json()
    assert "metrics" in data
    assert "total_ms" in data["metrics"]
    assert "query_preprocessing_ms" in data["metrics"]

def test_score_breakdown_included(client, auth_header):
    """Test that score breakdown is in results."""
    response = client.post(
        "/api/v1/retrieve",
        json={"query": "test", "rerank": True},
        headers=auth_header
    )
    
    data = response.json()
    if data["results"]:
        result = data["results"][0]
        # Should have score fields
        assert "score" in result
```

## Integration Test

```python
@pytest.mark.integration
def test_full_retrieval_flow():
    """Integration test with real services."""
    from fastapi.testclient import TestClient
    from api.main import app
    from jose import jwt
    
    client = TestClient(app)
    
    token = jwt.encode({
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "groups": ["users"],
        "roles": ["user"]
    }, "test-secret")
    
    response = client.post(
        "/api/v1/retrieve",
        json={
            "query": "machine learning introduction",
            "mode": "hybrid",
            "top_k": 5,
            "rerank": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["results"]) <= 5
    assert data["metrics"]["total_ms"] < 200  # P95 target
```

## Dependencies

- `fastapi>=0.104.0`
- `uvicorn>=0.24.0`
- `pydantic>=2.5.0`
- `python-jose[cryptography]>=3.3.0`

## Performance Requirements

- P95 latency: < 200ms
- Throughput: 100+ QPS
- Cold start: < 5s

## Definition of Done

- [ ] POST /retrieve endpoint implemented
- [ ] Hybrid, semantic, keyword modes work
- [ ] ACL filtering applied
- [ ] Reranking toggle works
- [ ] Metadata filters supported
- [ ] Response includes metrics
- [ ] Multi-query endpoint works
- [ ] Health endpoints implemented
- [ ] OpenAPI docs generated
- [ ] Request validation works
- [ ] Error handling complete
- [ ] >90% test coverage
- [ ] Integration test passes
- [ ] P95 < 200ms achieved
- [ ] Docstrings complete
- [ ] Type hints validated with mypy
