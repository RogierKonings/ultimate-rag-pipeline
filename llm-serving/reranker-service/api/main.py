"""
Reranker Service FastAPI Application.

Provides cross-encoder based document reranking.
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from ..core.batching import RerankBatcher
from ..core.reranker import RerankerService
from .models import (
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    RerankRequest,
    RerankResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUESTS_TOTAL = Counter(
    "rerank_requests_total",
    "Total rerank requests",
    ["status", "model"],
)
REQUEST_LATENCY = Histogram(
    "rerank_request_latency_seconds",
    "Rerank request latency",
    ["model"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)
PAIRS_PER_REQUEST = Histogram(
    "rerank_pairs_per_request",
    "Number of pairs per rerank request",
    buckets=[1, 5, 10, 20, 50, 100],
)
QUEUE_SIZE = Gauge(
    "rerank_queue_size",
    "Current queue size",
)

# Global instances
reranker_service: RerankerService | None = None
batcher: RerankBatcher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global reranker_service, batcher

    # Load configuration from environment
    model_name = os.environ.get("MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    max_sequence_length = int(os.environ.get("MAX_SEQUENCE_LENGTH", "512"))
    max_batch_size = int(os.environ.get("MAX_BATCH_SIZE", "32"))
    batch_timeout_ms = float(os.environ.get("BATCH_TIMEOUT_MS", "50"))
    use_fp16 = os.environ.get("USE_FP16", "true").lower() == "true"
    device = os.environ.get("DEVICE", "cuda")
    normalize_scores = os.environ.get("NORMALIZE_SCORES", "false").lower() == "true"
    max_queue_size = int(os.environ.get("MAX_QUEUE_SIZE", "1000"))

    # Initialize reranker service
    reranker_service = RerankerService(
        model_name=model_name,
        max_sequence_length=max_sequence_length,
        device=device,
        use_fp16=use_fp16,
        normalize_scores=normalize_scores,
        max_batch_size=max_batch_size,
    )
    await reranker_service.load_model()

    # Initialize batcher
    batcher = RerankBatcher(
        score_fn=reranker_service._score_pairs_batch,
        max_batch_size=max_batch_size,
        batch_timeout_ms=batch_timeout_ms,
        max_queue_size=max_queue_size,
    )
    await batcher.start()

    logger.info("Reranker service ready")

    yield

    # Cleanup
    await batcher.stop()
    await reranker_service.close()
    logger.info("Reranker service shutdown complete")


app = FastAPI(
    title="Reranker Service",
    description="Cross-encoder based document reranking",
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


@app.post("/rerank", response_model=RerankResponse)
async def rerank_documents(request: RerankRequest):
    """
    Rerank documents for a query.

    Accepts either:
    - query + documents: Scores query against each document
    - pairs: Scores each query-document pair
    """
    start_time = time.time()

    try:
        if request.pairs:
            # Use pre-formed pairs
            PAIRS_PER_REQUEST.observe(len(request.pairs))

            response = await reranker_service.rerank_pairs(
                pairs=request.pairs,
                top_k=request.top_k,
                min_score=request.min_score,
                return_documents=request.return_documents,
            )
        elif request.query and request.documents:
            # Use query + documents
            PAIRS_PER_REQUEST.observe(len(request.documents))

            response = await reranker_service.rerank(
                query=request.query,
                documents=request.documents,
                top_k=request.top_k,
                min_score=request.min_score,
                return_documents=request.return_documents,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either (query + documents) or pairs",
            )

        latency = time.time() - start_time
        REQUEST_LATENCY.labels(model=request.model).observe(latency)
        REQUESTS_TOTAL.labels(status="success", model=request.model).inc()

        return response

    except HTTPException:
        raise
    except Exception as e:
        REQUESTS_TOTAL.labels(status="error", model=request.model).inc()
        logger.error(f"Rerank error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank_v1(request: RerankRequest):
    """Versioned rerank endpoint (alias)."""
    return await rerank_documents(request)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    health = reranker_service.get_health()

    if batcher:
        metrics = batcher.get_metrics()
        health.queue_size = metrics["queue_size"]
        QUEUE_SIZE.set(metrics["queue_size"])

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
    """List available reranker models."""
    return ModelsResponse(
        data=[
            ModelInfo(
                id=reranker_service.model_name,
                owned_by="bge",
                type="reranker",
            ),
        ],
    )
