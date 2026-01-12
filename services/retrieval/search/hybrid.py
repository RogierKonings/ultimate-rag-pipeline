"""Hybrid search orchestrator combining semantic and keyword search."""

import asyncio
import time
from uuid import UUID

from search.base import BaseSearcher
from search.fusion import (
    DistributionBasedScoreFusion,
    FusedResult,
    FusionMethod,
    HybridSearchConfig,
    HybridSearchResponse,
    LinearFusion,
    ReciprocalRankFusion,
)
from search.keyword import KeywordSearcher
from search.semantic import SemanticSearcher


class HybridSearcher(BaseSearcher):
    """
    Orchestrates hybrid search by running semantic and keyword
    search in parallel, then fusing results.
    """

    def __init__(
        self,
        semantic_searcher: SemanticSearcher,
        keyword_searcher: KeywordSearcher,
        config: HybridSearchConfig | None = None,
    ):
        """
        Initialize hybrid searcher.

        Args:
            semantic_searcher: Qdrant semantic search client
            keyword_searcher: OpenSearch keyword search client
            config: Hybrid search configuration
        """
        self.semantic = semantic_searcher
        self.keyword = keyword_searcher
        self.config = config or HybridSearchConfig()

        # Initialize fusion algorithm
        self._fusion = self._create_fusion(self.config)

    def _create_fusion(
        self, config: HybridSearchConfig,
    ) -> ReciprocalRankFusion | LinearFusion | DistributionBasedScoreFusion:
        """Create fusion algorithm based on config."""
        if config.fusion_method == FusionMethod.RRF:
            return ReciprocalRankFusion(k=config.rrf_k)
        if config.fusion_method in (FusionMethod.LINEAR, FusionMethod.CONVEX):
            return LinearFusion(
                semantic_weight=config.semantic_weight,
                keyword_weight=config.keyword_weight,
            )
        if config.fusion_method == FusionMethod.DBSF:
            return DistributionBasedScoreFusion(
                semantic_weight=config.semantic_weight,
                keyword_weight=config.keyword_weight,
            )
        raise ValueError(f"Unknown fusion method: {config.fusion_method}")

    async def connect(self) -> None:
        """Connect to both search backends."""
        await asyncio.gather(self.semantic.connect(), self.keyword.connect())

    async def close(self) -> None:
        """Close connections to both search backends."""
        await asyncio.gather(self.semantic.close(), self.keyword.close())

    async def health_check(self) -> bool:
        """Check health of both search backends."""
        try:
            results = await asyncio.gather(
                self.semantic.health_check(),
                self.keyword.health_check(),
                return_exceptions=True,
            )
            return all(r is True for r in results)
        except Exception:
            return False

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int | None = None,
        filters: dict | None = None,
        config: HybridSearchConfig | None = None,
    ) -> HybridSearchResponse:
        """
        Execute hybrid search combining semantic and keyword search.

        Args:
            query: Text query for keyword search
            query_embedding: Query embedding for semantic search
            top_k: Number of final results (overrides config)
            filters: ACL and metadata filters
            config: Override default config for this search

        Returns:
            HybridSearchResponse with fused results
        """
        start_time = time.time()

        # Use provided config or default
        cfg = config or self.config
        final_top_k = top_k or cfg.top_k

        # Create fusion for this config
        fusion = self._create_fusion(cfg) if config else self._fusion

        # Run both searches in parallel
        semantic_task = self.semantic.search(
            query_embedding=query_embedding,
            top_k=cfg.semantic_top_k,
            filters=filters,
            score_threshold=0.0,
        )

        keyword_task = self.keyword.search(
            query=query,
            top_k=cfg.keyword_top_k,
            filters=filters,
            min_score=0.0,
        )

        semantic_response, keyword_response = await asyncio.gather(
            semantic_task,
            keyword_task,
        )

        # Fuse results
        fused_results = fusion.fuse(
            semantic_results=semantic_response.results,
            keyword_results=keyword_response.results,
            top_k=final_top_k,
        )

        # Apply score threshold
        if cfg.min_score > 0:
            fused_results = [r for r in fused_results if r.fused_score >= cfg.min_score]

        # Deduplicate if needed (by document_id, keeping highest scored chunk)
        if cfg.deduplicate:
            fused_results = self._deduplicate(fused_results)

        search_time = (time.time() - start_time) * 1000

        return HybridSearchResponse(
            results=fused_results,
            total_semantic=semantic_response.total_found,
            total_keyword=keyword_response.total_found,
            search_time_ms=search_time,
            fusion_method=cfg.fusion_method,
        )

    def _deduplicate(self, results: list[FusedResult]) -> list[FusedResult]:
        """
        Remove duplicate chunks from the same document.

        Keeps the highest-scored chunk from each document.
        """
        seen_docs: dict[UUID, FusedResult] = {}

        for result in results:
            doc_id = result.document_id
            if doc_id not in seen_docs or result.fused_score > seen_docs[doc_id].fused_score:
                seen_docs[doc_id] = result

        # Maintain score order
        return sorted(seen_docs.values(), key=lambda r: r.fused_score, reverse=True)

    async def search_semantic_only(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> HybridSearchResponse:
        """
        Bypass hybrid fusion and use semantic search only.

        Useful for queries where exact keywords don't matter.
        """
        start_time = time.time()

        response = await self.semantic.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters,
        )

        # Convert to FusedResult format
        fused_results = [
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

        search_time = (time.time() - start_time) * 1000

        return HybridSearchResponse(
            results=fused_results,
            total_semantic=response.total_found,
            total_keyword=0,
            search_time_ms=search_time,
            fusion_method=FusionMethod.RRF,  # N/A but required
        )

    async def search_keyword_only(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> HybridSearchResponse:
        """
        Bypass hybrid fusion and use keyword search only.

        Useful for exact term lookups.
        """
        start_time = time.time()

        response = await self.keyword.search(
            query=query,
            top_k=top_k,
            filters=filters,
        )

        # Convert to FusedResult format
        fused_results = [
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

        search_time = (time.time() - start_time) * 1000

        return HybridSearchResponse(
            results=fused_results,
            total_semantic=0,
            total_keyword=response.total_found,
            search_time_ms=search_time,
            fusion_method=FusionMethod.RRF,
        )

    async def get_backend_info(self) -> dict:
        """Get information about both search backends."""
        try:
            semantic_info = await self.semantic.get_collection_info()
        except Exception as e:
            semantic_info = {"error": str(e)}

        try:
            keyword_info = await self.keyword.get_index_info()
        except Exception as e:
            keyword_info = {"error": str(e)}

        return {
            "semantic": semantic_info,
            "keyword": keyword_info,
            "config": {
                "fusion_method": self.config.fusion_method.value,
                "semantic_weight": self.config.semantic_weight,
                "keyword_weight": self.config.keyword_weight,
                "rrf_k": self.config.rrf_k,
            },
        }
