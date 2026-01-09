"""Exceptions for reranking module."""


class RerankerError(Exception):
    """Base exception for reranker errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class RerankerConnectionError(RerankerError):
    """Raised when connection to reranker service fails."""

    pass


class RerankerTimeoutError(RerankerError):
    """Raised when reranker request times out."""

    pass


class RerankerValidationError(RerankerError):
    """Raised when input validation fails."""

    pass
