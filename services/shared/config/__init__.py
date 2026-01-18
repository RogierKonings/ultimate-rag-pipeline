"""
Shared configuration module for RAG pipeline services.

This module provides centralized configuration for timeouts, retries, and other
cross-cutting concerns across all services.

Usage:
    from shared.config import (
        TimeoutConfig,
        RETRIEVAL_EMBEDDING_TIMEOUT,
        get_timeout,
        get_timeout_seconds,
    )
"""

from shared.config.timeouts import (
    # Core class
    TimeoutConfig,
    # Retrieval service timeouts
    RETRIEVAL_EMBEDDING_TIMEOUT,
    RETRIEVAL_QDRANT_TIMEOUT,
    RETRIEVAL_OPENSEARCH_TIMEOUT,
    RETRIEVAL_RERANKER_TIMEOUT,
    RETRIEVAL_TOTAL_TIMEOUT,
    # Orchestrator service timeouts
    ORCHESTRATOR_RETRIEVAL_TIMEOUT,
    ORCHESTRATOR_LLM_TIMEOUT,
    ORCHESTRATOR_TOTAL_TIMEOUT,
    # Ingestion service timeouts
    INGESTION_PARSING_TIMEOUT,
    INGESTION_EMBEDDING_TIMEOUT,
    INGESTION_QDRANT_UPSERT_TIMEOUT,
    INGESTION_OPENSEARCH_INDEX_TIMEOUT,
    INGESTION_DOCUMENT_TIMEOUT,
    # Infrastructure timeouts
    REDIS_OPERATION_TIMEOUT,
    POSTGRES_QUERY_TIMEOUT,
    HTTP_CONNECTION_TIMEOUT,
    # Registry and helpers
    ALL_TIMEOUTS,
    get_timeout,
    get_timeout_seconds,
    get_timeout_ms,
)

__all__ = [
    # Core class
    "TimeoutConfig",
    # Retrieval service timeouts
    "RETRIEVAL_EMBEDDING_TIMEOUT",
    "RETRIEVAL_QDRANT_TIMEOUT",
    "RETRIEVAL_OPENSEARCH_TIMEOUT",
    "RETRIEVAL_RERANKER_TIMEOUT",
    "RETRIEVAL_TOTAL_TIMEOUT",
    # Orchestrator service timeouts
    "ORCHESTRATOR_RETRIEVAL_TIMEOUT",
    "ORCHESTRATOR_LLM_TIMEOUT",
    "ORCHESTRATOR_TOTAL_TIMEOUT",
    # Ingestion service timeouts
    "INGESTION_PARSING_TIMEOUT",
    "INGESTION_EMBEDDING_TIMEOUT",
    "INGESTION_QDRANT_UPSERT_TIMEOUT",
    "INGESTION_OPENSEARCH_INDEX_TIMEOUT",
    "INGESTION_DOCUMENT_TIMEOUT",
    # Infrastructure timeouts
    "REDIS_OPERATION_TIMEOUT",
    "POSTGRES_QUERY_TIMEOUT",
    "HTTP_CONNECTION_TIMEOUT",
    # Registry and helpers
    "ALL_TIMEOUTS",
    "get_timeout",
    "get_timeout_seconds",
    "get_timeout_ms",
]
