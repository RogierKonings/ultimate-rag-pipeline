"""Capability discovery endpoint for the Orchestrator Service.

This module provides a single endpoint that exposes runtime service
capabilities so the frontend can safely enable or disable UI features
(e.g. video search, reranker, streaming) without hard-coding assumptions.

GET /api/v1/capabilities -> ServiceCapabilities
"""

import structlog
from api.models.responses import ServiceCapabilities
from fastapi import APIRouter, Request

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Capabilities"])


async def _check_retrieval_reachable(request: Request) -> bool:
    """Check whether the retrieval service is reachable.

    Uses the retrieval client's health check if available, otherwise
    falls back to checking whether the client was initialised at all.

    Returns:
        True if the retrieval service appears reachable.
    """
    retrieval_client = getattr(request.app.state, "retrieval_client", None)
    if retrieval_client is None:
        return False
    try:
        result = await retrieval_client.health_check()
        if isinstance(result, dict):
            return result.get("status") in ("healthy", "degraded")
        return True
    except Exception:
        return False


async def _check_llm_gateway_reachable(request: Request) -> bool:
    """Check whether the LLM gateway (model gateway) is reachable.

    Returns:
        True if at least one model is healthy.
    """
    model_gateway = getattr(request.app.state, "model_gateway", None)
    if model_gateway is None:
        return False
    try:
        health_result = await model_gateway.health_check()
        return any(
            (m.status if hasattr(m, "status") else m.get("status")) == "healthy"
            for m in (
                health_result.values()
                if isinstance(health_result, dict)
                else [health_result]
            )
        )
    except Exception:
        return False


@router.get(
    "/capabilities",
    response_model=ServiceCapabilities,
    summary="Service capability discovery",
    description=(
        "Returns runtime feature availability so the frontend can "
        "conditionally enable or disable UI features."
    ),
)
async def get_capabilities(request: Request) -> ServiceCapabilities:
    """Return the current runtime capabilities of the orchestrator.

    The endpoint inspects application state to determine which
    components are initialised and reachable, then builds a feature
    map that the frontend can consume.

    Feature keys:
        streaming: Whether the SSE streaming endpoint is available.
        reranker: Whether the retrieval service (which includes reranking)
                  is reachable.
        video_search: Whether video search is supported (currently
                      requires retrieval service; hardcoded False until
                      the video pipeline is production-ready).
        query_expansion: Whether multi-query / query expansion is
                         available (not yet implemented).
        guardrails: Whether the guardrail pipeline is initialised.
        session_memory: Whether session / conversation memory is available.
        feedback: Whether the feedback endpoint is available.
        answer_verification: Whether CRAG-style answer verification
                             is enabled.

    Returns:
        ServiceCapabilities with version and features dict.
    """
    # Check component availability from app state
    stream_manager = getattr(request.app.state, "stream_manager", None)
    guardrail_pipeline = getattr(request.app.state, "guardrail_pipeline", None)
    session_manager = getattr(request.app.state, "session_manager", None)
    workflow = getattr(request.app.state, "workflow", None)

    # Runtime checks against downstream services
    retrieval_ok = await _check_retrieval_reachable(request)
    llm_ok = await _check_llm_gateway_reachable(request)

    # Read config flags
    from config import get_config

    config = get_config()

    features = {
        # Core query features
        "streaming": stream_manager is not None and llm_ok,
        "reranker": retrieval_ok,
        "llm": llm_ok,
        "workflow": workflow is not None,
        # Search modes
        "video_search": False,  # Not production-ready yet
        "query_expansion": False,  # Not implemented yet
        # Safety & quality
        "guardrails": guardrail_pipeline is not None,
        "answer_verification": config.verification_enabled,
        # Session & UX
        "session_memory": session_manager is not None,
        "feedback": True,  # Always available (persisted to DB)
    }

    logger.info(
        "capabilities_requested",
        features=features,
    )

    return ServiceCapabilities(version="1", features=features)
