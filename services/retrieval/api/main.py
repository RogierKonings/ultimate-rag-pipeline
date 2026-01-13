"""FastAPI application for the Retrieval Service."""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from acl.context import UserContextExtractor
from acl.filter import ACLFilter
from acl.models import ACLFilterConfig
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from query.models import QueryPreprocessorConfig
from query.preprocessor import QueryPreprocessor
from reranking.models import RerankerConfig
from reranking.reranker import RerankerService
from search.fusion import HybridSearchConfig
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher, OpenSearchConfig
from search.semantic import QdrantConfig, SemanticSearcher

from api.routes import health, retrieve
from config import RetrievalConfig


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown."""
    config = app.state.config

    # Initialize components
    preprocessor = QueryPreprocessor(
        QueryPreprocessorConfig(
            llm_gateway_url=config.llm_gateway_url,
            embedding_model=config.embedding_model,
            embedding_dimension=config.embedding_dimension,
            embedding_prefix=config.embedding_prefix,
        ),
    )

    semantic = SemanticSearcher(
        QdrantConfig(
            url=config.qdrant_url,
            collection_name=config.qdrant_collection,
        ),
    )
    await semantic.connect()

    keyword = KeywordSearcher(
        OpenSearchConfig(
            url=config.opensearch_url,
            index_name=config.opensearch_index,
        ),
    )
    await keyword.connect()

    hybrid = HybridSearcher(
        semantic,
        keyword,
        HybridSearchConfig(
            semantic_weight=config.semantic_weight,
            keyword_weight=config.keyword_weight,
        ),
    )

    reranker = RerankerService(
        RerankerConfig(
            llm_gateway_url=config.llm_gateway_url,
        ),
    )

    acl_filter = ACLFilter(ACLFilterConfig())
    user_extractor = UserContextExtractor(
        secret_key=config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )

    # Store in app state
    app.state.preprocessor = preprocessor
    app.state.hybrid = hybrid
    app.state.reranker = reranker
    app.state.acl_filter = acl_filter
    app.state.user_extractor = user_extractor

    yield

    # Shutdown
    await preprocessor.close()
    await semantic.close()
    await keyword.close()
    await reranker.close()


def create_app(config: RetrievalConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional configuration. Uses defaults if not provided.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = RetrievalConfig()

    app = FastAPI(
        title="Retrieval Service",
        description="Hybrid search retrieval service for RAG pipeline",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Store config in app state for access during lifespan
    app.state.config = config

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request timing middleware
    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        process_time = (time.time() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
        return response

    # Exception handlers
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": str(exc) if config.debug else None,
            },
        )

    # Include routers
    app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
    app.include_router(health.router, tags=["Health"])

    return app


# Default application instance
app = create_app()
