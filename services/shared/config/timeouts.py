"""
Centralized timeout and retry configuration for all RAG pipeline services.

This module provides standardized timeout values with environment variable overrides,
enabling consistent timeout policies across the entire system.

Cascade hierarchy (outer -> inner):
  RAG E2E (30000ms)
    ├── Retrieval Total (15000ms)
    │   ├── Embedding Request (5000ms)
    │   ├── Qdrant Query (3000ms)
    │   ├── OpenSearch Query (3000ms)
    │   └── Reranker Batch (8000ms)
    └── LLM Generation (25000ms)

  Ingestion Document (300000ms = 5min)
    ├── Parsing (60000ms)
    ├── Embedding Batch (30000ms)
    ├── Qdrant Upsert (10000ms)
    └── OpenSearch Index (10000ms)

Environment variable pattern: {SERVICE}_{OPERATION}_TIMEOUT_MS
Example: RETRIEVAL_EMBEDDING_TIMEOUT_MS=6000

Usage:
    from shared.config.timeouts import (
        RETRIEVAL_EMBEDDING_TIMEOUT,
        get_timeout,
        get_timeout_seconds,
    )

    # Access timeout config directly
    timeout_ms = RETRIEVAL_EMBEDDING_TIMEOUT.timeout_ms
    retries = RETRIEVAL_EMBEDDING_TIMEOUT.retries

    # Or use helper functions
    config = get_timeout("RETRIEVAL_EMBEDDING")
    timeout_secs = get_timeout_seconds("RETRIEVAL_EMBEDDING")
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class TimeoutConfig:
    """
    Configuration for timeout and retry behavior.

    Attributes:
        timeout_ms: Timeout value in milliseconds
        retries: Number of retry attempts (0 = no retries)
        backoff_base_ms: Base delay for exponential backoff in milliseconds
        backoff_max_ms: Maximum backoff delay in milliseconds
        idempotent: Whether the operation is idempotent (safe to retry)
    """

    timeout_ms: int
    retries: int
    backoff_base_ms: int = 100
    backoff_max_ms: int = 5000
    idempotent: bool = True

    @property
    def timeout_seconds(self) -> float:
        """Return timeout value in seconds."""
        return self.timeout_ms / 1000.0

    @property
    def backoff_base_seconds(self) -> float:
        """Return backoff base delay in seconds."""
        return self.backoff_base_ms / 1000.0

    @property
    def backoff_max_seconds(self) -> float:
        """Return maximum backoff delay in seconds."""
        return self.backoff_max_ms / 1000.0


def _get_env_int(name: str, default: int) -> int:
    """Get an integer value from environment variable with fallback to default."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    """Get a boolean value from environment variable with fallback to default."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def _create_timeout_config(
    env_prefix: str,
    default_timeout_ms: int,
    default_retries: int,
    default_backoff_base_ms: int = 100,
    default_backoff_max_ms: int = 5000,
    default_idempotent: bool = True,
) -> TimeoutConfig:
    """
    Create a TimeoutConfig with environment variable overrides.

    Environment variables checked:
        - {env_prefix}_TIMEOUT_MS: Timeout in milliseconds
        - {env_prefix}_RETRIES: Number of retries
        - {env_prefix}_BACKOFF_BASE_MS: Base backoff delay
        - {env_prefix}_BACKOFF_MAX_MS: Maximum backoff delay
        - {env_prefix}_IDEMPOTENT: Whether operation is idempotent
    """
    return TimeoutConfig(
        timeout_ms=_get_env_int(f"{env_prefix}_TIMEOUT_MS", default_timeout_ms),
        retries=_get_env_int(f"{env_prefix}_RETRIES", default_retries),
        backoff_base_ms=_get_env_int(
            f"{env_prefix}_BACKOFF_BASE_MS", default_backoff_base_ms
        ),
        backoff_max_ms=_get_env_int(
            f"{env_prefix}_BACKOFF_MAX_MS", default_backoff_max_ms
        ),
        idempotent=_get_env_bool(f"{env_prefix}_IDEMPOTENT", default_idempotent),
    )


# =============================================================================
# Retrieval Service Timeouts
# =============================================================================

