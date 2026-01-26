"""Configuration for the Retrieval Service."""

from pydantic import Field
from pydantic_settings import BaseSettings

from shared.config import (
    get_llm_gateway_url,
    get_opensearch_url,
    get_qdrant_url,
    get_redis_url,
    get_timeout_seconds,
)


class RetrievalConfig(BaseSettings):
    """Retrieval service configuration."""

    # Service
    service_name: str = "retrieval-service"
    service_port: int = 8002
    debug: bool = False

    # Qdrant (Semantic Search, from centralized config)
    qdrant_url: str = Field(default_factory=get_qdrant_url)
    qdrant_collection: str = "documents"

    # OpenSearch (Keyword Search, from centralized config)
    opensearch_url: str = Field(default_factory=get_opensearch_url)
    opensearch_index: str = "documents"

    # LLM Gateway (from centralized config)
    llm_gateway_url: str = Field(default_factory=get_llm_gateway_url)

    # Embedding service (separate from LLM Gateway)
    embedding_service_url: str = "http://embedding-service:8080"

    # Embedding settings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_prefix: str = ""  # MiniLM doesn't use query prefix

    # Default Search Weights
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)

    # Default Reranking
    rerank_enabled: bool = True
    rerank_top_k: int = 20

    # JWT
    jwt_secret: str = "dev-secret-key"  # noqa: S105
    jwt_algorithm: str = "HS256"

    # Cache (from centralized config)
    redis_url: str = Field(default_factory=get_redis_url)
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # Timeouts (from shared config, overridable via environment)
    search_timeout_seconds: float = get_timeout_seconds("RETRIEVAL_TOTAL")
    rerank_timeout_seconds: float = get_timeout_seconds("RETRIEVAL_RERANKER")

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Metrics
    metrics_enabled: bool = True
    metrics_port: int = 9090

    # Circuit Breaker settings
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 30.0
    circuit_half_open_max_calls: int = 3

    model_config = {
        "env_prefix": "RETRIEVAL_",
        "env_file": ".env",
        "extra": "ignore",
    }
