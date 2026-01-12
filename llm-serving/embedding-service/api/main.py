"""
Embedding Service FastAPI Application.

Provides high-throughput embedding generation with BGE models.
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from ..core.batching import DynamicBatcher
from ..core.embedder import EmbeddingService
from .models import (
    BatchEmbeddingRequest,
    BatchEmbeddingResult,
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
    HealthResponse,
    ModelInfo,
    ModelsResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUESTS_TOTAL = Counter(
    "embedding_requests_total",
    "Total embedding requests",
    ["status", "model"],
)
REQUEST_LATENCY = Histogram(
    "embedding_request_latency_seconds",
    "Embedding request latency",
    ["model"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
BATCH_SIZE = Histogram(
    "embedding_batch_size",
    "Embedding batch sizes",
    buckets=[1, 2, 4, 8, 16, 32, 64, 128],
)
QUEUE_SIZE = Gauge(
    "embedding_queue_size",
    "Current queue size",
)
GPU_MEMORY = Gauge(
    "embedding_gpu_memory_mb",
    "GPU memory usage in MB",
)

# Global service instances
embedding_service: EmbeddingService | None = None
batcher: DynamicBatcher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global embedding_service, batcher

    # Load configuration from environment
    model_name = os.environ.get("MODEL_NAME", "BAAI/bge-large-en-v1.5")
    embedding_dim = int(os.environ.get("EMBEDDING_DIM", "1024"))
    max_sequence_length = int(os.environ.get("MAX_SEQUENCE_LENGTH", "512"))
    max_batch_size = int(os.environ.get("MAX_BATCH_SIZE", "32"))
    max_batch_tokens = int(os.environ.get("MAX_BATCH_TOKENS", "8192"))
    batch_timeout_ms = float(os.environ.get("BATCH_TIMEOUT_MS", "50"))
    use_fp16 = os.environ.get("USE_FP16", "true").lower() == "true"
    device = os.environ.get("DEVICE", "cuda")
    max_queue_size = int(os.environ.get("MAX_QUEUE_SIZE", "1000"))

    # Initialize embedding service
    embedding_service = EmbeddingService(
        model_name=model_name,
        embedding_dim=embedding_dim,
        max_sequence_length=max_sequence_length,
        device=device,
        use_fp16=use_fp16,
        max_batch_size=max_batch_size,
    )
    await embedding_service.load_model()

    # Initialize dynamic batcher
    batcher = DynamicBatcher(
        embed_fn=embedding_service.embed,
        max_batch_size=max_batch_size,
        max_batch_tokens=max_batch_tokens,
        batch_timeout_ms=batch_timeout_ms,
        max_queue_size=max_queue_size,
    )
    await batcher.start()

    logger.info("Embedding service ready")

    yield

    # Cleanup
    await batcher.stop()
    await embedding_service.close()
    logger.info("Embedding service shutdown complete")


app = FastAPI(
    title="Embedding Service",
    description="High-throughput embedding generation with BGE models",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    """Add request timing header."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Request-Time"] = f"{duration:.4f}"
    return response


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(request: EmbeddingRequest):
    """
    Create embeddings for the input text(s).

    OpenAI-compatible endpoint for embedding generation.
    Supports both single string and list of strings as input.
    """
    start_time = time.time()

    try:
        # Normalize input to list
        texts = [request.input] if isinstance(request.input, str) else request.input

        # Record batch size
        BATCH_SIZE.observe(len(texts))

        # Submit to batcher
        embeddings = await batcher.submit(texts, request.input_type)

        # Build response
        data = [
            EmbeddingData(index=i, embedding=emb)
            for i, emb in enumerate(embeddings)
        ]

        total_tokens = sum(len(t.split()) for t in texts)

        response = EmbeddingResponse(
            model=request.model,
            data=data,
            usage=EmbeddingUsage(
                prompt_tokens=total_tokens,
                total_tokens=total_tokens,
            ),
        )

        # Record metrics
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(model=request.model).observe(latency)
        REQUESTS_TOTAL.labels(status="success", model=request.model).inc()

        return response

    except Exception as e:
        REQUESTS_TOTAL.labels(status="error", model=request.model).inc()
        logger.error(f"Embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/embed", response_model=BatchEmbeddingResult)
async def embed_batch(request: BatchEmbeddingRequest):
    """
    Batch embedding endpoint (non-OpenAI format).

    More efficient for internal use with direct list input.
    """
    try:
        embeddings = await batcher.submit(request.texts, request.input_type)

        return BatchEmbeddingResult(
            embeddings=embeddings,
            dimensions=len(embeddings[0]) if embeddings else 0,
            total_tokens=sum(len(t.split()) for t in request.texts),
            processing_time_ms=0,  # Filled by batcher
        )

    except Exception as e:
        logger.error(f"Batch embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    health = embedding_service.get_health()

    # Update queue size from batcher
    if batcher:
        metrics = batcher.get_metrics()
        health.queue_size = metrics["queue_size"]
        QUEUE_SIZE.set(metrics["queue_size"])

    # Update GPU metrics
    if health.gpu_memory_used_mb:
        GPU_MEMORY.set(health.gpu_memory_used_mb)

    if health.status == "unhealthy":
        raise HTTPException(status_code=503, detail="Service unhealthy")

    return health


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain",
    )


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """List available embedding models."""
    return ModelsResponse(
        data=[
            ModelInfo(
                id=embedding_service.model_name,
                owned_by="bge",
            ),
        ],
    )
