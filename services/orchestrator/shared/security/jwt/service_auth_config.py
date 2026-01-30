"""
Service authentication configuration.

This module provides configuration for service-to-service authentication,
including service identity and authorization matrix settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class ServiceAuthSettings(BaseSettings):
    """
    Configuration for service-to-service authentication.

    Environment Variables:
        SERVICE_NAME: Name of this service (e.g., "orchestrator")
        SERVICE_AUTH_ENABLED: Enable/disable service auth (default: True)
        SERVICE_TOKEN_TTL_SECONDS: Token time-to-live (default: 300)
        SERVICE_AUTH_EXCLUDE_PATHS: Comma-separated paths to exclude from auth

    The authorization matrix defines which services can call which endpoints.
    It can be configured via environment or loaded from a config file.
    """

    # Service identity
    service_name: str = Field(
        default="unknown",
        description="Name of this service",
        alias="SERVICE_NAME",
    )

    # Authentication settings
    enabled: bool = Field(
        default=True,
        description="Enable service-to-service authentication",
        alias="SERVICE_AUTH_ENABLED",
    )
    token_ttl_seconds: int = Field(
        default=300,  # 5 minutes
        ge=60,
        le=3600,
        description="Service token time-to-live in seconds",
        alias="SERVICE_TOKEN_TTL_SECONDS",
    )

    # Paths to exclude from service auth
    exclude_paths: list[str] = Field(
        default_factory=lambda: [
            "/health",
            "/healthz",
            "/ready",
            "/readyz",
            "/live",
            "/livez",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ],
        description="Paths excluded from service authentication",
        alias="SERVICE_AUTH_EXCLUDE_PATHS",
    )

    # Trusted services (services allowed to call this service)
    trusted_services: list[str] = Field(
        default_factory=list,
        description="List of service names trusted to call this service",
        alias="SERVICE_AUTH_TRUSTED_SERVICES",
    )

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


# Default authorization matrix for the RAG pipeline services
# Maps service_name -> target_service -> allowed_endpoints
DEFAULT_AUTHORIZATION_MATRIX: dict[str, dict[str, list[str]]] = {
    "orchestrator": {
        "retrieval": ["/internal/*", "/api/v1/search/*"],
        "ingestion": ["/internal/*"],
        "llm-gateway": ["/internal/*", "/v1/chat/completions", "/v1/embeddings"],
        "embedding": ["/internal/*", "/embed"],
    },
    "retrieval": {
        "embedding": ["/internal/*", "/embed"],
    },
    "ingestion": {
        "embedding": ["/internal/*", "/embed"],
        "retrieval": ["/internal/index/*"],
    },
}


def get_allowed_endpoints(
    source_service: str,
    target_service: str,
    matrix: dict[str, dict[str, list[str]]] | None = None,
) -> list[str]:
    """
    Get allowed endpoints for a service-to-service call.

    Args:
        source_service: The calling service name
        target_service: The target service name
        matrix: Optional custom authorization matrix (default: DEFAULT_AUTHORIZATION_MATRIX)

    Returns:
        List of allowed endpoint patterns, or empty list if not authorized
    """
    if matrix is None:
        matrix = DEFAULT_AUTHORIZATION_MATRIX

    return matrix.get(source_service, {}).get(target_service, [])


def is_service_authorized(
    source_service: str,
    target_service: str,
    endpoint: str,
    matrix: dict[str, dict[str, list[str]]] | None = None,
) -> bool:
    """
    Check if a service is authorized to call an endpoint on another service.

    Args:
        source_service: The calling service name
        target_service: The target service name
        endpoint: The endpoint being called
        matrix: Optional custom authorization matrix

    Returns:
        True if the call is authorized
    """
    import fnmatch

    allowed = get_allowed_endpoints(source_service, target_service, matrix)
    return any(fnmatch.fnmatch(endpoint, pattern) for pattern in allowed)
