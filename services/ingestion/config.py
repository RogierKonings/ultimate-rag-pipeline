"""Application configuration using pydantic-settings.

This module defines validated configuration settings for the ingestion service.
Configuration values are loaded from environment variables with validation
to ensure alignment with architecture-defined defaults (US-2.12).

Architecture defaults (from docs/architecture.md):
- Embedding dimensions: 1024 (BGE-large)
- Chunking target: 300 tokens
- Chunking max: 512 tokens
- Chunking overlap: 50 tokens

Timeout configuration (US-10.2.4):
- Parsing timeout: 60 seconds
- Embedding timeout: 30 seconds
- Qdrant upsert timeout: 10 seconds
- OpenSearch index timeout: 10 seconds
- Document total timeout: 300 seconds (5 minutes)
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from shared.config import (
    get_celery_broker_url,
    get_celery_result_backend,
    get_llm_gateway_url,
    get_minio_url,
    get_opensearch_url,
    get_otel_endpoint,
    get_postgres_url,
    get_qdrant_url,
    get_redis_url,
    get_timeout_seconds,
)

# Architecture-defined constants (US-2.12)
ARCHITECTURE_EMBEDDING_DIMENSIONS = 1024
ARCHITECTURE_CHUNKING_TARGET_TOKENS = 300
ARCHITECTURE_CHUNKING_MAX_TOKENS = 512
ARCHITECTURE_CHUNKING_OVERLAP_TOKENS = 50


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All embedding and chunking defaults are validated against architecture-defined
    values per US-2.12 requirements.
    """

    # API Settings
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # CORS
    cors_origins: list[str] = ["*"]

    # JWT Authentication
    jwt_secret: str = "your-secret-key-change-in-production"  # noqa: S105
    jwt_algorithm: str = "HS256"

    # Database URLs (from centralized config)
    database_url: str = Field(default_factory=lambda: get_postgres_url(async_driver=False))
    redis_url: str = Field(default_factory=get_redis_url)
    qdrant_url: str = Field(default_factory=get_qdrant_url)
    opensearch_url: str = Field(default_factory=get_opensearch_url)
    minio_url: str = Field(default_factory=get_minio_url)

    # MinIO/S3 credentials
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"  # noqa: S105
    minio_bucket: str = "rag-documents"

    # Celery (from centralized config)
    celery_broker_url: str = Field(default_factory=get_celery_broker_url)
    celery_result_backend: str = Field(default_factory=get_celery_result_backend)

    # LLM Gateway (from centralized config)
    llm_gateway_url: str = Field(default_factory=get_llm_gateway_url)

    # Embedding configuration (architecture defaults, US-2.12)
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dimensions: int = ARCHITECTURE_EMBEDDING_DIMENSIONS

    # Chunking configuration (architecture defaults, US-2.12)
    chunking_target_tokens: int = ARCHITECTURE_CHUNKING_TARGET_TOKENS
    chunking_max_tokens: int = ARCHITECTURE_CHUNKING_MAX_TOKENS
    chunking_overlap_tokens: int = ARCHITECTURE_CHUNKING_OVERLAP_TOKENS

    # OpenTelemetry configuration (US-2.12, from centralized config)
    otel_enabled: bool = True
    otel_service_name: str = "ingestion-service"
    otel_exporter_otlp_endpoint: str = Field(default_factory=get_otel_endpoint)

    # Prometheus metrics (US-2.12)
    metrics_enabled: bool = True
    metrics_port: int = 9090

    # Rate limiting configuration (US-10.2.3)
    rate_limit_default_max_concurrent: int = 10
    rate_limit_enabled: bool = True

    # Timeout configuration (US-10.2.4) - uses shared config defaults
    # These can be overridden via environment variables (INGESTION_{OPERATION}_TIMEOUT_MS)
    parsing_timeout_seconds: float = get_timeout_seconds("INGESTION_PARSING")
    embedding_timeout_seconds: float = get_timeout_seconds("INGESTION_EMBEDDING")
    qdrant_upsert_timeout_seconds: float = get_timeout_seconds("INGESTION_QDRANT_UPSERT")
    opensearch_index_timeout_seconds: float = get_timeout_seconds("INGESTION_OPENSEARCH_INDEX")
    document_timeout_seconds: float = get_timeout_seconds("INGESTION_DOCUMENT")

    @field_validator("embedding_dimensions")
    @classmethod
    def validate_embedding_dimensions(cls, v: int) -> int:
        """Validate embedding dimensions match architecture specification."""
        if v != ARCHITECTURE_EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding dimensions must be {ARCHITECTURE_EMBEDDING_DIMENSIONS} "
                f"per architecture specification (got {v})",
            )
        return v

    @field_validator("chunking_target_tokens")
    @classmethod
    def validate_chunking_target(cls, v: int) -> int:
        """Validate chunking target tokens match architecture specification."""
        if v != ARCHITECTURE_CHUNKING_TARGET_TOKENS:
            raise ValueError(
                f"Chunking target tokens must be {ARCHITECTURE_CHUNKING_TARGET_TOKENS} "
                f"per architecture specification (got {v})",
            )
        return v

    @field_validator("chunking_max_tokens")
    @classmethod
    def validate_chunking_max(cls, v: int) -> int:
        """Validate chunking max tokens match architecture specification."""
        if v != ARCHITECTURE_CHUNKING_MAX_TOKENS:
            raise ValueError(
                f"Chunking max tokens must be {ARCHITECTURE_CHUNKING_MAX_TOKENS} "
                f"per architecture specification (got {v})",
            )
        return v

    @field_validator("chunking_overlap_tokens")
    @classmethod
    def validate_chunking_overlap(cls, v: int) -> int:
        """Validate chunking overlap tokens match architecture specification."""
        if v != ARCHITECTURE_CHUNKING_OVERLAP_TOKENS:
            raise ValueError(
                f"Chunking overlap tokens must be {ARCHITECTURE_CHUNKING_OVERLAP_TOKENS} "
                f"per architecture specification (got {v})",
            )
        return v

    model_config = {
        "env_file": ".env",
        "env_prefix": "INGESTION_",
        "extra": "ignore",
    }


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def validate_architecture_config() -> dict:
    """Validate that current configuration matches architecture specification.

    Returns:
        Dictionary with validation results for CI testing (US-2.12).

    Raises:
        ValueError: If any configuration values don't match architecture spec.
    """
    settings = get_settings()

    validations = {
        "embedding_dimensions": {
            "expected": ARCHITECTURE_EMBEDDING_DIMENSIONS,
            "actual": settings.embedding_dimensions,
            "valid": settings.embedding_dimensions == ARCHITECTURE_EMBEDDING_DIMENSIONS,
        },
        "chunking_target_tokens": {
            "expected": ARCHITECTURE_CHUNKING_TARGET_TOKENS,
            "actual": settings.chunking_target_tokens,
            "valid": settings.chunking_target_tokens == ARCHITECTURE_CHUNKING_TARGET_TOKENS,
        },
        "chunking_max_tokens": {
            "expected": ARCHITECTURE_CHUNKING_MAX_TOKENS,
            "actual": settings.chunking_max_tokens,
            "valid": settings.chunking_max_tokens == ARCHITECTURE_CHUNKING_MAX_TOKENS,
        },
        "chunking_overlap_tokens": {
            "expected": ARCHITECTURE_CHUNKING_OVERLAP_TOKENS,
            "actual": settings.chunking_overlap_tokens,
            "valid": settings.chunking_overlap_tokens == ARCHITECTURE_CHUNKING_OVERLAP_TOKENS,
        },
    }

    all_valid = all(v["valid"] for v in validations.values())
    if not all_valid:
        failed = [k for k, v in validations.items() if not v["valid"]]
        raise ValueError(f"Configuration validation failed for: {failed}")

    return validations
