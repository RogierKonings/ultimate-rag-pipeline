"""
Authenticated HTTP client for service-to-service communication.

This module provides an HTTP client that automatically handles
service authentication tokens for inter-service API calls.
"""

import time
from datetime import timedelta
from typing import Any

import httpx
import structlog

from .handler import JWTHandler
from .service_auth_config import ServiceAuthSettings, get_allowed_endpoints

logger = structlog.get_logger(__name__)


class AuthenticatedServiceClient:
    """
    HTTP client with automatic service-to-service authentication.

    This client automatically generates and caches service tokens,
    injecting them into outgoing requests. It also propagates
    correlation context for distributed tracing.

    Features:
    - Automatic token generation and caching
    - Token refresh before expiration
    - Correlation header propagation
    - Connection pooling via httpx.AsyncClient

    Example:
        ```python
        from shared.security.jwt import (
            JWTHandler,
            ServiceAuthSettings,
            AuthenticatedServiceClient,
        )

        handler = JWTHandler()
        settings = ServiceAuthSettings(service_name="orchestrator")

        async with AuthenticatedServiceClient(
            base_url="http://retrieval:8002",
            target_service="retrieval",
            handler=handler,
            settings=settings,
        ) as client:
            response = await client.post(
                "/internal/search",
                json={"query": "test", "tenant_id": "..."},
            )
        ```
    """

    def __init__(
        self,
        base_url: str,
        target_service: str,
        handler: JWTHandler,
        settings: ServiceAuthSettings,
        timeout: float = 30.0,
        token_refresh_buffer_seconds: int = 30,
        **httpx_kwargs: Any,
    ):
        """
        Initialize authenticated service client.

        Args:
            base_url: Base URL of the target service
            target_service: Name of the target service (for audience)
            handler: JWT handler for token creation
            settings: Service authentication settings (contains service_name)
            timeout: Request timeout in seconds
            token_refresh_buffer_seconds: Refresh token this many seconds
                                         before expiration
            **httpx_kwargs: Additional arguments for httpx.AsyncClient
        """
        self.base_url = base_url.rstrip("/")
        self.target_service = target_service
        self.handler = handler
        self.settings = settings
        self.timeout = timeout
        self.token_refresh_buffer = token_refresh_buffer_seconds
        self._httpx_kwargs = httpx_kwargs

        self._client: httpx.AsyncClient | None = None
        self._token_cache: tuple[str, float] | None = None  # (token, expiry_timestamp)

        # Get allowed endpoints for this service pair
        self._allowed_endpoints = get_allowed_endpoints(
            settings.service_name,
            target_service,
        )

    async def __aenter__(self) -> "AuthenticatedServiceClient":
        """Initialize HTTP client on context entry."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            **self._httpx_kwargs,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Close HTTP client on context exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_or_create_token(self) -> str:
        """Get cached token or create a new one."""
        now = time.time()

        # Check if we have a valid cached token
        if self._token_cache:
            token, expiry = self._token_cache
            # Refresh if token expires within buffer period
            if expiry > now + self.token_refresh_buffer:
                return token

        # Create new token
        ttl = timedelta(seconds=self.settings.token_ttl_seconds)
        token = self.handler.create_service_token(
            service_name=self.settings.service_name,
            target_service=self.target_service,
            allowed_endpoints=self._allowed_endpoints,
            expires_delta=ttl,
        )

        # Cache token
        self._token_cache = (token, now + self.settings.token_ttl_seconds)

        logger.debug(
            "service_token_created",
            source_service=self.settings.service_name,
            target_service=self.target_service,
            ttl_seconds=self.settings.token_ttl_seconds,
        )

        return token

    def _get_headers(
        self,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Build request headers with auth token and correlation context.

        Args:
            extra_headers: Additional headers to include

        Returns:
            Headers dict with Authorization and correlation headers
        """
        headers = dict(extra_headers) if extra_headers else {}

        # Add service auth token
        token = self._get_or_create_token()
        headers["Authorization"] = f"Bearer {token}"

        # Propagate correlation context if available
        try:
            from shared.observability.correlation import get_correlation_context

            ctx = get_correlation_context()
            if ctx:
                headers.update(ctx.to_headers())
        except ImportError:
            # Correlation module not available
            pass

        return headers

    def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized."""
        if not self._client:
            raise RuntimeError(
                "Client not initialized. Use 'async with' statement."
            )
        return self._client

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make authenticated GET request.

        Args:
            path: Request path (relative to base_url)
            params: Query parameters
            headers: Additional headers
            **kwargs: Additional httpx arguments

        Returns:
            HTTP response
        """
        client = self._ensure_client()
        return await client.get(
            path,
            params=params,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def post(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make authenticated POST request.

        Args:
            path: Request path (relative to base_url)
            json: JSON body
            data: Form data
            headers: Additional headers
            **kwargs: Additional httpx arguments

        Returns:
            HTTP response
        """
        client = self._ensure_client()
        return await client.post(
            path,
            json=json,
            data=data,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def put(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make authenticated PUT request.

        Args:
            path: Request path (relative to base_url)
            json: JSON body
            data: Form data
            headers: Additional headers
            **kwargs: Additional httpx arguments

        Returns:
            HTTP response
        """
        client = self._ensure_client()
        return await client.put(
            path,
            json=json,
            data=data,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make authenticated DELETE request.

        Args:
            path: Request path (relative to base_url)
            headers: Additional headers
            **kwargs: Additional httpx arguments

        Returns:
            HTTP response
        """
        client = self._ensure_client()
        return await client.delete(
            path,
            headers=self._get_headers(headers),
            **kwargs,
        )

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make authenticated request with any HTTP method.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path
            **kwargs: Additional httpx arguments

        Returns:
            HTTP response
        """
        client = self._ensure_client()
        headers = kwargs.pop("headers", None)
        return await client.request(
            method,
            path,
            headers=self._get_headers(headers),
            **kwargs,
        )

    def clear_token_cache(self) -> None:
        """Clear the cached service token, forcing a new one on next request."""
        self._token_cache = None
