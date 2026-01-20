"""Resilient hybrid searcher with circuit breaker protection."""

import asyncio
import logging
import time

from resilience import (
    DegradationMode,
    RetrievalDegradationManager,
)

from search.fusion import FusedResult, FusionMethod, HybridSearchConfig, HybridSearchResponse
from search.hybrid import HybridSearcher

logger = logging.getLogger(__name__)


class ResilientHybridSearcher:
    """Hybrid searcher with resilience and degradation support.

    Wraps HybridSearcher with circuit breaker protection and automatically
    degrades to available components when backends fail.
    """

    def __init__(
        self,
        hybrid_searcher: HybridSearcher,
        degradation_manager: RetrievalDegradationManager,
    ):
        """Initialize resilient hybrid searcher.

        Args:
            hybrid_searcher: The underlying hybrid searcher
            degradation_manager: Manager for circuit breakers and degradation
        """
        self.hybrid = hybrid_searcher
        self.degradation = degradation_manager

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int | None = None,
        filters: dict | None = None,
        config: HybridSearchConfig | None = None,
        use_reranker: bool = True,
    ) -> HybridSearchResponse:
        """Execute hybrid search with degradation handling.

        Automatically uses available components based on circuit states.

        Args:
            query: Text query for keyword search
            query_embedding: Query embedding for semantic search
            top_k: Number of final results
            filters: ACL and metadata filters
            config: Override default hybrid config
            use_reranker: Whether to use reranker (if available)

        Returns:
            HybridSearchResponse with results and degradation info
        """
        start_time = time.time()
        mode = self.degradation.get_current_mode()
        status = self.degradation.get_status()

        logger.info(
            "search_starting",
            extra={
                "degradation_mode": mode.value,
                "components_available": status.components_available,
            },
        )

        cfg = config or self.hybrid.config
        final_top_k = top_k or cfg.top_k

        # Handle MINIMAL mode - return empty results
        if mode == DegradationMode.MINIMAL:
            logger.warning("both_search_backends_down", extra={"mode": mode.value})
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=(time.time() - start_time) * 1000,
                fusion_method=cfg.fusion_method,
                degradation_mode=mode.value,
                components_used=status.components_available,
                components_skipped=status.components_unavailable,
            )

        # Execute search based on degradation mode
        if mode == DegradationMode.SEMANTIC_ONLY:
            response = await self._search_semantic_with_circuit(
                query_embedding, final_top_k, filters
            )
        elif mode == DegradationMode.KEYWORD_ONLY:
            response = await self._search_keyword_with_circuit(
                query, final_top_k, filters
            )
        else:
            # HYBRID_FULL or HYBRID_NO_RERANK - run both searches
            response = await self._search_hybrid_with_circuits(
                query, query_embedding, final_top_k, filters, cfg
            )

        # Add degradation metadata to response
        search_time = (time.time() - start_time) * 1000

        return HybridSearchResponse(
            results=response.results,
            total_semantic=response.total_semantic,
            total_keyword=response.total_keyword,
            search_time_ms=search_time,
            fusion_method=response.fusion_method,
            degradation_mode=mode.value,
            components_used=status.components_available,
            components_skipped=status.components_unavailable,
        )

    async def _search_semantic_with_circuit(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
    ) -> HybridSearchResponse:
        """Execute semantic-only search with circuit breaker."""

        async def do_search() -> HybridSearchResponse:
            return await self.hybrid.search_semantic_only(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=filters,
            )

        async def fallback() -> HybridSearchResponse:
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=0,
                fusion_method=FusionMethod.RRF,
            )

        return await self.degradation.qdrant_breaker.call(do_search, fallback=fallback)

    async def _search_keyword_with_circuit(
        self,
        query: str,
        top_k: int,
        filters: dict | None,
    ) -> HybridSearchResponse:
        """Execute keyword-only search with circuit breaker."""

        async def do_search() -> HybridSearchResponse:
            return await self.hybrid.search_keyword_only(
                query=query,
                top_k=top_k,
                filters=filters,
            )

        async def fallback() -> HybridSearchResponse:
            return HybridSearchResponse(
                results=[],
                total_semantic=0,
                total_keyword=0,
                search_time_ms=0,
                fusion_method=FusionMethod.RRF,
            )

        return await self.degradation.opensearch_breaker.call(
            do_search, fallback=fallback
        )

    async def _search_hybrid_with_circuits(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
        config: HybridSearchConfig,
    ) -> HybridSearchResponse:
        """Execute full hybrid search with circuit breakers on both backends."""

        async def do_semantic() -> list[FusedResult]:
            response = await self.hybrid.semantic.search(
                query_embedding=query_embedding,
                top_k=config.semantic_top_k,
                filters=filters,
            )
            # Convert to FusedResult format
            return [
                FusedResult(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    content=r.content,
                    fused_score=r.score,
                    semantic_score=r.score,
                    semantic_rank=i + 1,
                    metadata=r.metadata,
                    title=r.title,
                    source=r.source,
                )
                for i, r in enumerate(response.results)
            ]

        async def do_keyword() -> list[FusedResult]:
            response = await self.hybrid.keyword.search(
                query=query,
                top_k=config.keyword_top_k,
                filters=filters,
            )
            return [
                FusedResult(
                    chunk_id=r.chunk_id,
                    document_id=r.document_id,
                    content=r.content,
                    fused_score=r.score,
                    keyword_score=r.score,
                    keyword_rank=i + 1,
                    metadata=r.metadata,
                    title=r.title,
                    source=r.source,
                )
                for i, r in enumerate(response.results)
            ]

        async def empty_fallback() -> list[FusedResult]:
            return []

        # Run both with circuit breakers
        semantic_task = self.degradation.qdrant_breaker.call(
            do_semantic, fallback=empty_fallback
        )
        keyword_task = self.degradation.opensearch_breaker.call(
            do_keyword, fallback=empty_fallback
        )

        semantic_results, keyword_results = await asyncio.gather(
            semantic_task, keyword_task
        )

        # Fuse results
        if semantic_results and keyword_results:
            fused = self.hybrid._fusion.fuse(
                semantic_results=semantic_results,
                keyword_results=keyword_results,
                top_k=top_k,
            )
        else:
            fused = semantic_results or keyword_results

        return HybridSearchResponse(
            results=fused[:top_k],
            total_semantic=len(semantic_results),
            total_keyword=len(keyword_results),
            search_time_ms=0,  # Will be set by caller
            fusion_method=config.fusion_method,
        )

    async def connect(self) -> None:
        """Connect to search backends."""
        await self.hybrid.connect()

    async def close(self) -> None:
        """Close connections to search backends."""
        await self.hybrid.close()

    async def health_check(self) -> bool:
        """Check health of search backends."""
        return await self.hybrid.health_check()
