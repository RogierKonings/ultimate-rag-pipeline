"""
Configuration API FastAPI application.

Provides REST API for managing model configuration, A/B tests,
and configuration versioning.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

from ..manager import ConfigurationManager
from .routes import router, set_config_manager

logger = logging.getLogger(__name__)

# Prometheus metrics
CONFIG_CHANGES = Counter(
    "config_changes_total",
    "Total configuration changes",
    ["change_type"],
)

ROUTING_DECISIONS = Counter(
    "routing_decisions_total",
    "Total routing decisions",
    ["model_type", "selected_model", "ab_test"],
)

CONFIG_LOAD_TIME = Histogram(
    "config_load_seconds",
    "Time to load configuration",
)

# Global config manager
_config_manager: ConfigurationManager | None = None


def get_config_manager() -> ConfigurationManager | None:
    """Get the global configuration manager."""
    return _config_manager


def init_config_manager(
    config_path: Path | None = None,
    watch_interval: float = 5.0,
) -> ConfigurationManager:
    """
    Initialize the global configuration manager.

    Args:
        config_path: Path to YAML configuration file
        watch_interval: Interval for file watching

    Returns:
        Initialized ConfigurationManager
    """
    global _config_manager
    _config_manager = ConfigurationManager(
        config_path=config_path,
        watch_interval=watch_interval,
    )
    set_config_manager(_config_manager)
    return _config_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    if _config_manager and _config_manager.config_path:
        try:
            await _config_manager.load_from_file(_config_manager.config_path)
            await _config_manager.start_watching()
            logger.info("Configuration loaded and watching started")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")

    yield

    # Shutdown
    if _config_manager:
        await _config_manager.stop_watching()
        logger.info("Configuration watching stopped")


# Create FastAPI application
app = FastAPI(
    title="Model Configuration API",
    description="API for managing LLM serving model configuration",
    version="1.0.0",
    lifespan=lifespan,
)

# Include routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "config_loaded": _config_manager is not None,
        "version": (
            _config_manager.get_state().current_version if _config_manager else None
        ),
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type="text/plain")


# Convenience function for standalone running
def create_app(
    config_path: str | None = None,
    watch_interval: float = 5.0,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config_path: Path to configuration file
        watch_interval: File watch interval

    Returns:
        Configured FastAPI application
    """
    path = Path(config_path) if config_path else None
    init_config_manager(config_path=path, watch_interval=watch_interval)
    return app


if __name__ == "__main__":
    import os

    import uvicorn

    config_path = os.environ.get("CONFIG_PATH", "defaults/llm.yaml")
    port = int(os.environ.get("CONFIG_API_PORT", "8010"))

    create_app(config_path=config_path)
    uvicorn.run(app, host="0.0.0.0", port=port)
