"""
Timeout configuration for the orchestrator service.

This module provides timeout constants that can be overridden via environment variables.
The Rust services (ingestion, retrieval) have their own timeout configuration in rag-config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class TimeoutConfig:
    """Configuration for a single timeout."""

    name: str
    timeout_ms: int
    retries: int
    env_var: str
    idempotent: bool = True
    backoff_base_ms: int = 100
    backoff_max_ms: int = 5000

    @property
    def timeout_seconds(self) -> float:
        """Return timeout in seconds."""
        return self.timeout_ms / 1000.0


def _get_timeout_ms(env_var: str, default: int) -> int:
    """Get timeout from environment variable or use default."""
    return int(os.getenv(env_var, str(default)))


# Orchestrator service timeouts
ORCHESTRATOR_RETRIEVAL_TIMEOUT = TimeoutConfig(
    name="ORCHESTRATOR_RETRIEVAL",
    timeout_ms=_get_timeout_ms("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", 20000),
    retries=1,
    env_var="ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS",
)

ORCHESTRATOR_LLM_TIMEOUT = TimeoutConfig(
    name="ORCHESTRATOR_LLM",
    timeout_ms=_get_timeout_ms("ORCHESTRATOR_LLM_TIMEOUT_MS", 25000),
    retries=0,
    env_var="ORCHESTRATOR_LLM_TIMEOUT_MS",
    idempotent=False,  # LLM generation is not idempotent
)

ORCHESTRATOR_TOTAL_TIMEOUT = TimeoutConfig(
    name="ORCHESTRATOR_TOTAL",
    timeout_ms=_get_timeout_ms("ORCHESTRATOR_TOTAL_TIMEOUT_MS", 30000),
    retries=0,
    env_var="ORCHESTRATOR_TOTAL_TIMEOUT_MS",
)

# Retrieval service timeouts (for validation cascade checks)
RETRIEVAL_EMBEDDING_TIMEOUT = TimeoutConfig(
    name="RETRIEVAL_EMBEDDING",
    timeout_ms=_get_timeout_ms("RETRIEVAL_EMBEDDING_TIMEOUT_MS", 5000),
    retries=2,
    env_var="RETRIEVAL_EMBEDDING_TIMEOUT_MS",
)

RETRIEVAL_QDRANT_TIMEOUT = TimeoutConfig(
    name="RETRIEVAL_QDRANT",
    timeout_ms=_get_timeout_ms("RETRIEVAL_QDRANT_TIMEOUT_MS", 3000),
    retries=1,
    env_var="RETRIEVAL_QDRANT_TIMEOUT_MS",
)

RETRIEVAL_OPENSEARCH_TIMEOUT = TimeoutConfig(
    name="RETRIEVAL_OPENSEARCH",
    timeout_ms=_get_timeout_ms("RETRIEVAL_OPENSEARCH_TIMEOUT_MS", 3000),
    retries=1,
    env_var="RETRIEVAL_OPENSEARCH_TIMEOUT_MS",
)

RETRIEVAL_RERANKER_TIMEOUT = TimeoutConfig(
    name="RETRIEVAL_RERANKER",
    timeout_ms=_get_timeout_ms("RETRIEVAL_RERANKER_TIMEOUT_MS", 8000),
    retries=1,
    env_var="RETRIEVAL_RERANKER_TIMEOUT_MS",
)

RETRIEVAL_TOTAL_TIMEOUT = TimeoutConfig(
    name="RETRIEVAL_TOTAL",
    timeout_ms=_get_timeout_ms("RETRIEVAL_TOTAL_TIMEOUT_MS", 15000),
    retries=0,
    env_var="RETRIEVAL_TOTAL_TIMEOUT_MS",
)

# Ingestion service timeouts (for validation cascade checks)
INGESTION_PARSING_TIMEOUT = TimeoutConfig(
    name="INGESTION_PARSING",
    timeout_ms=_get_timeout_ms("INGESTION_PARSING_TIMEOUT_MS", 60000),
    retries=0,
    env_var="INGESTION_PARSING_TIMEOUT_MS",
)

INGESTION_EMBEDDING_TIMEOUT = TimeoutConfig(
    name="INGESTION_EMBEDDING",
    timeout_ms=_get_timeout_ms("INGESTION_EMBEDDING_TIMEOUT_MS", 30000),
    retries=2,
    env_var="INGESTION_EMBEDDING_TIMEOUT_MS",
)

INGESTION_QDRANT_UPSERT_TIMEOUT = TimeoutConfig(
    name="INGESTION_QDRANT_UPSERT",
    timeout_ms=_get_timeout_ms("INGESTION_QDRANT_UPSERT_TIMEOUT_MS", 10000),
    retries=2,
    env_var="INGESTION_QDRANT_UPSERT_TIMEOUT_MS",
)

INGESTION_OPENSEARCH_INDEX_TIMEOUT = TimeoutConfig(
    name="INGESTION_OPENSEARCH_INDEX",
    timeout_ms=_get_timeout_ms("INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS", 10000),
    retries=2,
    env_var="INGESTION_OPENSEARCH_INDEX_TIMEOUT_MS",
)

INGESTION_DOCUMENT_TIMEOUT = TimeoutConfig(
    name="INGESTION_DOCUMENT",
    timeout_ms=_get_timeout_ms("INGESTION_DOCUMENT_TIMEOUT_MS", 300000),
    retries=3,
    env_var="INGESTION_DOCUMENT_TIMEOUT_MS",
)

# Infrastructure timeouts
REDIS_OPERATION_TIMEOUT = TimeoutConfig(
    name="REDIS_OPERATION",
    timeout_ms=_get_timeout_ms("REDIS_OPERATION_TIMEOUT_MS", 1000),
    retries=1,
    env_var="REDIS_OPERATION_TIMEOUT_MS",
)

POSTGRES_QUERY_TIMEOUT = TimeoutConfig(
    name="POSTGRES_QUERY",
    timeout_ms=_get_timeout_ms("POSTGRES_QUERY_TIMEOUT_MS", 5000),
    retries=0,
    env_var="POSTGRES_QUERY_TIMEOUT_MS",
)

HTTP_CONNECTION_TIMEOUT = TimeoutConfig(
    name="HTTP_CONNECTION",
    timeout_ms=_get_timeout_ms("HTTP_CONNECTION_TIMEOUT_MS", 5000),
    retries=0,
    env_var="HTTP_CONNECTION_TIMEOUT_MS",
)

# Registry of all timeouts for validation
ALL_TIMEOUTS: Dict[str, TimeoutConfig] = {
    "RETRIEVAL_EMBEDDING": RETRIEVAL_EMBEDDING_TIMEOUT,
    "RETRIEVAL_QDRANT": RETRIEVAL_QDRANT_TIMEOUT,
    "RETRIEVAL_OPENSEARCH": RETRIEVAL_OPENSEARCH_TIMEOUT,
    "RETRIEVAL_RERANKER": RETRIEVAL_RERANKER_TIMEOUT,
    "RETRIEVAL_TOTAL": RETRIEVAL_TOTAL_TIMEOUT,
    "ORCHESTRATOR_RETRIEVAL": ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    "ORCHESTRATOR_LLM": ORCHESTRATOR_LLM_TIMEOUT,
    "ORCHESTRATOR_TOTAL": ORCHESTRATOR_TOTAL_TIMEOUT,
    "INGESTION_PARSING": INGESTION_PARSING_TIMEOUT,
    "INGESTION_EMBEDDING": INGESTION_EMBEDDING_TIMEOUT,
    "INGESTION_QDRANT_UPSERT": INGESTION_QDRANT_UPSERT_TIMEOUT,
    "INGESTION_OPENSEARCH_INDEX": INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    "INGESTION_DOCUMENT": INGESTION_DOCUMENT_TIMEOUT,
    "REDIS_OPERATION": REDIS_OPERATION_TIMEOUT,
    "POSTGRES_QUERY": POSTGRES_QUERY_TIMEOUT,
    "HTTP_CONNECTION": HTTP_CONNECTION_TIMEOUT,
}


def get_timeout(name: str) -> TimeoutConfig:
    """Get a timeout configuration by name."""
    if name not in ALL_TIMEOUTS:
        raise KeyError(f"Unknown timeout: {name}")
    return ALL_TIMEOUTS[name]


def get_timeout_ms(name: str) -> int:
    """Get timeout value in milliseconds."""
    return get_timeout(name).timeout_ms


def get_timeout_seconds(name: str) -> float:
    """Get timeout value in seconds."""
    return get_timeout(name).timeout_seconds
