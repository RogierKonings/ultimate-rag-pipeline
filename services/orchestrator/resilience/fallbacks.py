"""Fallback handlers for graceful degradation.

This module provides fallback implementations for various services:
- LLM fallback: Return cached or default responses
- Retrieval fallback: Return empty results gracefully
- Embedding fallback: Return cached embeddings or raise

Fallbacks are designed to maintain service availability when
primary services are unavailable or failing.
"""

import logging
from typing import Any

from .config import FallbackConfig

logger = logging.getLogger(__name__)


class FallbackError(Exception):
    """Raised when a fallback operation fails."""

    def __init__(self, service: str, message: str, original_error: Exception | None = None):
        self.service = service
        self.original_error = original_error
        super().__init__(f"Fallback for '{service}' failed: {message}")


class FallbackHandlers:
    """Static fallback handlers for various services.

    These handlers provide graceful degradation by returning
    cached or default responses when primary services fail.

    Usage:
        # In circuit breaker call
        result = await circuit.call(
            llm_service.generate,
            prompt,
            fallback=FallbackHandlers.llm_fallback
        )
    """

    _config: FallbackConfig = FallbackConfig()
    _cache: dict[str, Any] = {}

    @classmethod
    def configure(cls, config: FallbackConfig) -> None:
        """Configure fallback handlers.

        Args:
            config: Fallback configuration
        """
        cls._config = config

    @classmethod
    def set_cached_response(cls, key: str, value: Any) -> None:
        """Store a value in the fallback cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        cls._cache[key] = value
        logger.debug(
            "Cached fallback response for key '%s'",
            key,
            extra={"cache_key": key},
        )

    @classmethod
    def get_cached_response(cls, key: str) -> Any | None:
        """Retrieve a value from the fallback cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        return cls._cache.get(key)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the fallback cache."""
        cls._cache.clear()
        logger.info("Fallback cache cleared")

    @staticmethod
    async def llm_fallback(
        *args: Any,
        error: Exception | None = None,
        cache_key: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Return cached or default response on LLM failure.

        This fallback:
        1. Checks for cached response if cache_key provided
        2. Returns default response if enabled
        3. Raises FallbackError if all options exhausted

        Args:
            *args: Original function arguments (ignored)
            error: The original exception that triggered fallback
            cache_key: Optional cache key to look up cached response
            **kwargs: Original function keyword arguments (ignored)

        Returns:
            Cached or default response string

        Raises:
            FallbackError: If no fallback option is available
        """
        config = FallbackHandlers._config

        # Try cache first
        if cache_key and config.enable_cache_fallback:
            cached = FallbackHandlers.get_cached_response(cache_key)
            if cached is not None:
                logger.info(
                    "LLM fallback: returning cached response",
                    extra={"cache_key": cache_key, "error": str(error) if error else None},
                )
                return cached

        # Return default response
        if config.enable_default_response:
            logger.info(
                "LLM fallback: returning default response",
                extra={"error": str(error) if error else None},
            )
            return config.default_response

        # No fallback available
        raise FallbackError(
            "llm",
            "No fallback option available (cache miss, default disabled)",
            original_error=error,
        )

    @staticmethod
    async def retrieval_fallback(
        *args: Any,
        error: Exception | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return empty results on retrieval failure.

        This fallback returns an empty document list, allowing the
        system to continue processing without retrieved context.
        The LLM can still provide a response based on its training.

        Args:
            *args: Original function arguments (ignored)
            error: The original exception that triggered fallback
            **kwargs: Original function keyword arguments (ignored)

        Returns:
            Empty list of documents
        """
        logger.warning(
            "Retrieval fallback: returning empty results",
            extra={"error": str(error) if error else None},
        )
        return []

    @staticmethod
    async def embedding_fallback(
        *args: Any,
        error: Exception | None = None,
        cache_key: str | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """Return cached embedding or raise on failure.

        Unlike other fallbacks, embedding fallback is more strict:
        it only returns cached embeddings. If no cached embedding
        is available, it raises an error because generating a
        fake embedding would corrupt search results.

        Args:
            *args: Original function arguments (ignored)
            error: The original exception that triggered fallback
            cache_key: Optional cache key to look up cached embedding
            **kwargs: Original function keyword arguments (ignored)

        Returns:
            Cached embedding vector

        Raises:
            FallbackError: If no cached embedding is available
        """
        config = FallbackHandlers._config

        # Only allow cached embeddings as fallback
        if cache_key and config.enable_cache_fallback:
            cached = FallbackHandlers.get_cached_response(cache_key)
            if cached is not None and isinstance(cached, list):
                logger.info(
                    "Embedding fallback: returning cached embedding",
                    extra={"cache_key": cache_key, "error": str(error) if error else None},
                )
                return cached

        # Cannot fake embeddings - must raise
        raise FallbackError(
            "embedding",
            "No cached embedding available, cannot generate fake embedding",
            original_error=error,
        )

    @staticmethod
    async def guardrails_fallback(
        *args: Any,
        error: Exception | None = None,
        strict_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fallback for guardrails service failure.

        In non-strict mode, allows content through when guardrails fail.
        In strict mode, blocks content to err on the side of safety.

        Args:
            *args: Original function arguments (ignored)
            error: The original exception that triggered fallback
            strict_mode: If True, block content on guardrails failure
            **kwargs: Original function keyword arguments (ignored)

        Returns:
            Guardrail result indicating pass/fail
        """
        if strict_mode:
            logger.warning(
                "Guardrails fallback (strict): blocking content",
                extra={"error": str(error) if error else None},
            )
            return {
                "passed": False,
                "violations": [],
                "reason": "Guardrails service unavailable (strict mode)",
            }

        logger.warning(
            "Guardrails fallback: allowing content through",
            extra={"error": str(error) if error else None},
        )
        return {
            "passed": True,
            "violations": [],
            "reason": "Guardrails service unavailable (permissive mode)",
        }


# Convenience function for creating custom fallbacks
def create_fallback_response(
    service_name: str,
    default_value: Any,
    log_level: str = "warning",
) -> callable:
    """Create a custom fallback function.

    Args:
        service_name: Name of the service for logging
        default_value: Value to return on fallback
        log_level: Logging level for fallback events

    Returns:
        Async fallback function
    """

    async def fallback(*args: Any, error: Exception | None = None, **kwargs: Any) -> Any:
        log_func = getattr(logger, log_level)
        log_func(
            f"{service_name} fallback: returning default value",
            extra={"error": str(error) if error else None},
        )
        return default_value

    return fallback
