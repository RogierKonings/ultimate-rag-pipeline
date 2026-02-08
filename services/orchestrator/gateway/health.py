"""Health check logic for the Model Gateway.

This module handles health checking of configured LLM model endpoints.
"""

import time

import httpx
import structlog

from .models import GatewayConfig, HealthStatus

logger = structlog.get_logger(__name__)


async def check_model_health(
    client: httpx.AsyncClient,
    gateway_config: GatewayConfig,
    gateway_base_url: str,
) -> dict[str, HealthStatus]:
    """Check health of all configured model endpoints.

    Tries multiple health endpoints per model (vLLM-style and Ollama-style)
    and returns the status for each.

    Args:
        client: The HTTP client to use.
        gateway_config: The gateway configuration with model definitions.
        gateway_base_url: The base URL of the gateway (without /v1 suffix).

    Returns:
        Dictionary mapping model names to their health status.
    """
    results: dict[str, HealthStatus] = {}

    for model_name, model_config in gateway_config.models.items():
        try:
            start_time = time.perf_counter()

            # Try multiple health endpoints (vLLM uses /v1/health, Ollama uses /)
            health_endpoints = [
                f"{model_config.base_url}/health",  # vLLM style
                gateway_base_url,  # Ollama root endpoint
            ]

            response = None
            for endpoint in health_endpoints:
                try:
                    response = await client.get(endpoint, timeout=5.0)
                    if response.is_success:
                        break
                except Exception as e:
                    logger.debug("Health check failed for endpoint %s: %s", endpoint, e)
                    continue

            latency_ms = (time.perf_counter() - start_time) * 1000

            if response is not None and response.is_success:
                results[model_name] = HealthStatus(
                    status="healthy",
                    latency_ms=latency_ms,
                )
            else:
                status_code = response.status_code if response else "N/A"
                results[model_name] = HealthStatus(
                    status="unhealthy",
                    latency_ms=latency_ms,
                    message=f"HTTP {status_code}",
                )
        except httpx.TimeoutException:
            results[model_name] = HealthStatus(
                status="error",
                message="Health check timed out",
            )
        except Exception as e:
            results[model_name] = HealthStatus(
                status="error",
                message=str(e),
            )

    return results