RETRIEVAL_EMBEDDING_TIMEOUT = _create_timeout_config(
    env_prefix="RETRIEVAL_EMBEDDING",
    default_timeout_ms=5000,
    default_retries=2,
)
"""Timeout for embedding generation requests during retrieval (5s, 2 retries)."""

RETRIEVAL_QDRANT_TIMEOUT = _create_timeout_config(
    env_prefix="RETRIEVAL_QDRANT",
    default_timeout_ms=3000,
    default_retries=1,
)
"""Timeout for Qdrant vector search queries (3s, 1 retry)."""

RETRIEVAL_OPENSEARCH_TIMEOUT = _create_timeout_config(
    env_prefix="RETRIEVAL_OPENSEARCH",
    default_timeout_ms=3000,
    default_retries=1,
)
"""Timeout for OpenSearch keyword search queries (3s, 1 retry)."""

RETRIEVAL_RERANKER_TIMEOUT = _create_timeout_config(
    env_prefix="RETRIEVAL_RERANKER",
    default_timeout_ms=8000,
    default_retries=1,
)
"""Timeout for reranker batch processing (8s, 1 retry)."""

RETRIEVAL_TOTAL_TIMEOUT = _create_timeout_config(
    env_prefix="RETRIEVAL_TOTAL",
    default_timeout_ms=15000,
    default_retries=0,
)
"""Total timeout for retrieval pipeline (15s, no retries)."""


# =============================================================================
# Orchestrator Service Timeouts
# =============================================================================

ORCHESTRATOR_RETRIEVAL_TIMEOUT = _create_timeout_config(
    env_prefix="ORCHESTRATOR_RETRIEVAL",
    default_timeout_ms=20000,
    default_retries=1,
)
"""Timeout for orchestrator calling retrieval service (20s, 1 retry)."""

ORCHESTRATOR_LLM_TIMEOUT = _create_timeout_config(
    env_prefix="ORCHESTRATOR_LLM",
    default_timeout_ms=25000,
    default_retries=0,
    default_idempotent=False,
)
"""Timeout for LLM generation requests (25s, no retries, not idempotent)."""

ORCHESTRATOR_TOTAL_TIMEOUT = _create_timeout_config(
    env_prefix="ORCHESTRATOR_TOTAL",
    default_timeout_ms=30000,
    default_retries=0,
    default_idempotent=False,
)
"""Total timeout for RAG end-to-end request (30s, no retries)."""


# =============================================================================
# Ingestion Service Timeouts
# =============================================================================

INGESTION_PARSING_TIMEOUT = _create_timeout_config(
    env_prefix="INGESTION_PARSING",
    default_timeout_ms=60000,
    default_retries=0,
)
"""Timeout for document parsing operations (60s, no retries)."""

INGESTION_EMBEDDING_TIMEOUT = _create_timeout_config(
    env_prefix="INGESTION_EMBEDDING",
    default_timeout_ms=30000,
    default_retries=2,
)
"""Timeout for embedding batch during ingestion (30s, 2 retries)."""

INGESTION_QDRANT_UPSERT_TIMEOUT = _create_timeout_config(
    env_prefix="INGESTION_QDRANT_UPSERT",
    default_timeout_ms=10000,
    default_retries=2,
)
"""Timeout for Qdrant upsert operations (10s, 2 retries)."""

INGESTION_OPENSEARCH_INDEX_TIMEOUT = _create_timeout_config(
    env_prefix="INGESTION_OPENSEARCH_INDEX",
    default_timeout_ms=10000,
    default_retries=2,
)
"""Timeout for OpenSearch indexing operations (10s, 2 retries)."""

INGESTION_DOCUMENT_TIMEOUT = _create_timeout_config(
    env_prefix="INGESTION_DOCUMENT",
    default_timeout_ms=300000,  # 5 minutes
    default_retries=3,
)
"""Total timeout for document ingestion (5 min, 3 retries)."""


# =============================================================================
# Infrastructure Timeouts
# =============================================================================

REDIS_OPERATION_TIMEOUT = _create_timeout_config(
    env_prefix="REDIS_OPERATION",
    default_timeout_ms=1000,
    default_retries=1,
)
"""Timeout for Redis cache operations (1s, 1 retry)."""

