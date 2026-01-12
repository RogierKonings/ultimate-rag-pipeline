"""
Logging Configuration.

Provides configuration dataclass for structured logging setup.
"""

import contextlib
import os
from dataclasses import dataclass, field


@dataclass
class LoggingConfig:
    """
    Configuration for structured logging.

    Attributes:
        service_name: Name of the service for log identification
        service_version: Version of the service
        environment: Deployment environment (dev, staging, prod)
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON format (True) or text format (False)
        pretty_json: Pretty-print JSON (for development)
        include_trace_context: Include trace_id/span_id from OpenTelemetry
        sensitive_fields: Fields to mask in logs
        excluded_paths: Paths to exclude from request logging
        log_request_body: Whether to log request bodies
        log_response_body: Whether to log response bodies
        max_body_length: Maximum length of body to log
        async_logging: Use async queue-based logging
    """

    service_name: str
    service_version: str = "0.0.0"
    environment: str = "development"
    log_level: str = "INFO"
    json_format: bool = True
    pretty_json: bool = False
    include_trace_context: bool = True
    sensitive_fields: list[str] = field(default_factory=lambda: [
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "api-key",
        "authorization",
        "auth",
        "credential",
        "private_key",
        "privatekey",
        "access_token",
        "refresh_token",
        "jwt",
        "bearer",
        "credit_card",
        "creditcard",
        "card_number",
        "cvv",
        "ssn",
        "social_security",
    ])
    excluded_paths: list[str] = field(default_factory=lambda: [
        "/health",
        "/healthz",
        "/ready",
        "/readyz",
        "/live",
        "/livez",
        "/metrics",
        "/favicon.ico",
    ])
    log_request_body: bool = False
    log_response_body: bool = False
    max_body_length: int = 1000
    async_logging: bool = True

    @classmethod
    def from_env(cls, service_name: str | None = None) -> "LoggingConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            SERVICE_NAME: Service name (required if not provided)
            SERVICE_VERSION: Service version
            ENVIRONMENT: Deployment environment
            LOG_LEVEL: Logging level
            LOG_JSON: Use JSON format (true/false)
            LOG_PRETTY: Pretty-print JSON (true/false)
            LOG_TRACE_CONTEXT: Include trace context (true/false)
            LOG_SENSITIVE_FIELDS: Comma-separated list of sensitive fields
            LOG_EXCLUDED_PATHS: Comma-separated list of paths to exclude
            LOG_REQUEST_BODY: Log request bodies (true/false)
            LOG_RESPONSE_BODY: Log response bodies (true/false)
            LOG_MAX_BODY_LENGTH: Max body length to log
            LOG_ASYNC: Use async logging (true/false)

        Returns:
            LoggingConfig instance
        """
        name = service_name or os.getenv("SERVICE_NAME", "unknown-service")

        # Parse boolean env vars
        def parse_bool(value: str | None, default: bool) -> bool:
            if value is None:
                return default
            return value.lower() in ("true", "1", "yes")

        # Parse list env vars
        def parse_list(value: str | None, default: list[str]) -> list[str]:
            if value is None:
                return default
            return [item.strip() for item in value.split(",") if item.strip()]

        config = cls(
            service_name=name,
            service_version=os.getenv("SERVICE_VERSION", "0.0.0"),
            environment=os.getenv("ENVIRONMENT", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            json_format=parse_bool(os.getenv("LOG_JSON"), True),
            pretty_json=parse_bool(os.getenv("LOG_PRETTY"), False),
            include_trace_context=parse_bool(os.getenv("LOG_TRACE_CONTEXT"), True),
            log_request_body=parse_bool(os.getenv("LOG_REQUEST_BODY"), False),
            log_response_body=parse_bool(os.getenv("LOG_RESPONSE_BODY"), False),
            async_logging=parse_bool(os.getenv("LOG_ASYNC"), True),
        )

        # Override sensitive fields if provided
        sensitive_fields = os.getenv("LOG_SENSITIVE_FIELDS")
        if sensitive_fields:
            config.sensitive_fields = parse_list(sensitive_fields, config.sensitive_fields)

        # Override excluded paths if provided
        excluded_paths = os.getenv("LOG_EXCLUDED_PATHS")
        if excluded_paths:
            config.excluded_paths = parse_list(excluded_paths, config.excluded_paths)

        # Override max body length if provided
        max_body = os.getenv("LOG_MAX_BODY_LENGTH")
        if max_body:
            with contextlib.suppress(ValueError):
                config.max_body_length = int(max_body)

        return config

    def get_log_level_int(self) -> int:
        """Get log level as integer for logging module."""
        import logging
        return getattr(logging, self.log_level, logging.INFO)
