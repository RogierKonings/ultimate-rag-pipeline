"""FastAPI application factory for the Orchestrator Service.

This module provides the application factory with:
- Lifespan handler for startup/shutdown
- CORS middleware configuration
- Request logging middleware
- Router registration
"""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shared.config import validate_on_startup

from config import OrchestratorConfig, get_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events.

    This handler:
    - On startup: Initializes all services (session manager, model gateway, etc.)
    - On shutdown: Gracefully closes all connections

    Args:
        app: The FastAPI application instance.

    Yields:
        None during the application lifecycle.
    """
    # Validate timeout configuration at startup
    validate_on_startup(fail_fast=True)

    config = get_config()
    logger.info(f"Starting {config.service_name}...")

    # Record start time for uptime calculation
    app.state.start_time = time.time()

    # Initialize services
    try:
        # Initialize Redis session store and manager
        from memory import MemoryConfig, RedisSessionStore, SessionManager

        memory_config = MemoryConfig(
            redis_url=config.redis_url,
            session_ttl=config.session_ttl,
            max_messages=config.max_history_length,
        )
        session_store = RedisSessionStore(memory_config)
        await session_store.connect()
        app.state.session_manager = SessionManager(session_store, memory_config)
        logger.info("Session manager initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize session manager: {e}")
        app.state.session_manager = None

    try:
        # Initialize model gateway
        from gateway import ModelGateway

        app.state.model_gateway = ModelGateway(config)
        logger.info("Model gateway initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize model gateway: {e}")
        app.state.model_gateway = None

    try:
        # Initialize guardrail pipeline
        from guardrails import GuardrailConfig, GuardrailPipeline

        guardrail_config = GuardrailConfig(
            max_input_length=config.max_input_length,
        )
        app.state.guardrail_pipeline = GuardrailPipeline(guardrail_config)
        logger.info("Guardrail pipeline initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize guardrail pipeline: {e}")
        app.state.guardrail_pipeline = None

    try:
        # Initialize stream manager
        from streaming import StreamManager

        app.state.stream_manager = StreamManager(gateway=app.state.model_gateway)
        logger.info("Stream manager initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize stream manager: {e}")
        app.state.stream_manager = None

    # Initialize RAG workflow
    try:
        from workflow import build_rag_workflow

        app.state.workflow = build_rag_workflow()
        logger.info("RAG workflow initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize RAG workflow: {e}")
        app.state.workflow = None

    app.state.retrieval_client = None

    logger.info(f"{config.service_name} started successfully")

    yield

    # Shutdown
    logger.info(f"Shutting down {config.service_name}...")

    # Close model gateway
    if app.state.model_gateway is not None:
        try:
            await app.state.model_gateway.close()
            logger.info("Model gateway closed")
        except Exception as e:
            logger.warning(f"Error closing model gateway: {e}")

    # Close session store
    if app.state.session_manager is not None:
        try:
            await app.state.session_manager.store.disconnect()
            logger.info("Session store disconnected")
        except Exception as e:
            logger.warning(f"Error closing session store: {e}")

    logger.info(f"{config.service_name} shutdown complete")


def create_app(config: OrchestratorConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional configuration. Uses default if not provided.

    Returns:
        Configured FastAPI application instance.
    """
    if config is None:
        config = get_config()

    app = FastAPI(
        title="Orchestrator Service",
        description="RAG orchestration service with LangGraph workflows",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all incoming requests with timing information."""
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", "")

        # Log request
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log response
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"status={response.status_code} duration={duration_ms:.2f}ms",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

            # Add request ID to response headers
            if request_id:
                response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"error={str(e)} duration={duration_ms:.2f}ms",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "duration_ms": duration_ms,
                },
                exc_info=True,
            )
            raise

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle uncaught exceptions."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "timestamp": time.time(),
            },
        )

    # Register routers
    from api.routes import health_router, query_router, sessions_router

    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(sessions_router)

    return app