POSTGRES_QUERY_TIMEOUT = _create_timeout_config(
    env_prefix="POSTGRES_QUERY",
    default_timeout_ms=5000,
    default_retries=1,
)
"""Timeout for PostgreSQL queries (5s, 1 retry)."""

HTTP_CONNECTION_TIMEOUT = _create_timeout_config(
    env_prefix="HTTP_CONNECTION",
    default_timeout_ms=5000,
    default_retries=0,
)
"""Timeout for HTTP connection establishment (5s, no retries)."""


# =============================================================================
# Timeout Registry
# =============================================================================

ALL_TIMEOUTS: Dict[str, TimeoutConfig] = {
    # Retrieval
    "RETRIEVAL_EMBEDDING": RETRIEVAL_EMBEDDING_TIMEOUT,
    "RETRIEVAL_QDRANT": RETRIEVAL_QDRANT_TIMEOUT,
    "RETRIEVAL_OPENSEARCH": RETRIEVAL_OPENSEARCH_TIMEOUT,
    "RETRIEVAL_RERANKER": RETRIEVAL_RERANKER_TIMEOUT,
    "RETRIEVAL_TOTAL": RETRIEVAL_TOTAL_TIMEOUT,
    # Orchestrator
    "ORCHESTRATOR_RETRIEVAL": ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    "ORCHESTRATOR_LLM": ORCHESTRATOR_LLM_TIMEOUT,
    "ORCHESTRATOR_TOTAL": ORCHESTRATOR_TOTAL_TIMEOUT,
    # Ingestion
    "INGESTION_PARSING": INGESTION_PARSING_TIMEOUT,
    "INGESTION_EMBEDDING": INGESTION_EMBEDDING_TIMEOUT,
    "INGESTION_QDRANT_UPSERT": INGESTION_QDRANT_UPSERT_TIMEOUT,
    "INGESTION_OPENSEARCH_INDEX": INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    "INGESTION_DOCUMENT": INGESTION_DOCUMENT_TIMEOUT,
    # Infrastructure
    "REDIS_OPERATION": REDIS_OPERATION_TIMEOUT,
    "POSTGRES_QUERY": POSTGRES_QUERY_TIMEOUT,
    "HTTP_CONNECTION": HTTP_CONNECTION_TIMEOUT,
}
"""Registry of all timeout configurations indexed by name."""


def get_timeout(name: str) -> TimeoutConfig:
    """
    Get a timeout configuration by name.

    Args:
        name: The timeout name (e.g., "RETRIEVAL_EMBEDDING")

    Returns:
        The TimeoutConfig for the specified timeout

    Raises:
        KeyError: If the timeout name is not found

    Example:
        >>> config = get_timeout("RETRIEVAL_EMBEDDING")
        >>> print(config.timeout_ms)
        5000
    """
    if name not in ALL_TIMEOUTS:
        raise KeyError(
            f"Unknown timeout: {name}. "
            f"Available timeouts: {', '.join(sorted(ALL_TIMEOUTS.keys()))}"
        )
    return ALL_TIMEOUTS[name]


def get_timeout_seconds(name: str) -> float:
    """
    Get a timeout value in seconds by name.

    Args:
        name: The timeout name (e.g., "RETRIEVAL_EMBEDDING")

    Returns:
        The timeout value in seconds

    Raises:
        KeyError: If the timeout name is not found

    Example:
        >>> timeout = get_timeout_seconds("RETRIEVAL_EMBEDDING")
        >>> print(timeout)
        5.0
    """
    return get_timeout(name).timeout_seconds


def get_timeout_ms(name: str) -> int:
    """
    Get a timeout value in milliseconds by name.

    Args:
        name: The timeout name (e.g., "RETRIEVAL_EMBEDDING")

    Returns:
        The timeout value in milliseconds

    Raises:
        KeyError: If the timeout name is not found

    Example:
        >>> timeout = get_timeout_ms("RETRIEVAL_EMBEDDING")
        >>> print(timeout)
        5000
    """
    return get_timeout(name).timeout_ms
