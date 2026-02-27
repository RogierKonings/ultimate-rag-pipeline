"""Health check endpoints for the Orchestrator Service.

This module provides health check endpoints for:
- Detailed health status (GET /health)
- Kubernetes liveness probe (GET /health/live)
- Kubernetes readiness probe (GET /health/ready)
"""

import time
from datetime import UTC, datetime

from api.models.responses import ComponentHealth, HealthResponse
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Detailed health check",
    description="Returns detailed health status including all component checks.",
)
async def health_check(request: Request) -> HealthResponse:
    """Perform detailed health check of all components.

    This endpoint checks:
    - Session manager (Redis connectivity)
    - Model gateway (LLM backend connectivity)
    - Overall service status

    Returns:
        HealthResponse with component-level health details.
    """
    components: list[ComponentHealth] = []
    overall_healthy = True
    start_time = getattr(request.app.state, "start_time", time.time())
    uptime = time.time() - start_time

    # Check session manager / Redis
    session_manager = getattr(request.app.state, "session_manager", None)
    if session_manager is not None:
        try:
            redis_start = time.perf_counter()
            # Try to ping Redis through the session store
            if hasattr(session_manager, "store") and hasattr(
                session_manager.store,
                "_redis",
            ):
                await session_manager.store._redis.ping()
            redis_latency = (time.perf_counter() - redis_start) * 1000
            components.append(
                ComponentHealth(
                    name="redis",
                    status="healthy",
                    latency_ms=round(redis_latency, 2),
                    message="Connected",
                ),
            )
        except Exception as e:
            overall_healthy = False
            components.append(
                ComponentHealth(
                    name="redis",
                    status="unhealthy",
                    message=str(e),
                ),
            )
    else:
        components.append(
            ComponentHealth(
                name="redis",
                status="unknown",
                message="Session manager not initialized",
            ),
        )

    # Check model gateway
    model_gateway = getattr(request.app.state, "model_gateway", None)
    if model_gateway is not None:
        try:
            gateway_start = time.perf_counter()
            health_result = await model_gateway.health_check()
            gateway_latency = (time.perf_counter() - gateway_start) * 1000

            # Check if any model is healthy
            gateway_healthy = any(m.status == "healthy" for m in health_result.values())
            components.append(
                ComponentHealth(
                    name="llm_gateway",
                    status="healthy" if gateway_healthy else "degraded",
                    latency_ms=round(gateway_latency, 2),
                    message=f"Models: {list(health_result.keys())}",
                ),
            )
            if not gateway_healthy:
                overall_healthy = False
        except Exception as e:
            overall_healthy = False
            components.append(
                ComponentHealth(
                    name="llm_gateway",
                    status="unhealthy",
                    message=str(e),
                ),
            )
    else:
        components.append(
            ComponentHealth(
                name="llm_gateway",
                status="unknown",
                message="Model gateway not initialized",
            ),
        )

    # Check cache invalidation listener
    cache_invalidation_listener = getattr(
        request.app.state, "cache_invalidation_listener", None
    )
    if cache_invalidation_listener is not None:
        listener_running = cache_invalidation_listener.is_running
        components.append(
            ComponentHealth(
                name="cache_invalidation_listener",
                status="healthy" if listener_running else "degraded",
                message="Listening" if listener_running else "Task not running",
            ),
        )
        if not listener_running:
            overall_healthy = False

    # Determine overall status
    if overall_healthy:
        overall_status = "healthy"
    elif any(c.status == "healthy" for c in components):
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        service="orchestrator-service",
        version="1.0.0",
        uptime_seconds=round(uptime, 2),
        components=components,
        timestamp=datetime.now(tz=UTC),
    )


@router.get(
    "/health/live",
    summary="Liveness probe",
    description="Returns 200 if the service is running. Used by Kubernetes.",
    responses={
        200: {"description": "Service is alive"},
    },
)
async def liveness_probe() -> JSONResponse:
    """Kubernetes liveness probe.

    This is a lightweight check that only verifies the service is running
    and able to respond to requests. It does not check dependencies.

    Returns:
        Simple JSON response indicating the service is alive.
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "alive"},
    )


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Returns 200 if the service is ready to receive traffic.",
    responses={
        200: {"description": "Service is ready"},
        503: {"description": "Service is not ready"},
    },
)
async def readiness_probe(request: Request) -> JSONResponse:
    """Kubernetes readiness probe.

    This check verifies that critical dependencies are available
    and the service can handle requests.

    Returns:
        200 if ready, 503 if not ready.
    """
    # Check if essential components are initialized
    session_manager = getattr(request.app.state, "session_manager", None)
    model_gateway = getattr(request.app.state, "model_gateway", None)

    ready = True
    reasons = []

    if session_manager is None:
        ready = False
        reasons.append("Session manager not initialized")
    else:
        # Try to ping Redis
        try:
            if hasattr(session_manager, "store") and hasattr(
                session_manager.store,
                "_redis",
            ):
                await session_manager.store._redis.ping()
        except Exception as e:
            ready = False
            reasons.append(f"Redis not available: {e}")

    if model_gateway is None:
        ready = False
        reasons.append("Model gateway not initialized")

    if ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready"},
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "not_ready", "reasons": reasons},
    )
