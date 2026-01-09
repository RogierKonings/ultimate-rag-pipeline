"""Custom exceptions for the Model Gateway.

This module defines exception classes for handling various error scenarios
in LLM API interactions.
"""


class ModelGatewayError(Exception):
    """Base exception for model gateway errors.

    All gateway-specific exceptions inherit from this class,
    making it easy to catch all gateway errors.
    """

    def __init__(self, message: str = "Model gateway error occurred"):
        self.message = message
        super().__init__(self.message)


class ModelNotFoundError(ModelGatewayError):
    """Model is not configured or available.

    Raised when a requested model is not found in the gateway configuration.
    """

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Model not found: {model}")


class ModelTimeoutError(ModelGatewayError):
    """Request timed out.

    Raised when an LLM request exceeds the configured timeout.
    """

    def __init__(self, message: str = "Request timed out"):
        super().__init__(message)


class RateLimitError(ModelGatewayError):
    """Rate limit exceeded.

    Raised when the rate limit for a model is exceeded.
    """

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message)


class AuthenticationError(ModelGatewayError):
    """Invalid or missing API key.

    Raised when authentication with the LLM provider fails.
    """

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class ModelError(ModelGatewayError):
    """Generic model/API error.

    Raised for general errors from the LLM provider that don't
    fit into other categories.
    """

    def __init__(self, message: str = "Model error occurred"):
        super().__init__(message)


class StreamingNotSupportedError(ModelGatewayError):
    """Model does not support streaming.

    Raised when attempting to stream from a model that
    doesn't support streaming responses.
    """

    def __init__(self, model: str):
        self.model = model
        super().__init__(f"Model does not support streaming: {model}")


class InvalidRequestError(ModelGatewayError):
    """Invalid request parameters.

    Raised when the request contains invalid parameters.
    """

    def __init__(self, message: str = "Invalid request"):
        super().__init__(message)


class ContentFilterError(ModelGatewayError):
    """Content was filtered by the model.

    Raised when the model's content filter blocks the request or response.
    """

    def __init__(self, message: str = "Content filtered"):
        super().__init__(message)
