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
from shared.observability.correlation import CorrelationMiddleware

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

    # Initialize usage tracker and flusher (US-10.5.4)
    app.state.usage_tracker = None
    app.state.usage_flusher = None
    app.state.usage_scheduler = None

    try:
        from database.connection import get_session_factory
        from usage import UsageFlusher, UsageFlusherConfig, UsageTracker, UsageTrackerConfig

        usage_tracker_config = UsageTrackerConfig(
            redis_url=config.redis_url,
            key_prefix="usage",
        )
        session_factory = get_session_factory()
        usage_tracker = UsageTracker(usage_tracker_config, session_factory)
        await usage_tracker.connect()
        app.state.usage_tracker = usage_tracker
        logger.info("Usage tracker initialized")

        # Initialize usage flusher with scheduler
        flusher_config = UsageFlusherConfig(
            redis_url=config.redis_url,
            key_prefix="usage",
            flush_interval_seconds=300,  # 5 minutes
        )
        usage_flusher = UsageFlusher(flusher_config, session_factory)
        await usage_flusher.connect()
        app.state.usage_flusher = usage_flusher

        # Set up APScheduler for periodic flush
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            usage_flusher.flush,
            "interval",
            seconds=flusher_config.flush_interval_seconds,
            id="usage_flush",
            name="Flush usage counters to PostgreSQL",
        )
        scheduler.start()
        app.state.usage_scheduler = scheduler
        logger.info("Usage flusher and scheduler initialized (5 min interval)")

    except Exception as e:
        logger.warning(f"Failed to initialize usage tracking: {e}")

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

    # Shutdown usage scheduler and flush remaining data (US-10.5.4)
    if app.state.usage_scheduler is not None:
        try:
            app.state.usage_scheduler.shutdown(wait=False)
            logger.info("Usage scheduler stopped")
        except Exception as e:
            logger.warning(f"Error stopping usage scheduler: {e}")

    # Final flush before shutdown
    if app.state.usage_flusher is not None:
        try:
            flushed = await app.state.usage_flusher.flush()
            logger.info(f"Final usage flush completed: {flushed} records")
            await app.state.usage_flusher.disconnect()
            logger.info("Usage flusher disconnected")
        except Exception as e:
            logger.warning(f"Error during final usage flush: {e}")

    if app.state.usage_tracker is not None:
        try:
            await app.state.usage_tracker.disconnect()
            logger.info("Usage tracker disconnected")
        except Exception as e:
            logger.warning(f"Error closing usage tracker: {e}")

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

    # Correlation ID middleware for distributed tracing (US-10.3.1)
    # Replaces inline log_requests with more comprehensive correlation handling
    app.add_middleware(
        CorrelationMiddleware,
        service_name="orchestrator-service",
    )

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
    from api.routes import admin_router, health_router, query_router, sessions_router

    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(sessions_router)
    app.include_router(admin_router)  # Usage tracking (US-10.5.4)

    return app
