"""
Configuration module for the orchestrator service.

Provides URL helpers, default configurations, and validation utilities.
"""

from orchestrator.config.defaults import (
    ChunkingConfig,
    EmbeddingConfig,
    RetrievalConfig,
    get_chunking_config,
    get_embedding_config,
    get_retrieval_config,
    validate_all_configs,
)
from orchestrator.config.settings import (
    OrchestratorConfig,
    get_config,
)
from orchestrator.config.timeouts import (
    get_timeout,
    get_timeout_ms,
    get_timeout_seconds,
)
from orchestrator.config.urls import (
    HOSTS,
    PORTS,
    DeployEnv,
    get_celery_broker_url,
    get_celery_result_backend,
    get_deploy_env,
    get_embedding_service_url,
    get_grafana_url,
    get_ingestion_service_url,
    get_jaeger_url,
    get_llm_gateway_url,
    get_loki_url,
    get_minio_endpoint,
    get_minio_url,
    get_ollama_url,
    get_opensearch_url,
    get_orchestrator_service_url,
    get_otel_endpoint,
    get_phoenix_url,
    get_postgres_url,
    get_prometheus_url,
    get_qdrant_grpc_url,
    get_qdrant_url,
    get_redis_url,
    get_reranker_service_url,
    get_retrieval_service_url,
    get_vault_url,
)
from orchestrator.config.validation import (
    ConfigurationError,
    validate_on_startup,
    validate_timeout_cascade,
)

__all__ = [
    # Configuration classes
    "ChunkingConfig",
    "EmbeddingConfig",
    "RetrievalConfig",
    "get_chunking_config",
    "get_embedding_config",
    "get_retrieval_config",
    "validate_all_configs",
    # Service configuration
    "OrchestratorConfig",
    "get_config",
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
    # Validation
    "ConfigurationError",
    "validate_timeout_cascade",
    "validate_on_startup",
    # Timeouts
    "get_timeout",
    "get_timeout_ms",
    "get_timeout_seconds",
]
