"""Tests for the LLM Gateway client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ..client import LLMGatewayClient, LLMGatewayError
from ..models import EmbeddingServiceConfig


class TestLLMGatewayClient:
    """Tests for LLMGatewayClient."""

    @pytest.fixture
    def client_config(self) -> EmbeddingServiceConfig:
        """Create test configuration."""
        return EmbeddingServiceConfig(
            llm_gateway_url="http://localhost:8004",
            embedding_endpoint="/v1/embeddings",
            model="BAAI/bge-large-en-v1.5",
            max_retries=3,
            retry_min_wait=0.1,
            retry_max_wait=0.5,
            timeout_seconds=30.0,
        )

    @pytest.fixture
    def mock_response(self):
        """Create mock successful response."""
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": [
                {"embedding": [0.1] * 1024},
                {"embedding": [0.2] * 1024},
            ],
            "usage": {"total_tokens": 150},
        }
        response.raise_for_status = MagicMock()
        return response

    @pytest.mark.asyncio
    async def test_embed_batch_returns_embeddings(
        self,
        client_config: EmbeddingServiceConfig,
        mock_response,
    ):
        """Test that embed_batch returns embeddings correctly."""
        client = LLMGatewayClient(client_config)

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        embeddings, tokens = await client.embed_batch(["text1", "text2"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 1024
        assert tokens == 150

    @pytest.mark.asyncio
    async def test_embed_batch_sends_correct_request(
        self,
        client_config: EmbeddingServiceConfig,
        mock_response,
    ):
        """Test that embed_batch sends correct request format."""
        client = LLMGatewayClient(client_config)

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        await client.embed_batch(["text1", "text2"])

        mock_http_client.post.assert_called_once_with(
            "/v1/embeddings",
            json={
                "input": ["text1", "text2"],
                "model": "BAAI/bge-large-en-v1.5",
            },
        )

    @pytest.mark.asyncio
    async def test_embed_batch_handles_missing_usage(
        self,
        client_config: EmbeddingServiceConfig,
    ):
        """Test that embed_batch handles missing usage field."""
        client = LLMGatewayClient(client_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1024}],
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        embeddings, tokens = await client.embed_batch(["text1"])

        assert len(embeddings) == 1
        assert tokens == 0  # Default when usage is missing

    @pytest.mark.asyncio
    async def test_embed_batch_raises_on_http_error(
        self,
        client_config: EmbeddingServiceConfig,
    ):
        """Test that embed_batch raises LLMGatewayError on HTTP errors."""
        client_config.max_retries = 1
        client_config.retry_min_wait = 0.01
        client = LLMGatewayClient(client_config)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        error = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=mock_response,
        )
        mock_response.raise_for_status = MagicMock(side_effect=error)

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        with pytest.raises(LLMGatewayError) as exc_info:
            await client.embed_batch(["text1"])

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(
        self,
        client_config: EmbeddingServiceConfig,
    ):
        """Test that health_check returns True when healthy."""
        client = LLMGatewayClient(client_config)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        client._client = mock_http_client

        result = await client.health_check()

        assert result is True
        mock_http_client.get.assert_called_once_with("/health")

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_failure(
        self,
        client_config: EmbeddingServiceConfig,
    ):
        """Test that health_check returns False when unhealthy."""
        client = LLMGatewayClient(client_config)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        client._client = mock_http_client

        result = await client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_context_manager(self, client_config: EmbeddingServiceConfig):
        """Test async context manager."""
        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_async_client.return_value = mock_instance

            async with LLMGatewayClient(client_config) as client:
                assert client._client is not None

            mock_instance.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_connected_creates_client(
        self,
        client_config: EmbeddingServiceConfig,
    ):
        """Test that _ensure_connected creates client when needed."""
        client = LLMGatewayClient(client_config)
        assert client._client is None

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_instance = AsyncMock()
            mock_async_client.return_value = mock_instance

            await client._ensure_connected()

            assert client._client is not None
            mock_async_client.assert_called_once()


class TestLLMGatewayError:
    """Tests for LLMGatewayError."""

    def test_error_with_status_code(self):
        """Test error creation with status code."""
        error = LLMGatewayError("Test error", status_code=500)
        assert str(error) == "Test error"
        assert error.status_code == 500

    def test_error_without_status_code(self):
        """Test error creation without status code."""
        error = LLMGatewayError("Test error")
        assert str(error) == "Test error"
        assert error.status_code is None
