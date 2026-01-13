"""Configuration for the Retrieval Service."""

from pydantic import Field
from pydantic_settings import BaseSettings


class RetrievalConfig(BaseSettings):
    """Retrieval service configuration."""

    # Service
    service_name: str = "retrieval-service"
    service_port: int = 8002
    debug: bool = False

    # Qdrant (Semantic Search)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "documents"

    # OpenSearch (Keyword Search)
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "documents"

    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"

    # Embedding settings
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768
    embedding_prefix: str = ""  # nomic-embed-text doesn't need prefix

    # Default Search Weights
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)

    # Default Reranking
    rerank_enabled: bool = True
    rerank_top_k: int = 20

    # JWT
    jwt_secret: str = "dev-secret-key"  # noqa: S105
    jwt_algorithm: str = "HS256"

    # Cache
    redis_url: str = "redis://localhost:6379"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # Timeouts
    search_timeout_seconds: float = 30.0
    rerank_timeout_seconds: float = 30.0

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Metrics
    metrics_enabled: bool = True
    metrics_port: int = 9090

    model_config = {
        "env_prefix": "RETRIEVAL_",
        "env_file": ".env",
        "extra": "ignore",
    }
