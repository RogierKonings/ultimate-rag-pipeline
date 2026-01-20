"""HTTP client that automatically propagates correlation headers."""

from __future__ import annotations

from typing import Any

import httpx

from .context import get_correlation_context


class CorrelatedHttpClient:
    """HTTP client that auto-propagates correlation headers."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._client_kwargs = kwargs
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> CorrelatedHttpClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            **self._client_kwargs,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Build headers with correlation context merged with extra headers."""
        headers = dict(extra_headers) if extra_headers else {}
        ctx = get_correlation_context()
        if ctx:
            headers.update(ctx.to_headers())
        return headers

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform GET request with correlation headers."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with statement.")
        return await self._client.get(
            path, params=params, headers=self._get_headers(headers), **kwargs
        )

    async def post(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform POST request with correlation headers."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with statement.")
        return await self._client.post(
            path, json=json, data=data, headers=self._get_headers(headers), **kwargs
        )

    async def put(
        self,
        path: str,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform PUT request with correlation headers."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with statement.")
        return await self._client.put(
            path, json=json, data=data, headers=self._get_headers(headers), **kwargs
        )

    async def delete(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform DELETE request with correlation headers."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with statement.")
        return await self._client.delete(
            path, headers=self._get_headers(headers), **kwargs
        )


def create_service_client(
    service_name: str,
    base_url: str,
    timeout: float = 30.0,
    **kwargs: Any,
) -> CorrelatedHttpClient:
    """Factory function to create a correlated HTTP client for a service.

    Args:
        service_name: Name of the target service (for logging/metrics).
        base_url: Base URL of the service.
        timeout: Request timeout in seconds.
        **kwargs: Additional arguments passed to httpx.AsyncClient.

    Returns:
        A CorrelatedHttpClient instance.
    """
    return CorrelatedHttpClient(base_url=base_url, timeout=timeout, **kwargs)
