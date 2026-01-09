"""API module for the Orchestrator Service.

This module provides:
- FastAPI application factory
- Request/Response models
- Route handlers
- Dependency injection
"""

from .app import create_app
from .dependencies import (
    ConfigDep,
    GuardrailPipelineDep,
    ModelGatewayDep,
    SessionManagerDep,
    StartTimeDep,
    StreamManagerDep,
    get_config_dep,
    get_guardrail_pipeline,
    get_model_gateway,
    get_session_manager,
    get_start_time,
    get_stream_manager,
)
from .models import (
    ClearSessionResponse,
    ComponentHealth,
    CreateSessionRequest,
    DeleteSessionResponse,
    ErrorDetail,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    HistoryResponse,
    MessageInfo,
    QueryRequest,
    QueryResponse,
    SessionInfo,
    SessionResponse,
    SourceDocument,
    StreamQueryRequest,
    UsageInfo,
)
from .routes import health_router, query_router, sessions_router

__all__ = [
    # Application
    "create_app",
    # Dependencies
    "get_config_dep",
    "get_session_manager",
    "get_model_gateway",
    "get_guardrail_pipeline",
    "get_stream_manager",
    "get_start_time",
    "ConfigDep",
    "SessionManagerDep",
    "ModelGatewayDep",
    "GuardrailPipelineDep",
    "StreamManagerDep",
    "StartTimeDep",
    # Request models
    "QueryRequest",
    "StreamQueryRequest",
    "FeedbackRequest",
    "CreateSessionRequest",
    # Response models
    "QueryResponse",
    "SessionResponse",
    "SessionInfo",
    "HistoryResponse",
    "MessageInfo",
    "HealthResponse",
    "ComponentHealth",
    "ErrorResponse",
    "ErrorDetail",
    "SourceDocument",
    "UsageInfo",
    "FeedbackResponse",
    "ClearSessionResponse",
    "DeleteSessionResponse",
    # Routers
    "health_router",
    "query_router",
    "sessions_router",
]
