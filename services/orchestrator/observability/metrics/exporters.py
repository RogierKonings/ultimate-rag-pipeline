"""
Prometheus Metrics Exporters.

Provides the /metrics endpoint for Prometheus scraping with:
- Standard Prometheus format output
- Multiprocess mode support for gunicorn
- FastAPI route setup helpers
"""

import os

import structlog
from fastapi import APIRouter, FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)

logger = structlog.get_logger(__name__)

# Router for metrics endpoint
metrics_router = APIRouter(tags=["monitoring"])


def get_metrics_output(registry: CollectorRegistry | None = None) -> tuple[bytes, str]:
    """
    Generate Prometheus metrics output.

    Args:
        registry: Custom registry (uses default if None)

    Returns:
        Tuple of (metrics bytes, content type)
    """
    if registry is None:
        # Check for multiprocess mode
        prometheus_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if prometheus_dir:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
        else:
            registry = REGISTRY

    return generate_latest(registry), CONTENT_TYPE_LATEST


@metrics_router.get(
    "/metrics",
    summary="Prometheus Metrics",
    description="Returns Prometheus-formatted metrics for scraping",
    response_class=Response,
)
async def metrics_endpoint() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus exposition format.
    """
    metrics_output, content_type = get_metrics_output()
    return Response(
        content=metrics_output,
        media_type=content_type,
    )


def setup_metrics_endpoint(
    app: FastAPI,
    path: str = "/metrics",
    include_in_schema: bool = False,
) -> None:
    """
    Setup metrics endpoint on a FastAPI app.

    Args:
        app: FastAPI application
        path: Path for metrics endpoint
        include_in_schema: Whether to include in OpenAPI schema
    """

    @app.get(
        path,
        include_in_schema=include_in_schema,
        tags=["monitoring"],
    )
    async def _metrics() -> Response:
        metrics_output, content_type = get_metrics_output()
        return Response(
            content=metrics_output,
            media_type=content_type,
        )

    logger.info(f"Metrics endpoint configured at {path}")


def get_metrics_endpoint():
    """
    Get the metrics router for inclusion in FastAPI app.

    Usage:
        from orchestrator.observability.metrics import get_metrics_endpoint
        app.include_router(get_metrics_endpoint())
    """
    return metrics_router


class MetricsExporter:
    """
    Helper class for managing metrics export.

    Provides methods for generating metrics in various formats
    and handling multiprocess scenarios.
    """

    def __init__(self, registry: CollectorRegistry | None = None):
        """
        Initialize the exporter.

        Args:
            registry: Custom registry (auto-detects multiprocess mode if None)
        """
        self.registry = registry
        self._multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")

    def get_registry(self) -> CollectorRegistry:
        """
        Get the appropriate registry.

        Returns:
            CollectorRegistry for generating metrics
        """
        if self.registry is not None:
            return self.registry

        if self._multiprocess_dir:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            return registry

        return REGISTRY

    def generate(self) -> bytes:
        """
        Generate metrics output.

        Returns:
            Prometheus-formatted metrics as bytes
        """
        return generate_latest(self.get_registry())

    def content_type(self) -> str:
        """
        Get the content type for metrics output.

        Returns:
            Content type string
        """
        return CONTENT_TYPE_LATEST

    def is_multiprocess(self) -> bool:
        """
        Check if running in multiprocess mode.

        Returns:
            True if multiprocess mode is enabled
        """
        return self._multiprocess_dir is not None
