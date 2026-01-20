"""Tests for CorrelatedHttpClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ..context import (
    CorrelationContext,
    clear_correlation_context,
    set_correlation_context,
)
from ..http_client import CorrelatedHttpClient, create_service_client


@pytest.fixture
def correlation_context():
    """Set up correlation context for tests."""
    ctx = CorrelationContext(
        request_id="req-123",
        trace_id="trace-456",
        tenant_id="tenant-789",
        user_id_hash="abc123",
    )
    set_correlation_context(ctx)
    yield ctx
    clear_correlation_context()


class TestCorrelatedHttpClient:
    """Tests for CorrelatedHttpClient."""

    @pytest.mark.asyncio
    async def test_get_includes_correlation_headers(self, correlation_context):
        """Should include correlation headers in GET requests."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test")

            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["X-Request-ID"] == "req-123"
            assert headers["X-Trace-ID"] == "trace-456"
            assert headers["X-Tenant-ID"] == "tenant-789"
            assert headers["X-User-ID-Hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_post_includes_correlation_headers(self, correlation_context):
        """Should include correlation headers in POST requests."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            async with client:
                await client.post("/test", json={"data": "value"})

            call_kwargs = mock_post.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["X-Request-ID"] == "req-123"

    @pytest.mark.asyncio
    async def test_merges_extra_headers(self, correlation_context):
        """Should merge extra headers with correlation headers."""
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test", headers={"Authorization": "Bearer token"})

            call_kwargs = mock_get.call_args[1]
            headers = call_kwargs.get("headers", {})
            assert headers["Authorization"] == "Bearer token"
            assert headers["X-Request-ID"] == "req-123"

    @pytest.mark.asyncio
    async def test_works_without_correlation_context(self):
        """Should work when no correlation context is set."""
        clear_correlation_context()
        client = CorrelatedHttpClient(base_url="http://test.local")

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_get.return_value = mock_response

            async with client:
                await client.get("/test")

            # Should not raise


class TestCreateServiceClient:
    """Tests for create_service_client factory."""

    def test_creates_client_with_correct_base_url(self):
        """Should create client with correct base URL."""
        client = create_service_client(service_name="retrieval", base_url="http://retrieval:8002")

        assert client.base_url == "http://retrieval:8002"
        assert client.timeout == 30.0

    def test_creates_client_with_custom_timeout(self):
        """Should allow custom timeout."""
        client = create_service_client(
            service_name="retrieval", base_url="http://retrieval:8002", timeout=60.0
        )

        assert client.timeout == 60.0
