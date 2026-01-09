"""
OpenAI-compatible API routes for the Gateway.

Provides endpoints for:
- Chat completions
- Embeddings
- Reranking
- Model listing
- Health checks
"""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..clients import EmbeddingClient, RerankerClient, VLLMClient
from ..models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ErrorResponse,
    ModelInfo,
    ModelListResponse,
    RerankRequest,
    RerankResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Client instances (will be set by dependency injection or startup)
_vllm_client: Optional[VLLMClient] = None
_embedding_client: Optional[EmbeddingClient] = None
_reranker_client: Optional[RerankerClient] = None


def get_vllm_client() -> VLLMClient:
    """Get vLLM client instance."""
    global _vllm_client
    if _vllm_client is None:
        _vllm_client = VLLMClient()
    return _vllm_client


def get_embedding_client() -> EmbeddingClient:
    """Get embedding client instance."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client


def get_reranker_client() -> RerankerClient:
    """Get reranker client instance."""
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = RerankerClient()
    return _reranker_client


def get_context_headers(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
) -> dict[str, str]:
    """Extract context headers for downstream services."""
    headers = {}
    if x_tenant_id:
        headers["X-Tenant-ID"] = x_tenant_id
    if x_user_id:
        headers["X-User-ID"] = x_user_id
    if x_request_id:
        headers["X-Request-ID"] = x_request_id
    return headers


# =============================================================================
# Health Endpoints
# =============================================================================


@router.get("/health")
async def health_check(
    vllm: VLLMClient = Depends(get_vllm_client),
    embedding: EmbeddingClient = Depends(get_embedding_client),
    reranker: RerankerClient = Depends(get_reranker_client),
):
    """Check health of all backend services."""
    vllm_healthy = await vllm.health_check()
    embedding_healthy = await embedding.health_check()
    reranker_healthy = await reranker.health_check()

    all_healthy = vllm_healthy and embedding_healthy and reranker_healthy

    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": {
            "vllm": "healthy" if vllm_healthy else "unhealthy",
            "embedding": "healthy" if embedding_healthy else "unhealthy",
            "reranker": "healthy" if reranker_healthy else "unhealthy",
        },
    }


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    vllm: VLLMClient = Depends(get_vllm_client),
):
    """Kubernetes readiness probe."""
    if await vllm.health_check():
        return {"status": "ready"}
    raise HTTPException(status_code=503, detail="Service not ready")


# =============================================================================
# Model Endpoints
# =============================================================================


@router.get("/v1/models", response_model=ModelListResponse)
async def list_models(
    vllm: VLLMClient = Depends(get_vllm_client),
    embedding: EmbeddingClient = Depends(get_embedding_client),
    reranker: RerankerClient = Depends(get_reranker_client),
):
    """List all available models."""
    models = []

    # Get vLLM models
    try:
        vllm_models = await vllm.list_models()
        for m in vllm_models:
            models.append(
                ModelInfo(
                    id=m.get("id", "unknown"),
                    owned_by="vllm",
                )
            )
    except Exception as e:
        logger.warning(f"Failed to get vLLM models: {e}")

    # Add embedding model
    try:
        info = await embedding.get_model_info()
        if info and info.get("model_loaded"):
            models.append(
                ModelInfo(
                    id=embedding.default_model,
                    owned_by="embedding-service",
                )
            )
    except Exception as e:
        logger.warning(f"Failed to get embedding model: {e}")

    # Add reranker model
    try:
        info = await reranker.get_model_info()
        if info and info.get("model_loaded"):
            models.append(
                ModelInfo(
                    id=reranker.default_model,
                    owned_by="reranker-service",
                )
            )
    except Exception as e:
        logger.warning(f"Failed to get reranker model: {e}")

    return ModelListResponse(data=models)


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    """Get information about a specific model."""
    return ModelInfo(id=model_id)


# =============================================================================
# Chat Completions
# =============================================================================


@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    vllm: VLLMClient = Depends(get_vllm_client),
    context_headers: dict = Depends(get_context_headers),
):
    """
    Create a chat completion.

    Compatible with OpenAI's chat completion API.
    """
    start_time = time.time()

    try:
        if request.stream:
            # Streaming response
            async def generate():
                try:
                    async for chunk in vllm.chat_completion_stream(
                        request, context_headers
                    ):
                        yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    error = ErrorResponse.create(str(e), "server_error")
                    yield f"data: {error.model_dump_json()}\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
        else:
            # Non-streaming response
            response = await vllm.chat_completion(request, context_headers)

            latency_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Chat completion: model={request.model} "
                f"messages={len(request.messages)} latency={latency_ms:.1f}ms"
            )

            return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat completion error: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(str(e), "server_error").model_dump(),
        )


# =============================================================================
# Embeddings
# =============================================================================


@router.post("/v1/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(
    request: EmbeddingRequest,
    embedding: EmbeddingClient = Depends(get_embedding_client),
    context_headers: dict = Depends(get_context_headers),
):
    """
    Create embeddings for the given input.

    Compatible with OpenAI's embeddings API.
    """
    start_time = time.time()

    try:
        response = await embedding.create_embeddings(request, context_headers)

        input_count = (
            len(request.input) if isinstance(request.input, list) else 1
        )
        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Embeddings: model={request.model} count={input_count} "
            f"latency={latency_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(str(e), "server_error").model_dump(),
        )


# =============================================================================
# Reranking
# =============================================================================


@router.post("/v1/rerank", response_model=RerankResponse)
async def create_rerank(
    request: RerankRequest,
    reranker: RerankerClient = Depends(get_reranker_client),
    context_headers: dict = Depends(get_context_headers),
):
    """
    Rerank documents against a query.

    This endpoint follows a similar pattern to Cohere's rerank API.
    """
    start_time = time.time()

    try:
        response = await reranker.rerank(request, context_headers)

        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Rerank: model={request.model} documents={len(request.documents)} "
            f"latency={latency_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rerank error: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse.create(str(e), "server_error").model_dump(),
        )


# Alias for /v1/rerankings (alternative endpoint name)
@router.post("/v1/rerankings", response_model=RerankResponse)
async def create_rerankings(
    request: RerankRequest,
    reranker: RerankerClient = Depends(get_reranker_client),
    context_headers: dict = Depends(get_context_headers),
):
    """Alias for /v1/rerank endpoint."""
    return await create_rerank(request, reranker, context_headers)
