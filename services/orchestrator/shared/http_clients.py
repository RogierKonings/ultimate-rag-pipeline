"""Shared HTTP client factories for the Orchestrator Service.

This module provides lifecycle-managed httpx.AsyncClient instances
for communication with downstream services (retrieval, LLM gateway).

Clients are configured with centralized timeout, retry, and header
policies. They are initialized once at application startup and closed
at shutdown, enabling connection pooling across requests.

Usage in workflow nodes::

    from shared.http_clients import get_retrieval_client, get_llm_client

    client = get_retrieval_client()
    response = await client.post(...)
"""

from __future__ import annotations

import httpx
import structlog
from orchestrator.config.timeouts import (
    HTTP_CONNECTION_TIMEOUT,
    ORCHESTRATOR_LLM_TIMEOUT,
    ORCHESTRATOR_RETRIEVAL_TIMEOUT,
)

from config import get_config

logger = structlog.get_logger(__name__)

# Module-level client singletons
_retrieval_client: httpx.AsyncClient | None = None
_llm_client: httpx.AsyncClient | None = None


def _build_timeout(
    *,
    total_seconds: float,
    connect_seconds: float | None = None,
) -> httpx.Timeout:
    """Build an httpx.Timeout with separate connect and total limits.

    Args:
        total_seconds: Overall request timeout in seconds.
        connect_seconds: TCP connect timeout in seconds.
            Defaults to the centralized HTTP_CONNECTION_TIMEOUT.

    Returns:
        Configured httpx.Timeout instance.
    """
    if connect_seconds is None:
        connect_seconds = HTTP_CONNECTION_TIMEOUT.timeout_seconds

    return httpx.Timeout(
        timeout=total_seconds,
        connect=connect_seconds,
    )


def _create_retrieval_client() -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for the retrieval service.

    The client uses:
    - Connection pooling (max 20 connections, max 5 keepalive)
    - Retrieval-specific timeout from centralized config
    - Separate connect timeout from HTTP_CONNECTION_TIMEOUT
    """
    config = get_config()

    timeout = _build_timeout(
        total_seconds=ORCHESTRATOR_RETRIEVAL_TIMEOUT.timeout_seconds,
    )

    limits = httpx.Limits(
        max_connections=20,
        max_keepalive_connections=5,
        keepalive_expiry=30.0,
    )

    return httpx.AsyncClient(
        base_url=config.retrieval_url,
        timeout=timeout,
        limits=limits,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "orchestrator-service/1.0",
        },
    )


def _create_llm_client() -> httpx.AsyncClient:
    """Create an httpx.AsyncClient configured for the LLM gateway.

    The client uses:
    - Connection pooling (max 10 connections, max 5 keepalive)
    - LLM-specific timeout from centralized config
    - Separate connect timeout from HTTP_CONNECTION_TIMEOUT
    """
    config = get_config()

    timeout = _build_timeout(
        total_seconds=ORCHESTRATOR_LLM_TIMEOUT.timeout_seconds,
    )

    limits = httpx.Limits(
        max_connections=10,
        max_keepalive_connections=5,
        keepalive_expiry=30.0,
    )

    return httpx.AsyncClient(
        base_url=config.llm_gateway_url,
        timeout=timeout,
        limits=limits,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "orchestrator-service/1.0",
        },
    )


async def init_http_clients() -> None:
    """Initialize shared HTTP clients.

    Call this during application startup (lifespan). Creates the
    retrieval and LLM gateway clients with their respective
    timeout and connection pool configurations.
    """
    global _retrieval_client, _llm_client  # noqa: PLW0603

    _retrieval_client = _create_retrieval_client()
    _llm_client = _create_llm_client()

    logger.info(
        "Shared HTTP clients initialized",
        retrieval_timeout=ORCHESTRATOR_RETRIEVAL_TIMEOUT.timeout_seconds,
        llm_timeout=ORCHESTRATOR_LLM_TIMEOUT.timeout_seconds,
        connect_timeout=HTTP_CONNECTION_TIMEOUT.timeout_seconds,
    )


async def close_http_clients() -> None:
    """Close shared HTTP clients and release connection pools.

    Call this during application shutdown (lifespan). Ensures all
    connections are properly closed to avoid resource leaks.
    """
    global _retrieval_client, _llm_client  # noqa: PLW0603

    if _retrieval_client is not None:
        await _retrieval_client.aclose()
        _retrieval_client = None
        logger.info("Retrieval HTTP client closed")

    if _llm_client is not None:
        await _llm_client.aclose()
        _llm_client = None
        logger.info("LLM HTTP client closed")


def get_retrieval_client() -> httpx.AsyncClient:
    """Get the shared retrieval service HTTP client.

    Returns:
        The lifecycle-managed httpx.AsyncClient for the retrieval service.

    Raises:
        RuntimeError: If clients have not been initialized via init_http_clients().
    """
    if _retrieval_client is None:
        raise RuntimeError(
            "Retrieval HTTP client not initialized. "
            "Call init_http_clients() during application startup."
        )
    return _retrieval_client


def get_llm_client() -> httpx.AsyncClient:
    """Get the shared LLM gateway HTTP client.

    Returns:
        The lifecycle-managed httpx.AsyncClient for the LLM gateway.

    Raises:
        RuntimeError: If clients have not been initialized via init_http_clients().
    """
    if _llm_client is None:
        raise RuntimeError(
            "LLM HTTP client not initialized. Call init_http_clients() during application startup."
        )
    return _llm_client
