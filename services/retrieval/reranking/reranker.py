"""Cross-encoder reranking service."""

import time
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from reranking.exceptions import (
    RerankerConnectionError,
    RerankerTimeoutError,
    RerankerValidationError,
)
from reranking.models import RerankerConfig, RerankResponse, RerankResult

if TYPE_CHECKING:
    from search.fusion import FusedResult


class RerankerService:
    """
    Cross-encoder reranking service.

    Uses BGE-reranker-v2-m3 via LLM Gateway to score query-document
    pairs directly. Cross-encoders are more accurate than bi-encoders
    but slower, so we only rerank top candidates.

    The model jointly encodes query and document, attending to both
    simultaneously, which captures fine-grained relevance signals.
    """

    def __init__(self, config: RerankerConfig | None = None):
        """
        Initialize reranker service.

        Args:
            config: Reranker configuration
        """
        self.config = config or RerankerConfig()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.llm_gateway_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    async def rerank(
        self,
        query: str,
        documents: list[str],
        document_ids: list[UUID],
        top_k: int | None = None,
        return_documents: bool = False,
    ) -> RerankResponse:
        """
        Rerank documents by relevance to query.

        Args:
            query: Search query
            documents: List of document contents
            document_ids: Corresponding document/chunk IDs
            top_k: Number of top results to return (None = all)
            return_documents: Include document text in response

        Returns:
            RerankResponse with reordered results
        """
        start_time = time.time()

        # Validation
        if len(documents) != len(document_ids):
            raise RerankerValidationError(
                "documents and document_ids must have same length",
                details={
                    "documents_count": len(documents),
                    "ids_count": len(document_ids),
                },
            )

        if len(documents) > self.config.max_documents:
            raise RerankerValidationError(
                f"Too many documents: {len(documents)} > {self.config.max_documents}",
                details={"count": len(documents), "max": self.config.max_documents},
            )

        if not documents:
            return RerankResponse(
                results=[],
                model=self.config.model,
                processing_time_ms=0.0,
            )

        # Truncate query and documents if needed
        truncated_query = self._truncate(query, self.config.max_query_length)
        truncated_docs = [self._truncate(doc, self.config.max_document_length) for doc in documents]

        # Call reranker in batches if needed
        all_scores: list[float] = []
        for batch_start in range(0, len(truncated_docs), self.config.max_batch_size):
            batch_end = min(
                batch_start + self.config.max_batch_size,
                len(truncated_docs),
            )
            batch_docs = truncated_docs[batch_start:batch_end]

            batch_scores = await self._rerank_batch(truncated_query, batch_docs)
            all_scores.extend(batch_scores)

        # Build results with original indices
        results = []
        for idx, (doc_id, score) in enumerate(zip(document_ids, all_scores, strict=True)):
            if score >= self.config.score_threshold:
                results.append(
                    RerankResult(
                        document_id=doc_id,
                        index=idx,
                        relevance_score=score,
                        document=documents[idx] if return_documents else None,
                    ),
                )

        # Sort by score descending
        results.sort(key=lambda x: x.relevance_score, reverse=True)

        # Apply top_k limit
        if top_k is not None:
            results = results[:top_k]

        processing_time = (time.time() - start_time) * 1000

        return RerankResponse(
            results=results,
            model=self.config.model,
            processing_time_ms=processing_time,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _rerank_batch(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        """
        Call LLM Gateway rerank endpoint for a batch.

        The API is modeled after Cohere's rerank API format.
        """
        try:
            client = await self._get_client()
            response = await client.post(
                self.config.rerank_endpoint,
                json={
                    "model": self.config.model,
                    "query": query,
                    "documents": documents,
                    "return_documents": False,
                },
            )
            response.raise_for_status()

            data = response.json()

            # Extract scores, maintaining order
            # Response format: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
            scores = [0.0] * len(documents)
            for result in data["results"]:
                scores[result["index"]] = result["relevance_score"]

            return scores

        except httpx.TimeoutException as e:
            raise RerankerTimeoutError(
                f"Reranker request timed out: {e}",
                details={"timeout": self.config.timeout_seconds},
            ) from None
        except httpx.ConnectError as e:
            raise RerankerConnectionError(
                f"Failed to connect to reranker: {e}",
                details={"url": self.config.llm_gateway_url},
            ) from None

    def _truncate(self, text: str, max_length: int) -> str:
        """
        Truncate text to max length (approximate token count).

        Uses character-based estimation: ~4 chars per token.
        """
        max_chars = max_length * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    async def rerank_fused_results(
        self,
        query: str,
        fused_results: list["FusedResult"],
        top_k: int | None = None,
    ) -> list["FusedResult"]:
        """
        Convenience method to rerank FusedResult objects.

        Preserves all metadata and updates scores based on reranking.

        Args:
            query: Search query
            fused_results: Results from hybrid fusion
            top_k: Number of results to return

        Returns:
            Reranked FusedResult list with updated scores
        """
        if not fused_results:
            return []

        # Extract content and IDs
        documents = [r.content for r in fused_results]
        document_ids = [r.chunk_id for r in fused_results]

        # Rerank
        rerank_response = await self.rerank(
            query=query,
            documents=documents,
            document_ids=document_ids,
            top_k=top_k,
        )

        # Build ID to result mapping
        result_map = {r.chunk_id: r for r in fused_results}

        # Rebuild results with rerank scores
        reranked = []
        for rr in rerank_response.results:
            original = result_map[rr.document_id]
            # Create new result with rerank score
            reranked_result = original.model_copy()
            reranked_result.fused_score = rr.relevance_score
            reranked_result.metadata["rerank_score"] = rr.relevance_score
            reranked_result.metadata["original_fused_score"] = original.fused_score
            reranked.append(reranked_result)

        return reranked

    async def health_check(self) -> bool:
        """Check if reranker service is healthy."""
        try:
            # Try a simple rerank call
            await self._rerank_batch("test", ["test document"])
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RerankerService":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
