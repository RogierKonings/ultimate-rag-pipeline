"""LLM Gateway client for embedding generation."""


import httpx
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from .models import EmbeddingServiceConfig


class LLMGatewayError(Exception):
    """Exception raised for LLM Gateway errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LLMGatewayClient:
    """
    Client for interacting with the LLM Gateway.

    Handles HTTP communication with the embedding endpoint,
    including retry logic with exponential backoff.
    """

    def __init__(self, config: EmbeddingServiceConfig):
        """
        Initialize the LLM Gateway client.

        Args:
            config: Service configuration with gateway URL and retry settings.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Create HTTP client connection."""
        self._client = httpx.AsyncClient(
            base_url=self.config.llm_gateway_url,
            timeout=self.config.timeout_seconds,
        )

    async def disconnect(self) -> None:
        """Close HTTP client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_connected(self) -> None:
        """Ensure HTTP client is connected."""
        if not self._client:
            await self.connect()

    def _create_retry_decorator(self):
        """Create retry decorator with configured settings."""
        return retry(
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(
                multiplier=1,
                min=self.config.retry_min_wait,
                max=self.config.retry_max_wait,
            ),
            reraise=True,
        )

    async def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """
        Generate embeddings for a batch of texts.

        Uses the OpenAI-compatible API format supported by the LLM Gateway.

        Args:
            texts: List of text strings to embed.

        Returns:
            Tuple of (embeddings list, total tokens used).

        Raises:
            LLMGatewayError: If the API request fails after retries.
        """
        await self._ensure_connected()

        @self._create_retry_decorator()
        async def _request():
            response = await self._client.post(
                self.config.embedding_endpoint,
                json={"input": texts, "model": self.config.model},
            )
            response.raise_for_status()
            return response.json()

        try:
            data = await _request()
        except httpx.HTTPStatusError as e:
            raise LLMGatewayError(
                f"LLM Gateway request failed: {e.response.text}",
                status_code=e.response.status_code,
            ) from e
        except RetryError as e:
            raise LLMGatewayError(
                f"LLM Gateway request failed after {self.config.max_retries} retries",
            ) from e

        embeddings = [item["embedding"] for item in data["data"]]
        total_tokens = data.get("usage", {}).get("total_tokens", 0)

        return embeddings, total_tokens

    async def health_check(self) -> bool:
        """
        Check if the LLM Gateway is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        await self._ensure_connected()

        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def __aenter__(self) -> "LLMGatewayClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
