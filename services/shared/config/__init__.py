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
        validate_on_startup,
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
from shared.config.validation import (
    ConfigurationError,
    validate_on_startup,
    validate_timeout_cascade,
)
from shared.config.defaults import (
    # Configuration classes
    ChunkingConfig,
    EmbeddingConfig,
    RetrievalConfig,
    # Factory functions
    get_chunking_config,
    get_embedding_config,
    get_retrieval_config,
    # Validation
    validate_all_configs,
)
from shared.config.urls import (
    # Environment
    DeployEnv,
    get_deploy_env,
    PORTS,
    HOSTS,
    # Database
    get_postgres_url,
    get_redis_url,
    get_celery_broker_url,
    get_celery_result_backend,
    # Vector Store & Search
    get_qdrant_url,
    get_qdrant_grpc_url,
    get_opensearch_url,
    # Object Storage
    get_minio_url,
    get_minio_endpoint,
    # ML Services
    get_embedding_service_url,
    get_reranker_service_url,
    get_llm_gateway_url,
    get_ollama_url,
    # Application Services
    get_ingestion_service_url,
    get_retrieval_service_url,
    get_orchestrator_service_url,
    # Observability
    get_otel_endpoint,
    get_jaeger_url,
    get_prometheus_url,
    get_grafana_url,
    get_loki_url,
    get_phoenix_url,
    # Security
    get_vault_url,
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
    # Validation
    "ConfigurationError",
    "validate_timeout_cascade",
    "validate_on_startup",
    # Shared defaults (US-10.6.2)
    "ChunkingConfig",
    "EmbeddingConfig",
    "RetrievalConfig",
    "get_chunking_config",
    "get_embedding_config",
    "get_retrieval_config",
    "validate_all_configs",
    # URL configuration
    "DeployEnv",
    "get_deploy_env",
    "PORTS",
    "HOSTS",
    "get_postgres_url",
    "get_redis_url",
    "get_celery_broker_url",
    "get_celery_result_backend",
    "get_qdrant_url",
    "get_qdrant_grpc_url",
    "get_opensearch_url",
    "get_minio_url",
    "get_minio_endpoint",
    "get_embedding_service_url",
    "get_reranker_service_url",
    "get_llm_gateway_url",
    "get_ollama_url",
    "get_ingestion_service_url",
    "get_retrieval_service_url",
    "get_orchestrator_service_url",
    "get_otel_endpoint",
    "get_jaeger_url",
    "get_prometheus_url",
    "get_grafana_url",
    "get_loki_url",
    "get_phoenix_url",
    "get_vault_url",
]
