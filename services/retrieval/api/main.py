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
from retrieval.video.retriever import VideoRetriever, VideoRetrieverConfig
from search.fusion import HybridSearchConfig
from search.hybrid import HybridSearcher
from search.keyword import KeywordSearcher, OpenSearchConfig
from search.semantic import QdrantConfig, SemanticSearcher
from video.clip_cache import ClipCacheConfig, ClipCacheService

from api.routes import clips, health, retrieve, video_retrieve
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

    # Initialize video retriever
    video_retriever = VideoRetriever(
        config=VideoRetrieverConfig(
            qdrant_url=config.qdrant_url,
            opensearch_url=config.opensearch_url,
        ),
        reranker=reranker,
    )

    # Initialize clip cache service
    clip_cache = ClipCacheService(
        ClipCacheConfig(
            minio_url=getattr(config, "minio_url", "localhost:9000"),
            access_key=getattr(config, "minio_access_key", "minioadmin"),
            secret_key=getattr(config, "minio_secret_key", "minioadmin"),
            bucket_name=getattr(config, "minio_bucket", "rag-pipeline"),
        )
    )

    # Store in app state
    app.state.preprocessor = preprocessor
    app.state.hybrid = hybrid
    app.state.reranker = reranker
    app.state.acl_filter = acl_filter
    app.state.user_extractor = user_extractor
    app.state.video_retriever = video_retriever
    app.state.clip_cache = clip_cache

    yield

    # Shutdown
    await preprocessor.close()
    await semantic.close()
    await keyword.close()
    await reranker.close()
    video_retriever.close()


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
    app.include_router(video_retrieve.router, prefix="/api/v1", tags=["Video Retrieval"])
    app.include_router(clips.router, prefix="/api/v1", tags=["Video Clips"])
    app.include_router(health.router, tags=["Health"])

    return app


# Default application instance
app = create_app()
