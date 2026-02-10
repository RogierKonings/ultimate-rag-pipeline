"""Orchestrator Service Configuration Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings

from orchestrator.config.timeouts import get_timeout_seconds
from orchestrator.config.urls import (
    get_llm_gateway_url,
    get_otel_endpoint,
    get_postgres_url,
    get_redis_url,
    get_retrieval_service_url,
)


class OrchestratorConfig(BaseSettings):
    """Configuration settings for the Orchestrator Service."""

    # Service
    service_name: str = "orchestrator-service"
    service_port: int = 8003
    debug: bool = False
    environment: str = "development"

    # CORS configuration
    cors_enabled: bool = True
    cors_allowed_origins: str = ""  # Comma-separated; empty = env-based defaults
    cors_allowed_methods: str = ""  # Comma-separated; empty = defaults
    cors_allowed_headers: str = ""  # Comma-separated; empty = defaults

    # Retrieval Service (from centralized config)
    retrieval_url: str = Field(default_factory=get_retrieval_service_url)
    retrieval_timeout: float = get_timeout_seconds("ORCHESTRATOR_RETRIEVAL")
    retrieval_top_k: int = 100  # Number of documents to retrieve (set high to search all)

    # LLM Gateway (from centralized config)
    llm_gateway_url: str = Field(default_factory=get_llm_gateway_url)
    default_model: str = "meta-llama/Llama-3.1-70B-Instruct"
    fallback_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    max_tokens: int = 1024
    temperature: float = 0.7

    # Model Tiering (US-10.5.2)
    small_model: str = "qwen2.5-7b"
    medium_model: str = "llama-3.1-8b"
    large_model: str = "llama-3.1-70b"
    enable_model_tiering: bool = True  # Feature flag for gradual rollout

    # Redis (from centralized config)
    redis_url: str = Field(default_factory=get_redis_url)
    session_ttl: int = 3600  # 1 hour
    max_history_length: int = 20

    # Answer Cache (US-10.5.3)
    answer_cache_enabled: bool = True
    answer_cache_ttl: int = 3600  # 1 hour default
    answer_cache_prompt_version: str = "v1"  # Bump when prompts change

    # Postgres (from centralized config)
    database_url: str = Field(default_factory=get_postgres_url)

    # Guardrails
    enable_input_guardrails: bool = True
    enable_output_guardrails: bool = True
    max_input_length: int = 4000

    # Answer Verification (CRAG-style)
    verification_enabled: bool = False  # Opt-in by default
    verification_max_claims: int = 5
    verification_confidence_threshold: float = 0.7
    verification_add_disclaimer: bool = True

    # Streaming
    stream_timeout: float = get_timeout_seconds("ORCHESTRATOR_LLM")

    # JWT Authentication
    jwt_secret: str = "secret"  # noqa: S105
    jwt_algorithm: str = "HS256"

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0

    # Observability (from centralized config)
    otel_exporter_endpoint: str = Field(default_factory=get_otel_endpoint)
    enable_tracing: bool = True

    class Config:
        env_prefix = "ORCHESTRATOR_"
        case_sensitive = False


# Global config instance
def get_config() -> OrchestratorConfig:
    """Get the configuration instance."""
    return OrchestratorConfig()
