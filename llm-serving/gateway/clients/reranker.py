"""
Reranker service client.

Handles communication with the reranker service for document ranking.
"""

import logging
import time

import httpx

from ..models import RerankRequest, RerankResponse, RerankResult, Usage

logger = logging.getLogger(__name__)


class RerankerClient:
    """Client for reranker service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        timeout: float = 30.0,
        default_model: str = "BAAI/bge-reranker-v2-m3",
    ):
        """
        Initialize reranker client.

        Args:
            base_url: Base URL of the reranker service
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
        """Check if reranker service is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Reranker health check failed: {e}")
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

    def _extract_document_text(self, doc: str | dict) -> str:
        """Extract text from document (string or dict with 'text' field)."""
        if isinstance(doc, str):
            return doc
        if isinstance(doc, dict):
            return doc.get("text", doc.get("content", str(doc)))
        return str(doc)

    async def rerank(
        self,
        request: RerankRequest,
        context_headers: dict[str, str] | None = None,
    ) -> RerankResponse:
        """
        Rerank documents against a query.

        Args:
            request: Rerank request
            context_headers: Additional headers to pass

        Returns:
            Rerank response with sorted results
        """
        client = await self._get_client()
        start_time = time.time()

        # Extract document texts
        document_texts = [
            self._extract_document_text(doc) for doc in request.documents
        ]

        # Build request payload
        payload = {
            "query": request.query,
            "documents": document_texts,
        }

        if request.top_n is not None:
            payload["top_n"] = request.top_n

        headers = {"Content-Type": "application/json"}
        if context_headers:
            headers.update(context_headers)

        try:
            response = await client.post(
                "/rerank",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            # Process results
            results = []
            for item in data.get("results", []):
                idx = item.get("index", 0)
                score = item.get("score", item.get("relevance_score", 0.0))

                result = RerankResult(
                    index=idx,
                    relevance_score=score,
                )

                # Include document text if requested
                if request.return_documents and idx < len(request.documents):
                    result.document = request.documents[idx]

                results.append(result)

            # Sort by relevance score (descending)
            results.sort(key=lambda x: x.relevance_score, reverse=True)

            # Apply top_n if specified
            if request.top_n is not None:
                results = results[: request.top_n]

            # Approximate token usage
            total_chars = len(request.query) + sum(len(d) for d in document_texts)
            total_tokens = int(total_chars / 4)  # Rough approximation

            latency_ms = (time.time() - start_time) * 1000
            logger.debug(
                f"Reranked {len(request.documents)} documents in {latency_ms:.1f}ms",
            )

            return RerankResponse(
                results=results,
                model=request.model or self.default_model,
                usage=Usage(
                    prompt_tokens=total_tokens,
                    total_tokens=total_tokens,
                ),
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Rerank request failed: {e.response.status_code} - {e.response.text}",
            )
            raise
        except Exception as e:
            logger.error(f"Rerank request error: {e}")
            raise

    async def rerank_simple(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
        context_headers: dict[str, str] | None = None,
    ) -> list[tuple[int, float]]:
        """
        Simple rerank interface returning (index, score) tuples.

        Args:
            query: Query text
            documents: List of document texts
            top_n: Number of top results to return
            context_headers: Additional headers

        Returns:
            List of (document_index, relevance_score) tuples sorted by score
        """
        request = RerankRequest(
            model=self.default_model,
            query=query,
            documents=documents,
            top_n=top_n,
            return_documents=False,
        )
        response = await self.rerank(request, context_headers)
        return [(r.index, r.relevance_score) for r in response.results]
