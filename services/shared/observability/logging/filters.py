"""
Log Filters.

Provides filters for sensitive data masking and log filtering.
"""

import logging
import re
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """
    Filter that masks sensitive data in log records.

    Detects and masks:
    - Field names matching sensitive patterns
    - JWT tokens
    - API keys
    - Credit card numbers
    - Other sensitive patterns
    """

    # Regex patterns for sensitive data
    PATTERNS = {
        # JWT tokens (header.payload.signature)
        "jwt": re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
        # Bearer tokens
        "bearer": re.compile(r"Bearer\s+[A-Za-z0-9_-]+", re.IGNORECASE),
        # API keys (various formats)
        "api_key": re.compile(
            r"(?:api[_-]?key|apikey)[=:]\s*['\"]?([A-Za-z0-9_-]{20,})['\"]?",
            re.IGNORECASE,
        ),
        # Credit card numbers (with or without spaces/dashes)
        "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        # SSN (US Social Security Number)
        "ssn": re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
        # Email addresses (partial masking)
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        # AWS access keys
        "aws_key": re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}"),
        # Generic secret patterns
        "generic_secret": re.compile(
            r"(?:secret|password|passwd|pwd)[=:]\s*['\"]?([^\s'\"]+)['\"]?",
            re.IGNORECASE,
        ),
    }

    def __init__(
        self,
        sensitive_fields: list[str] | None = None,
        mask_pattern: str = "***REDACTED***",
        mask_email: bool = False,
    ):
        """
        Initialize the filter.

        Args:
            sensitive_fields: List of field names to mask (case-insensitive)
            mask_pattern: String to replace sensitive data with
            mask_email: Whether to mask email addresses
        """
        super().__init__()
        self.mask_pattern = mask_pattern
        self.mask_email = mask_email

        # Default sensitive field names
        self.sensitive_fields = {
            f.lower()
            for f in (
                sensitive_fields
                or [
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
                ]
            )
        }

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter the log record, masking sensitive data.

        Returns True to allow the record through (but modified).
        """
        # Mask the message
        record.msg = self._mask_string(str(record.msg))

        # Mask args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self._mask_value(arg) for arg in record.args)

        # Mask extra attributes
        for key in list(record.__dict__.keys()):
            if key.startswith("_") or key in self._standard_attrs():
                continue
            value = getattr(record, key)
            setattr(record, key, self._mask_value(value, key))

        return True

    def _standard_attrs(self) -> set[str]:
        """Return standard LogRecord attributes."""
        return {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "asctime",
        }

    def _mask_value(self, value: Any, field_name: str = "") -> Any:
        """Mask a value based on its type and field name."""
        # Check if field name is sensitive
        if field_name and field_name.lower() in self.sensitive_fields:
            return self.mask_pattern

        if isinstance(value, str):
            return self._mask_string(value)
        if isinstance(value, dict):
            return self._mask_dict(value)
        if isinstance(value, (list, tuple)):
            return type(value)(self._mask_value(item) for item in value)
        return value

    def _mask_string(self, text: str) -> str:
        """Mask sensitive patterns in a string."""
        if not text:
            return text

        result = text

        # Mask each pattern type
        for pattern_name, pattern in self.PATTERNS.items():
            if pattern_name == "email" and not self.mask_email:
                continue
            result = pattern.sub(self.mask_pattern, result)

        return result

    def _mask_dict(self, data: dict) -> dict:
        """Recursively mask sensitive fields in a dictionary."""
        result = {}
        for key, value in data.items():
            key_lower = key.lower() if isinstance(key, str) else key

            # Check if key is sensitive
            if isinstance(key_lower, str) and key_lower in self.sensitive_fields:
                result[key] = self.mask_pattern
            elif isinstance(value, dict):
                result[key] = self._mask_dict(value)
            elif isinstance(value, (list, tuple)):
                result[key] = type(value)(self._mask_value(item) for item in value)
            elif isinstance(value, str):
                result[key] = self._mask_string(value)
            else:
                result[key] = value

        return result


class LogLevelFilter(logging.Filter):
    """
    Filter that only allows logs at or above a certain level.

    Useful for filtering specific loggers to different levels.
    """

    def __init__(self, min_level: int = logging.INFO):
        """
        Initialize the filter.

        Args:
            min_level: Minimum log level to allow
        """
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True if record level >= min_level."""
        return record.levelno >= self.min_level


class ExcludePathFilter(logging.Filter):
    """
    Filter that excludes log records for specific paths.

    Useful for suppressing health check logs, etc.
    """

    def __init__(self, excluded_paths: list[str] | None = None):
        """
        Initialize the filter.

        Args:
            excluded_paths: List of path prefixes to exclude
        """
        super().__init__()
        self.excluded_paths = excluded_paths or []

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True if the path should be logged."""
        # Check if record has a path attribute
        path = getattr(record, "path", None) or getattr(record, "request_path", None)
        if path is None:
            return True

        # Check against excluded paths
        return all(not path.startswith(excluded) for excluded in self.excluded_paths)


class RateLimitFilter(logging.Filter):
    """
    Filter that rate-limits repeated log messages.

    Prevents log flooding from repeated errors.
    """

    def __init__(
        self,
        rate_limit_seconds: float = 60.0,
        max_duplicates: int = 3,
    ):
        """
        Initialize the filter.

        Args:
            rate_limit_seconds: Time window for rate limiting
            max_duplicates: Max duplicate messages in window
        """
        super().__init__()
        self.rate_limit_seconds = rate_limit_seconds
        self.max_duplicates = max_duplicates
        self._message_counts: dict[str, list[float]] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True if the message should be logged."""
        import time

        # Create a key for the message
        key = f"{record.name}:{record.levelno}:{record.msg}"

        current_time = time.time()
        cutoff_time = current_time - self.rate_limit_seconds

        # Get or create the timestamp list for this message
        if key not in self._message_counts:
            self._message_counts[key] = []

        # Remove old timestamps
        self._message_counts[key] = [t for t in self._message_counts[key] if t > cutoff_time]

        # Check if we've exceeded the limit
        if len(self._message_counts[key]) >= self.max_duplicates:
            # Add suppression note
            if not hasattr(record, "_rate_limited"):
                record._rate_limited = True
                record.msg = f"{record.msg} (further duplicates suppressed)"
                self._message_counts[key].append(current_time)
                return True
            return False

        # Add timestamp and allow
        self._message_counts[key].append(current_time)
        return True
