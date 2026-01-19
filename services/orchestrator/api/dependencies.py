"""Dependency injection for the Orchestrator API.

This module provides FastAPI dependency injection functions for
accessing shared services throughout the application.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from gateway import ModelGateway
from guardrails import GuardrailPipeline
from memory import SessionManager
from streaming import StreamManager
from usage import UsageTracker

from config import OrchestratorConfig, get_config


def get_config_dep() -> OrchestratorConfig:
    """Get the application configuration.

    Returns:
        OrchestratorConfig instance.
    """
    return get_config()


ConfigDep = Annotated[OrchestratorConfig, Depends(get_config_dep)]


def get_session_manager(request: Request) -> SessionManager:
    """Get the session manager from application state.

    Args:
        request: The incoming request with app state.

    Returns:
        SessionManager instance.

    Raises:
        HTTPException: If session manager is not available.
    """
    session_manager = getattr(request.app.state, "session_manager", None)
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session manager not available",
        )
    return session_manager


SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]


def get_model_gateway(request: Request) -> ModelGateway:
    """Get the model gateway from application state.

    Args:
        request: The incoming request with app state.

    Returns:
        ModelGateway instance.

    Raises:
        HTTPException: If model gateway is not available.
    """
    model_gateway = getattr(request.app.state, "model_gateway", None)
    if model_gateway is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model gateway not available",
        )
    return model_gateway


ModelGatewayDep = Annotated[ModelGateway, Depends(get_model_gateway)]


def get_guardrail_pipeline(request: Request) -> GuardrailPipeline:
    """Get the guardrail pipeline from application state.

    Args:
        request: The incoming request with app state.

    Returns:
        GuardrailPipeline instance.

    Raises:
        HTTPException: If guardrail pipeline is not available.
    """
    guardrail_pipeline = getattr(request.app.state, "guardrail_pipeline", None)
    if guardrail_pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Guardrail pipeline not available",
        )
    return guardrail_pipeline


GuardrailPipelineDep = Annotated[GuardrailPipeline, Depends(get_guardrail_pipeline)]


def get_stream_manager(request: Request) -> StreamManager:
    """Get the stream manager from application state.

    Args:
        request: The incoming request with app state.

    Returns:
        StreamManager instance.

    Raises:
        HTTPException: If stream manager is not available.
    """
    stream_manager = getattr(request.app.state, "stream_manager", None)
    if stream_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stream manager not available",
        )
    return stream_manager


StreamManagerDep = Annotated[StreamManager, Depends(get_stream_manager)]


def get_start_time(request: Request) -> float:
    """Get the application start time for uptime calculation.

    Args:
        request: The incoming request with app state.

    Returns:
        Start time as Unix timestamp.
    """
    return getattr(request.app.state, "start_time", 0.0)


StartTimeDep = Annotated[float, Depends(get_start_time)]


def get_usage_tracker(request: Request) -> UsageTracker | None:
    """Get the usage tracker from application state.

    Args:
        request: The incoming request with app state.

    Returns:
        UsageTracker instance or None if not configured.
    """
    return getattr(request.app.state, "usage_tracker", None)


UsageTrackerDep = Annotated[UsageTracker | None, Depends(get_usage_tracker)]
