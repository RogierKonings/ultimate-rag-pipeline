"""
Centralized URL configuration for RAG pipeline services.

This module provides a single source of truth for all service URLs across
different deployment environments (local, docker, kubernetes).

Usage:
    from shared.config.urls import (
        get_postgres_url,
        get_qdrant_url,
        get_opensearch_url,
        get_redis_url,
        get_minio_url,
        get_embedding_service_url,
        get_llm_gateway_url,
        get_reranker_service_url,
        get_ingestion_service_url,
        get_retrieval_service_url,
        get_orchestrator_service_url,
        get_otel_endpoint,
    )

Environment Detection:
    Set DEPLOY_ENV to control which URL profile is used:
    - "local" (default): Uses localhost with standard ports
    - "docker": Uses Docker service names
    - "kubernetes": Uses Kubernetes service DNS names

Override Behavior:
    Individual URLs can still be overridden via specific environment variables.
    The getter functions check for explicit env vars first, then fall back to
    the environment-based defaults.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache


class DeployEnv(str, Enum):
    """Deployment environment types."""

    LOCAL = "local"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"


# =============================================================================
# Port Configuration (consistent across all environments)
# =============================================================================

PORTS = {
    "postgres": 5432,
    "qdrant_http": 6333,
    "qdrant_grpc": 6334,
    "opensearch": 9200,
    "opensearch_perf": 9600,
    "redis": 6379,
    "minio_api": 9000,
    "minio_console": 9001,
    "embedding_service": 8080,
    "reranker_service": 8081,
    "llm_gateway": 8004,
    "ollama": 11434,
    "ingestion_service": 8001,
    "retrieval_service": 8002,
    "orchestrator_service": 8003,
    "otel_collector": 4317,
    "jaeger": 16686,
    "prometheus": 9090,
    "grafana": 3000,
    "loki": 3100,
    "phoenix": 6006,
    "vault": 8200,
    "opensearch_dashboards": 5601,
}

# =============================================================================
# Host Mappings Per Environment
# =============================================================================

HOSTS: dict[str, dict[str, str]] = {
    DeployEnv.LOCAL: {
        "postgres": "localhost",
        "qdrant": "localhost",
        "opensearch": "localhost",
        "redis": "localhost",
        "minio": "localhost",
        "embedding_service": "localhost",
        "reranker_service": "localhost",
        "llm_gateway": "localhost",
        "ollama": "localhost",
        "ingestion_service": "localhost",
        "retrieval_service": "localhost",
        "orchestrator_service": "localhost",
        "otel_collector": "localhost",
        "jaeger": "localhost",
        "prometheus": "localhost",
        "grafana": "localhost",
        "loki": "localhost",
        "phoenix": "localhost",
        "vault": "localhost",
        "opensearch_dashboards": "localhost",
    },
    DeployEnv.DOCKER: {
        "postgres": "postgres",
        "qdrant": "qdrant",
        "opensearch": "opensearch",
        "redis": "redis",
        "minio": "minio",
        "embedding_service": "embedding-service",
        "reranker_service": "reranker-service",
        "llm_gateway": "host.docker.internal",  # Ollama runs natively on host
        "ollama": "host.docker.internal",
        "ingestion_service": "ingestion-service",
        "retrieval_service": "retrieval-service",
        "orchestrator_service": "orchestrator-service",
        "otel_collector": "otel-collector",
        "jaeger": "jaeger",
        "prometheus": "prometheus",
        "grafana": "grafana",
        "loki": "loki",
        "phoenix": "phoenix",
        "vault": "vault",
        "opensearch_dashboards": "opensearch-dashboards",
    },
    DeployEnv.KUBERNETES: {
        "postgres": "postgres.rag-pipeline.svc.cluster.local",
        "qdrant": "qdrant.rag-pipeline.svc.cluster.local",
        "opensearch": "opensearch.rag-pipeline.svc.cluster.local",
        "redis": "redis.rag-pipeline.svc.cluster.local",
        "minio": "minio.rag-pipeline.svc.cluster.local",
        "embedding_service": "embedding-service.rag-pipeline.svc.cluster.local",
        "reranker_service": "reranker-service.rag-pipeline.svc.cluster.local",
        "llm_gateway": "llm-gateway.rag-pipeline.svc.cluster.local",
        "ollama": "llm-gateway.rag-pipeline.svc.cluster.local",
        "ingestion_service": "ingestion-service.rag-pipeline.svc.cluster.local",
        "retrieval_service": "retrieval-service.rag-pipeline.svc.cluster.local",
        "orchestrator_service": "orchestrator-service.rag-pipeline.svc.cluster.local",
        "otel_collector": "otel-collector.rag-pipeline.svc.cluster.local",
        "jaeger": "jaeger.rag-pipeline.svc.cluster.local",
        "prometheus": "prometheus.rag-pipeline.svc.cluster.local",
        "grafana": "grafana.rag-pipeline.svc.cluster.local",
        "loki": "loki.rag-pipeline.svc.cluster.local",
        "phoenix": "phoenix.rag-pipeline.svc.cluster.local",
        "vault": "vault.rag-pipeline.svc.cluster.local",
        "opensearch_dashboards": "opensearch-dashboards.rag-pipeline.svc.cluster.local",
    },
}


# =============================================================================
# Environment Detection
# =============================================================================


@lru_cache(maxsize=1)
def get_deploy_env() -> DeployEnv:
    """
    Get the current deployment environment.

    Checks DEPLOY_ENV environment variable. Defaults to 'local' if not set.

    Returns:
        DeployEnv: The current deployment environment.
    """
    env_value = os.getenv("DEPLOY_ENV", "local").lower()
    try:
        return DeployEnv(env_value)
    except ValueError:
        # Fall back to local if invalid value
        return DeployEnv.LOCAL


def _get_host(service: str) -> str:
    """Get the host for a service based on current deployment environment."""
    deploy_env = get_deploy_env()
    return HOSTS[deploy_env][service]


def _get_port(port_name: str) -> int:
    """Get a port number by name."""
    return PORTS[port_name]


# =============================================================================
# Database URLs
# =============================================================================


def get_postgres_url(
    *,
    async_driver: bool = True,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> str:
    """
    Get PostgreSQL connection URL.

    Args:
        async_driver: Use asyncpg driver (True) or psycopg2 (False).
        user: Override username (default: from POSTGRES_USER or 'raguser').
        password: Override password (default: from POSTGRES_PASSWORD or 'ragpass').
        database: Override database name (default: from POSTGRES_DB or 'ragpipeline').

    Returns:
        PostgreSQL connection URL.
    """
    # Check for explicit override first
    if async_driver:
        explicit = os.getenv("DATABASE_URL")
    else:
        explicit = os.getenv("DATABASE_URL_SYNC")

    if explicit:
        return explicit

    # Build from components
    _user = user or os.getenv("POSTGRES_USER", "raguser")
    _password = password or os.getenv("POSTGRES_PASSWORD", "ragpass")
    _database = database or os.getenv("POSTGRES_DB", "ragpipeline")
    host = os.getenv("POSTGRES_HOST") or _get_host("postgres")
    port = int(os.getenv("POSTGRES_PORT", _get_port("postgres")))

    driver = "postgresql+asyncpg" if async_driver else "postgresql"
    return f"{driver}://{_user}:{_password}@{host}:{port}/{_database}"


def get_redis_url(*, db: int = 2, include_password: bool = True) -> str:
    """
    Get Redis connection URL.

    Args:
        db: Redis database number (default: 2 for app caches).
        include_password: Include password in URL.

    Returns:
        Redis connection URL.
    """
    explicit = os.getenv("REDIS_URL")
    if explicit:
        return explicit

    host = os.getenv("REDIS_HOST") or _get_host("redis")
    port = int(os.getenv("REDIS_PORT", _get_port("redis")))
    password = os.getenv("REDIS_PASSWORD", "ragredis")

    if include_password and password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def get_celery_broker_url() -> str:
    """Get Celery broker URL (Redis db 0)."""
    explicit = os.getenv("CELERY_BROKER_URL")
    if explicit:
        return explicit
    return get_redis_url(db=0)


def get_celery_result_backend() -> str:
    """Get Celery result backend URL (Redis db 1)."""
    explicit = os.getenv("CELERY_RESULT_BACKEND")
    if explicit:
        return explicit
    return get_redis_url(db=1)


# =============================================================================
# Vector Store & Search URLs
# =============================================================================


def get_qdrant_url() -> str:
    """Get Qdrant HTTP API URL."""
    explicit = os.getenv("QDRANT_URL")
    if explicit:
        return explicit

    host = _get_host("qdrant")
    port = _get_port("qdrant_http")
    return f"http://{host}:{port}"


def get_qdrant_grpc_url() -> str:
    """Get Qdrant gRPC URL."""
    explicit = os.getenv("QDRANT_GRPC_URL")
    if explicit:
        return explicit

    host = _get_host("qdrant")
    port = _get_port("qdrant_grpc")
    return f"{host}:{port}"


def get_opensearch_url() -> str:
    """Get OpenSearch URL."""
    explicit = os.getenv("OPENSEARCH_URL")
    if explicit:
        return explicit

    host = _get_host("opensearch")
    port = _get_port("opensearch")
    return f"http://{host}:{port}"


# =============================================================================
# Object Storage URLs
# =============================================================================


def get_minio_url() -> str:
    """Get MinIO API URL."""
    explicit = os.getenv("MINIO_URL") or os.getenv("MINIO_ENDPOINT")
    if explicit:
        # Normalize: add http:// if not present, handle endpoint without protocol
        if not explicit.startswith(("http://", "https://")):
            return f"http://{explicit}"
        return explicit

    host = _get_host("minio")
    port = _get_port("minio_api")
    return f"http://{host}:{port}"


def get_minio_endpoint() -> str:
    """Get MinIO endpoint (host:port without protocol)."""
    explicit = os.getenv("MINIO_ENDPOINT")
    if explicit:
        # Remove protocol if present
        if explicit.startswith("http://"):
            return explicit[7:]
        if explicit.startswith("https://"):
            return explicit[8:]
        return explicit

    host = _get_host("minio")
    port = _get_port("minio_api")
    return f"{host}:{port}"


# =============================================================================
# ML Service URLs
# =============================================================================


def get_embedding_service_url() -> str:
    """Get embedding service URL."""
    explicit = os.getenv("EMBEDDING_SERVICE_URL")
    if explicit:
        return explicit

    host = _get_host("embedding_service")
    port = _get_port("embedding_service")
    return f"http://{host}:{port}"


def get_reranker_service_url() -> str:
    """Get reranker service URL."""
    explicit = os.getenv("RERANKER_SERVICE_URL")
    if explicit:
        return explicit

    host = _get_host("reranker_service")
    port = _get_port("reranker_service")
    return f"http://{host}:{port}"


def get_llm_gateway_url() -> str:
    """
    Get LLM gateway URL.

    In Docker environment, this points to host.docker.internal to reach
    native Ollama running on the host (for Metal GPU acceleration).
    """
    explicit = os.getenv("LLM_GATEWAY_URL") or os.getenv("LLM_SERVICE_URL")
    if explicit:
        return explicit

    deploy_env = get_deploy_env()
    host = _get_host("llm_gateway")

    # In Docker, Ollama runs natively so use Ollama port
    if deploy_env == DeployEnv.DOCKER:
        port = _get_port("ollama")
    else:
        port = _get_port("llm_gateway")

    return f"http://{host}:{port}"


def get_ollama_url() -> str:
    """Get Ollama URL (alias for LLM gateway in most cases)."""
    explicit = os.getenv("OLLAMA_URL")
    if explicit:
        return explicit

    host = _get_host("ollama")
    port = _get_port("ollama")
    return f"http://{host}:{port}"


# =============================================================================
# Application Service URLs
# =============================================================================


def get_ingestion_service_url() -> str:
    """Get ingestion service URL."""
    explicit = os.getenv("INGESTION_SERVICE_URL")
    if explicit:
        return explicit

    host = _get_host("ingestion_service")
    port = _get_port("ingestion_service")
    return f"http://{host}:{port}"


def get_retrieval_service_url() -> str:
    """Get retrieval service URL."""
    explicit = os.getenv("RETRIEVAL_SERVICE_URL")
    if explicit:
        return explicit

    host = _get_host("retrieval_service")
    port = _get_port("retrieval_service")
    return f"http://{host}:{port}"


def get_orchestrator_service_url() -> str:
    """Get orchestrator service URL."""
    explicit = os.getenv("ORCHESTRATOR_SERVICE_URL")
    if explicit:
        return explicit

    host = _get_host("orchestrator_service")
    port = _get_port("orchestrator_service")
    return f"http://{host}:{port}"


# =============================================================================
# Observability URLs
# =============================================================================


def get_otel_endpoint() -> str:
    """Get OpenTelemetry collector endpoint."""
    explicit = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if explicit:
        return explicit

    host = _get_host("otel_collector")
    port = _get_port("otel_collector")
    return f"http://{host}:{port}"


def get_jaeger_url() -> str:
    """Get Jaeger UI URL."""
    explicit = os.getenv("JAEGER_URL")
    if explicit:
        return explicit

    host = _get_host("jaeger")
    port = _get_port("jaeger")
    return f"http://{host}:{port}"


def get_prometheus_url() -> str:
    """Get Prometheus URL."""
    explicit = os.getenv("PROMETHEUS_URL")
    if explicit:
        return explicit

    host = _get_host("prometheus")
    port = _get_port("prometheus")
    return f"http://{host}:{port}"


def get_grafana_url() -> str:
    """Get Grafana URL."""
    explicit = os.getenv("GRAFANA_URL")
    if explicit:
        return explicit

    host = _get_host("grafana")
    port = _get_port("grafana")
    return f"http://{host}:{port}"


def get_loki_url() -> str:
    """Get Loki URL."""
    explicit = os.getenv("LOKI_URL")
    if explicit:
        return explicit

    host = _get_host("loki")
    port = _get_port("loki")
    return f"http://{host}:{port}"


def get_phoenix_url() -> str:
    """Get Phoenix (Arize) URL."""
    explicit = os.getenv("PHOENIX_URL")
    if explicit:
        return explicit

    host = _get_host("phoenix")
    port = _get_port("phoenix")
    return f"http://{host}:{port}"


# =============================================================================
# Security URLs
# =============================================================================


def get_vault_url() -> str:
    """Get HashiCorp Vault URL."""
    explicit = os.getenv("VAULT_ADDR")
    if explicit:
        return explicit

    host = _get_host("vault")
    port = _get_port("vault")
    return f"http://{host}:{port}"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Environment
    "DeployEnv",
    "get_deploy_env",
    "PORTS",
    "HOSTS",
    # Database
    "get_postgres_url",
    "get_redis_url",
    "get_celery_broker_url",
    "get_celery_result_backend",
    # Vector Store & Search
    "get_qdrant_url",
    "get_qdrant_grpc_url",
    "get_opensearch_url",
    # Object Storage
    "get_minio_url",
    "get_minio_endpoint",
    # ML Services
    "get_embedding_service_url",
    "get_reranker_service_url",
    "get_llm_gateway_url",
    "get_ollama_url",
    # Application Services
    "get_ingestion_service_url",
    "get_retrieval_service_url",
    "get_orchestrator_service_url",
    # Observability
    "get_otel_endpoint",
    "get_jaeger_url",
    "get_prometheus_url",
    "get_grafana_url",
    "get_loki_url",
    "get_phoenix_url",
    # Security
    "get_vault_url",
]
