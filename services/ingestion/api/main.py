"""FastAPI application factory for the ingestion service.

This module creates and configures the FastAPI application with:
- OpenTelemetry tracing and Prometheus metrics (US-2.12)
- Structured logging with trace context
- CORS and authentication middleware
"""

import logging
from contextlib import asynccontextmanager

from api.middleware import RequestLoggingMiddleware, TenantMiddleware
from api.routes import (
    admin_router,
    documents_router,
    ingest_router,
    migrations_router,
    video_management_router,
    video_router,
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from telemetry import (
    get_current_trace_context,
    instrument_fastapi,
    setup_telemetry,
)

from config import Settings, get_settings

logger = logging.getLogger(__name__)


async def initialize_connections() -> None:
    """Initialize database and service connections on startup."""
    logger.info("Initializing service connections...")
    # Connections are initialized lazily in dependencies
    # This is a placeholder for any eager initialization


async def close_connections() -> None:
    """Close database and service connections on shutdown."""
    logger.info("Closing service connections...")
    # Connections are closed by dependency cleanup
    # This is a placeholder for any additional cleanup


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    logger.info("Starting Ingestion Service...")

    # Initialize OpenTelemetry and Prometheus (US-2.12)
    setup_telemetry()

    await initialize_connections()

    yield

    # Shutdown
    logger.info("Shutting down Ingestion Service...")
    await close_connections()


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Create and configure FastAPI application.

    Args:
        settings: Optional settings override (for testing).

    Returns:
        Configured FastAPI application with telemetry enabled.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title="RAG Pipeline Ingestion Service",
        description="Document ingestion and indexing API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware (order matters: first added = outermost)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TenantMiddleware)

    # Instrument FastAPI with OpenTelemetry (US-2.12)
    instrument_fastapi(app)

    # Include routers
    app.include_router(
        ingest_router,
        prefix="/ingest",
        tags=["Ingestion"],
    )
    app.include_router(
        documents_router,
        prefix="/documents",
        tags=["Documents"],
    )

    # Video router for Video RAG Pipeline
    app.include_router(
        video_router,
        prefix="/videos",
        tags=["Videos"],
    )

    # Video management router for CRUD operations
    app.include_router(
        video_management_router,
        prefix="/api/v1/videos",
        tags=["Video Management"],
    )

    # Migrations router is optional
    if migrations_router is not None:
        app.include_router(
            migrations_router,
            prefix="/migrations",
            tags=["Migrations"],
        )

    # Admin router for maintenance operations (US-10.1.2)
    app.include_router(
        admin_router,
        prefix="/admin",
        tags=["Admin"],
    )

    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "ingestion"}

    # Metrics endpoint (US-2.12)
    @app.get("/metrics", tags=["Observability"])
    async def metrics():
        """Prometheus metrics endpoint.

        Note: The actual Prometheus metrics are served by the prometheus_client
        HTTP server on a separate port (configured via settings.metrics_port).
        This endpoint provides basic service metrics info.
        """
        trace_context = get_current_trace_context()
        return {
            "service": "ingestion",
            "metrics_port": settings.metrics_port,
            "otel_enabled": settings.otel_enabled,
            **trace_context,
        }

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions with trace context."""
        trace_context = get_current_trace_context()
        logger.exception(
            f"Unhandled exception: {exc}",
            extra=trace_context,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                **trace_context,
            },
        )

    return app


# Create app instance
app = create_app()
