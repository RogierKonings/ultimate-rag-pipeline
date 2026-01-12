"""Health check endpoints for the Retrieval Service."""

import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import ComponentHealth, HealthResponse

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

    **Status Values:**
    - `healthy`: All components operational
    - `degraded`: Some components down but service functional
    - `unhealthy`: Critical components down
    """
    components: dict[str, bool] = {}
    component_details: list[ComponentHealth] = []

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
            ),
        )
    except Exception as e:
        components["qdrant"] = False
        component_details.append(
            ComponentHealth(name="qdrant", healthy=False, error=str(e)),
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
            ),
        )
    except Exception as e:
        components["opensearch"] = False
        component_details.append(
            ComponentHealth(name="opensearch", healthy=False, error=str(e)),
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
            ),
        )
    except Exception as e:
        components["reranker"] = False
        component_details.append(
            ComponentHealth(name="reranker", healthy=False, error=str(e)),
        )

    # Determine overall status
    all_healthy = all(components.values())
    any_healthy = any(components.values())

    if all_healthy:
        status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    elif any_healthy:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        version=VERSION,
        components=components,
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
async def readiness(request: Request) -> dict[str, str]:
    """
    Kubernetes readiness probe.

    Returns 200 if the service is ready to accept requests.
    Checks if core search backends are connected.

    Raises:
        HTTPException: 503 if service is not ready
    """
    try:
        # Check if we can handle requests
        if hasattr(request.app.state, "hybrid"):
            await request.app.state.hybrid.semantic.health_check()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Service not ready: {e}",
        ) from e
