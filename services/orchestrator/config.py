"""Orchestrator Service Configuration."""

from pydantic_settings import BaseSettings


class OrchestratorConfig(BaseSettings):
    """Configuration settings for the Orchestrator Service."""

    # Service
    service_name: str = "orchestrator-service"
    service_port: int = 8003
    debug: bool = False

    # Retrieval Service
    retrieval_url: str = "http://localhost:8002"
    retrieval_timeout: float = 10.0
    retrieval_top_k: int = 100  # Number of documents to retrieve (set high to search all)

    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"
    default_model: str = "meta-llama/Llama-3.1-70B-Instruct"
    fallback_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    max_tokens: int = 1024
    temperature: float = 0.7

    # Redis
    redis_url: str = "redis://localhost:6379"
    session_ttl: int = 3600  # 1 hour
    max_history_length: int = 20

    # Postgres
    database_url: str = "postgresql+asyncpg://raguser:ragpassword@localhost:5432/ragpipeline"

    # Guardrails
    enable_input_guardrails: bool = True
    enable_output_guardrails: bool = True
    max_input_length: int = 4000

    # Streaming
    stream_timeout: float = 60.0

    # JWT Authentication
    jwt_secret: str = "secret"  # noqa: S105
    jwt_algorithm: str = "HS256"

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0

    # Observability
    otel_exporter_endpoint: str = "http://localhost:4317"
    enable_tracing: bool = True

    class Config:
        env_prefix = "ORCHESTRATOR_"
        case_sensitive = False


# Global config instance
def get_config() -> OrchestratorConfig:
    """Get the configuration instance."""
    return OrchestratorConfig()
