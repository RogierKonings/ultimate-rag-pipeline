"""
Main FastAPI application for the Unified OpenAI Gateway.

This is the entry point for the gateway service that exposes
OpenAI-compatible endpoints for chat, embeddings, and reranking.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from ..clients import EmbeddingClient, RerankerClient, VLLMClient
from ..security import (
    AuthMiddleware,
    RateLimitMiddleware,
)
from ..security.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from . import routes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Unified OpenAI Gateway...")

    # Initialize clients with configuration from environment
    vllm_url = os.getenv("VLLM_URL", "http://localhost:8000")
    embedding_url = os.getenv("EMBEDDING_URL", "http://localhost:8001")
    reranker_url = os.getenv("RERANKER_URL", "http://localhost:8002")

    routes._vllm_client = VLLMClient(
        base_url=vllm_url,
        default_model=os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
    )
    routes._embedding_client = EmbeddingClient(
        base_url=embedding_url,
        default_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"),
    )
    routes._reranker_client = RerankerClient(
        base_url=reranker_url,
        default_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
    )

    logger.info(f"vLLM client configured: {vllm_url}")
    logger.info(f"Embedding client configured: {embedding_url}")
    logger.info(f"Reranker client configured: {reranker_url}")

    yield

    # Shutdown
    logger.info("Shutting down Unified OpenAI Gateway...")
    await routes._vllm_client.close()
    await routes._embedding_client.close()
    await routes._reranker_client.close()


# Create FastAPI application
app = FastAPI(
    title="Unified OpenAI Gateway",
    description="""
OpenAI-compatible API gateway for LLM serving layer.

## Endpoints

### Chat Completions
- `POST /v1/chat/completions` - Create chat completions (streaming supported)

### Embeddings
- `POST /v1/embeddings` - Generate text embeddings

### Reranking
- `POST /v1/rerank` - Rerank documents against a query
- `POST /v1/rerankings` - Alias for rerank endpoint

### Models
- `GET /v1/models` - List available models
- `GET /v1/models/{model_id}` - Get model information

### Health
- `GET /health` - Service health status
- `GET /health/live` - Liveness probe
- `GET /health/ready` - Readiness probe

## Authentication

Include your API key in the `Authorization` header:
```
Authorization: Bearer <your-api-key>
```

Or use the `X-API-Key` header:
```
X-API-Key: <your-api-key>
```

## Context Headers

The following headers are propagated to downstream services:
- `X-Tenant-ID` - Tenant identifier
- `X-User-ID` - User identifier
- `X-Request-ID` - Request correlation ID
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add middleware (order matters - first added is last executed)
# Security headers (outermost)
app.add_middleware(SecurityHeadersMiddleware)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# Rate limiting (needs auth context)
if os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true":
    app.add_middleware(RateLimitMiddleware)

# Authentication
if os.getenv("AUTH_ENABLED", "false").lower() == "true":
    app.add_middleware(AuthMiddleware)

# CORS (innermost for preflight requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(routes.router)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Unified OpenAI Gateway",
        "version": "1.0.0",
        "description": "OpenAI-compatible API gateway for LLM serving",
        "docs_url": "/docs",
        "openapi_url": "/openapi.json",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "embeddings": "/v1/embeddings",
            "rerank": "/v1/rerank",
            "models": "/v1/models",
            "health": "/health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8004")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
    )
