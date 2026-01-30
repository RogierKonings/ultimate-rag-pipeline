"""
Log Sanitizer.

Provides utilities for sanitizing sensitive data from logs, connection strings,
and structured data. Can be used standalone or integrated with structlog.

This module complements the SensitiveDataFilter for stdlib logging with
a functional approach that works with any data structure.
"""

import re
from typing import Any

# Patterns to sanitize in logs and data
SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Database connection URLs with credentials
    (re.compile(r"://[^:]+:[^@]+@", re.IGNORECASE), "://***:***@"),
    # Redis URLs with password
    (re.compile(r"redis://[^:]*:[^@]+@", re.IGNORECASE), "redis://***:***@"),
    # Generic password parameters
    (re.compile(r"password=[\w\-]+", re.IGNORECASE), "password=***"),
    (re.compile(r"pwd=[\w\-]+", re.IGNORECASE), "pwd=***"),
    # Secret parameters
    (re.compile(r"secret=[\w\-]+", re.IGNORECASE), "secret=***"),
    # Token parameters
    (re.compile(r"token=[\w\-\.]+", re.IGNORECASE), "token=***"),
    # API key parameters
    (re.compile(r"api[_-]?key=[\w\-]+", re.IGNORECASE), "api_key=***"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[\w\-\.]+", re.IGNORECASE), "Bearer ***"),
    # Basic auth headers
    (re.compile(r"Basic\s+[\w\+/=]+", re.IGNORECASE), "Basic ***"),
    # JWT tokens
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "***JWT***"),
    # AWS access keys
    (re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}"), "***AWS_KEY***"),
]

# Keys that should have their entire value masked
SENSITIVE_KEYS: set[str] = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "private_key",
    "privatekey",
    "access_token",
    "refresh_token",
    "jwt",
    "bearer",
    "connection_string",
    "database_url",
    "redis_password",
    "postgres_password",
    "opensearch_password",
}


def sanitize_value(value: Any) -> Any:
    """Sanitize sensitive data from a value.

    Applies pattern matching to detect and mask credentials,
    tokens, and other sensitive information in strings.

    Args:
        value: The value to sanitize.

    Returns:
        The sanitized value with sensitive data masked.
    """
    if not isinstance(value, str):
        return value

    result = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def sanitize_dict(data: dict, mask: str = "***") -> dict:
    """Recursively sanitize sensitive data from a dictionary.

    Masks values for keys that match sensitive key patterns,
    and applies pattern-based sanitization to string values.

    Args:
        data: The dictionary to sanitize.
        mask: The string to use for masking sensitive values.

    Returns:
        A new dictionary with sensitive data masked.
    """
    result = {}
    for key, value in data.items():
        lower_key = key.lower() if isinstance(key, str) else str(key).lower()

        # Mask entire value for sensitive keys
        if any(s in lower_key for s in SENSITIVE_KEYS):
            result[key] = mask
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, mask)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict(v, mask) if isinstance(v, dict) else sanitize_value(v) for v in value
            ]
        else:
            result[key] = sanitize_value(value)

    return result


def sanitize_connection_string(connection_string: str) -> str:
    """Sanitize a database connection string.

    Specifically designed to handle connection URLs like:
    - postgresql://user:password@host:port/db
    - redis://:password@host:port/db
    - mongodb://user:password@host:port/db

    Args:
        connection_string: The connection string to sanitize.

    Returns:
        The sanitized connection string with credentials masked.
    """
    if not connection_string:
        return connection_string

    # Handle standard URL format: scheme://user:password@host
    pattern = re.compile(r"(://[^:]*:)[^@]+(@)")
    return pattern.sub(r"\1***\2", connection_string)


class SanitizingProcessor:
    """Structlog processor that sanitizes sensitive data.

    Can be added to structlog's processor chain to automatically
    mask sensitive data in log output.

    Example:
        import structlog

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                SanitizingProcessor(),
                structlog.processors.JSONRenderer(),
            ],
        )
    """

    def __init__(self, mask: str = "***"):
        """Initialize the processor.

        Args:
            mask: The string to use for masking sensitive values.
        """
        self.mask = mask

    def __call__(
        self,
        logger: Any,
        method_name: str,
        event_dict: dict,
    ) -> dict:
        """Process the event dictionary, sanitizing sensitive data.

        Args:
            logger: The wrapped logger object.
            method_name: The name of the method called on the logger.
            event_dict: The event dictionary with log data.

        Returns:
            The sanitized event dictionary.
        """
        return sanitize_dict(event_dict, self.mask)


def configure_structlog_with_sanitizer() -> None:
    """Configure structlog with the sanitizing processor.

    Sets up structlog with a standard configuration that includes
    the SanitizingProcessor for automatic credential masking.

    This is a convenience function for services that want secure
    logging out of the box.
    """
    import structlog

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            SanitizingProcessor(),  # Add sanitizer before final output
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
