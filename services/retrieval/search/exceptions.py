"""Custom exceptions for search module."""


class SearchError(Exception):
    """Base exception for search errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SearchConnectionError(SearchError):
    """Error connecting to search backend."""

    pass


class SearchTimeoutError(SearchError):
    """Search operation timed out."""

    pass


class SearchFilterError(SearchError):
    """Error building or applying search filters."""

    pass


class SearchConfigError(SearchError):
    """Invalid search configuration."""

    pass
