"""
Embedding service client.

Handles communication with the embedding service for vector generation.
"""

import base64
import logging
import struct
import time

import httpx

from ..models import EmbeddingData, EmbeddingRequest, EmbeddingResponse, Usage

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for embedding service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        timeout: float = 30.0,
        default_model: str = "BAAI/bge-large-en-v1.5",
    ):
        """
        Initialize embedding client.

        Args:
            base_url: Base URL of the embedding service
            timeout: Request timeout in seconds
            default_model: Default model name
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_model = default_model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health_check(self) -> bool:
        """Check if embedding service is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Embedding health check failed: {e}")
            return False

    async def get_model_info(self) -> dict | None:
        """Get model information."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return None

    async def create_embeddings(
        self,
        request: EmbeddingRequest,
        context_headers: dict[str, str] | None = None,
    ) -> EmbeddingResponse:
        """
        Create embeddings for the given input.

        Args:
            request: Embedding request
            context_headers: Additional headers to pass

        Returns:
            Embedding response
        """
        client = await self._get_client()
        start_time = time.time()

        # Normalize input to list
        texts = request.input if isinstance(request.input, list) else [request.input]

        # Build request payload
        payload = {
            "texts": texts,
            "normalize": True,
        }

        headers = {"Content-Type": "application/json"}
        if context_headers:
            headers.update(context_headers)

        try:
            response = await client.post(
                "/embed",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            # Process embeddings
            embeddings_data = []
            raw_embeddings = data.get("embeddings", [])

            for i, emb in enumerate(raw_embeddings):
                if request.encoding_format == "base64":
                    # Convert float list to base64
                    packed = struct.pack(f"{len(emb)}f", *emb)
                    embedding_value = base64.b64encode(packed).decode("utf-8")
                else:
                    embedding_value = emb

                embeddings_data.append(
                    EmbeddingData(
                        index=i,
                        embedding=embedding_value,
                    ),
                )

            # Calculate token usage (approximate)
            total_tokens = sum(len(text.split()) * 1.3 for text in texts)

            latency_ms = (time.time() - start_time) * 1000
            logger.debug(
                f"Created {len(embeddings_data)} embeddings in {latency_ms:.1f}ms",
            )

            return EmbeddingResponse(
                data=embeddings_data,
                model=request.model or self.default_model,
                usage=Usage(
                    prompt_tokens=int(total_tokens),
                    total_tokens=int(total_tokens),
                ),
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Embedding request failed: {e.response.status_code} - {e.response.text}",
            )
            raise
        except Exception as e:
            logger.error(f"Embedding request error: {e}")
            raise

    async def create_embeddings_batch(
        self,
        texts: list[str],
        model: str | None = None,
        context_headers: dict[str, str] | None = None,
    ) -> list[list[float]]:
        """
        Create embeddings for a batch of texts.

        Args:
            texts: List of texts to embed
            model: Model to use
            context_headers: Additional headers

        Returns:
            List of embedding vectors
        """
        request = EmbeddingRequest(
            model=model or self.default_model,
            input=texts,
            encoding_format="float",
        )
        response = await self.create_embeddings(request, context_headers)
        return [item.embedding for item in response.data]
