"""Embedding service with OpenAI-compatible API.

Provides text embeddings using sentence-transformers models with an
OpenAI-compatible REST API for easy integration with existing clients.
"""

import asyncio
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

# Thread pool for CPU-bound embedding operations
executor = ThreadPoolExecutor(max_workers=2)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
MODEL_NAME = os.getenv("MODEL_NAME", "BAAI/bge-large-en-v1.5")
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "32"))

# Global model instance
model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup, cleanup on shutdown."""
    global model
    logger.info("Loading embedding model: %s", MODEL_NAME)
    start_time = time.time()

    model = SentenceTransformer(MODEL_NAME)

    load_time = time.time() - start_time
    dimension = model.get_sentence_embedding_dimension()
    logger.info(
        "Model loaded in %.2fs. Embedding dimension: %d",
        load_time,
        dimension,
    )
    yield
    logger.info("Shutting down embedding service")
    model = None


app = FastAPI(
    title="Embedding Service",
    description="OpenAI-compatible embedding API using sentence-transformers",
    version="1.0.0",
    lifespan=lifespan,
)


# Request/Response models (OpenAI-compatible)
class EmbeddingRequest(BaseModel):
    """OpenAI-compatible embedding request."""

    input: list[str] | str = Field(..., description="Text(s) to embed")
    model: str = Field(default=MODEL_NAME, description="Model to use")
    encoding_format: str = Field(default="float", description="Encoding format")


class EmbeddingData(BaseModel):
    """Single embedding result."""

    embedding: list[float]
    index: int
    object: str = "embedding"


class Usage(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    """OpenAI-compatible embedding response."""

    data: list[EmbeddingData]
    model: str
    object: str = "list"
    usage: Usage


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    """Generate embeddings for input text(s).

    This endpoint is compatible with the OpenAI embeddings API.

    Args:
        request: Embedding request with input text(s).

    Returns:
        EmbeddingResponse with embeddings and usage info.

    Raises:
        HTTPException: If model not loaded or batch size exceeded.
    """
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded yet. Please wait for startup to complete.",
        )

    # Normalize input to list
    texts = [request.input] if isinstance(request.input, str) else request.input

    if not texts:
        raise HTTPException(status_code=400, detail="Input cannot be empty")

    if len(texts) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(texts)} exceeds maximum {MAX_BATCH_SIZE}",
        )

    start_time = time.time()

    try:
        # Run embedding in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            executor,
            lambda: model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Generated %d embeddings in %.2fms (%.2fms/text)",
            len(texts),
            elapsed_ms,
            elapsed_ms / len(texts),
        )

        # Estimate tokens (rough approximation: ~0.75 tokens per word)
        total_tokens = sum(int(len(t.split()) * 0.75) for t in texts)

        return EmbeddingResponse(
            data=[
                EmbeddingData(embedding=emb.tolist(), index=i)
                for i, emb in enumerate(embeddings)
            ],
            model=MODEL_NAME,
            usage=Usage(prompt_tokens=total_tokens, total_tokens=total_tokens),
        )
    except Exception as e:
        logger.error("Embedding generation failed: %s", str(e))
        logger.error("Traceback: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns:
        Health status including model info.
    """
    if model is None:
        return {
            "status": "loading",
            "model": MODEL_NAME,
            "dimension": None,
            "message": "Model is still loading",
        }

    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "dimension": model.get_sentence_embedding_dimension(),
        "max_batch_size": MAX_BATCH_SIZE,
    }


@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI compatibility).

    Returns:
        List of available models.
    """
    dimension = model.get_sentence_embedding_dimension() if model else None

    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": 0,
                "owned_by": "local",
                "permission": [],
                "root": MODEL_NAME,
                "parent": None,
                "metadata": {
                    "dimension": dimension,
                    "max_batch_size": MAX_BATCH_SIZE,
                },
            }
        ],
    }


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "embedding-service",
        "version": "1.0.0",
        "model": MODEL_NAME,
        "endpoints": {
            "embeddings": "/v1/embeddings",
            "models": "/v1/models",
            "health": "/health",
        },
    }
