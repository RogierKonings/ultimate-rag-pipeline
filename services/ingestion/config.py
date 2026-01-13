"""Application configuration using pydantic-settings.

This module defines validated configuration settings for the ingestion service.
Configuration values are loaded from environment variables with validation
to ensure alignment with architecture-defined defaults (US-2.12).

Architecture defaults (from docs/architecture.md):
- Embedding dimensions: 1024 (BGE-large)
- Chunking target: 300 tokens
- Chunking max: 512 tokens
- Chunking overlap: 50 tokens
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings

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

    # Database URLs
    database_url: str = "postgresql://localhost:5432/rag_pipeline"
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    opensearch_url: str = "http://localhost:9200"
    minio_url: str = "http://localhost:9000"

    # MinIO/S3 credentials
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"  # noqa: S105
    minio_bucket: str = "rag-documents"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"

    # Embedding configuration (architecture defaults, US-2.12)
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dimensions: int = ARCHITECTURE_EMBEDDING_DIMENSIONS

    # Chunking configuration (architecture defaults, US-2.12)
    chunking_target_tokens: int = ARCHITECTURE_CHUNKING_TARGET_TOKENS
    chunking_max_tokens: int = ARCHITECTURE_CHUNKING_MAX_TOKENS
    chunking_overlap_tokens: int = ARCHITECTURE_CHUNKING_OVERLAP_TOKENS

    # OpenTelemetry configuration (US-2.12)
    otel_enabled: bool = True
    otel_service_name: str = "ingestion-service"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # Prometheus metrics (US-2.12)
    metrics_enabled: bool = True
    metrics_port: int = 9090

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
