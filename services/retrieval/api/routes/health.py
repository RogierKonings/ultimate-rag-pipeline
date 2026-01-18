"""Health check endpoints for the Retrieval Service."""

import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import ComponentHealth, HealthResponse
from resilience import DegradationMode, get_degradation_manager

router = APIRouter()

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """
    Check service health.

    Returns status of all dependent components including:
    - Qdrant (semantic search)
    - OpenSearch (keyword search)
    - Reranker (LLM Gateway)

    Also includes degradation mode and capabilities.

    **Status Values:**
    - `healthy`: All components operational
    - `degraded`: Some components down but service functional
    - `unhealthy`: Critical components down
    """
    components: dict[str, bool] = {}
    component_details: list[ComponentHealth] = []

    # Get degradation manager for circuit states
    degradation_manager = get_degradation_manager()
    degradation_status = degradation_manager.get_status()
    circuit_statuses = degradation_manager.get_circuit_statuses()

    # Check Qdrant (semantic search)
    try:
        start = time.time()
        if hasattr(request.app.state, "hybrid"):
            await request.app.state.hybrid.semantic.health_check()
        components["qdrant"] = True
        component_details.append(
            ComponentHealth(
                name="qdrant",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["qdrant"]["state"],
            ),
        )
    except Exception as e:
        components["qdrant"] = False
        component_details.append(
            ComponentHealth(
                name="qdrant",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["qdrant"]["state"],
            ),
        )

    # Check OpenSearch (keyword search)
    try:
        start = time.time()
        if hasattr(request.app.state, "hybrid"):
            await request.app.state.hybrid.keyword.health_check()
        components["opensearch"] = True
        component_details.append(
            ComponentHealth(
                name="opensearch",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["opensearch"]["state"],
            ),
        )
    except Exception as e:
        components["opensearch"] = False
        component_details.append(
            ComponentHealth(
                name="opensearch",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["opensearch"]["state"],
            ),
        )

    # Check Reranker (LLM Gateway)
    try:
        start = time.time()
        if hasattr(request.app.state, "reranker"):
            await request.app.state.reranker.health_check()
        components["reranker"] = True
        component_details.append(
            ComponentHealth(
                name="reranker",
                healthy=True,
                latency_ms=(time.time() - start) * 1000,
                circuit_state=circuit_statuses["reranker"]["state"],
            ),
        )
    except Exception as e:
        components["reranker"] = False
        component_details.append(
            ComponentHealth(
                name="reranker",
                healthy=False,
                error=str(e),
                circuit_state=circuit_statuses["reranker"]["state"],
            ),
        )

    # Determine overall status based on degradation mode
    mode = degradation_status.mode
    if mode == DegradationMode.HYBRID_FULL:
        status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    elif mode == DegradationMode.MINIMAL:
        status = "unhealthy"
    else:
        status = "degraded"

    # Capabilities based on circuit states
    capabilities = {
        "semantic_search": degradation_status.qdrant_healthy,
        "keyword_search": degradation_status.opensearch_healthy,
        "reranking": degradation_status.reranker_healthy,
        "hybrid_search": (
            degradation_status.qdrant_healthy and degradation_status.opensearch_healthy
        ),
    }

    return HealthResponse(
        status=status,
        version=VERSION,
        components=components,
        component_details=component_details,
        degradation_level=mode.value,
        capabilities=capabilities,
        timestamp=datetime.now(tz=UTC),
    )


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """
    Kubernetes liveness probe.

    Returns 200 if the service process is running.
    Used to detect if the container needs to be restarted.
    """
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(request: Request) -> dict[str, str | None]:
    """
    Kubernetes readiness probe.

    Returns 200 if the service is ready to accept requests.
    Checks if at least one search backend is available based on
    degradation mode.

    Raises:
        HTTPException: 503 if service is not ready
    """
    degradation_manager = get_degradation_manager()
    mode = degradation_manager.get_current_mode()

    # Ready if at least one search backend is available
    ready = mode != DegradationMode.MINIMAL

    if not ready:
        raise HTTPException(
            status_code=503,
            detail="Service not ready: all search backends unavailable",
        )

    return {
        "status": "ready",
        "degradation_mode": mode.value,
    }
