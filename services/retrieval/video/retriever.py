"""Video retriever service with hybrid search.

This module provides the VideoRetriever class that orchestrates
hybrid search for video chunks, combining semantic and keyword
search with RRF fusion and result grouping.
"""

import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from opensearchpy import OpenSearch
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)

from video.exceptions import VideoSearchError
from video.models import (
    VideoMatch,
    VideoResult,
    VideoSearchMetrics,
    VideoSearchMode,
    VideoTimelineResponse,
)

logger = logging.getLogger(__name__)

# Default configuration constants
VIDEO_CHUNKS_QDRANT_COLLECTION = "video_chunks"
VIDEO_CHUNKS_OPENSEARCH_INDEX = "video_chunks"
RRF_K = 60
DEFAULT_SEMANTIC_TOP_K = 50
DEFAULT_KEYWORD_TOP_K = 50
DEFAULT_RERANK_TOP_K = 50
DEFAULT_FINAL_TOP_K = 10
DEFAULT_MAX_MATCHES_PER_VIDEO = 10


@dataclass
class VideoRetrieverConfig:
    """Configuration for video retriever.

    Attributes:
        qdrant_url: Qdrant server URL.
        qdrant_collection: Collection name for video chunks.
        opensearch_url: OpenSearch URL.
        opensearch_index: Index name for video chunks.
        semantic_top_k: Results to retrieve from semantic search.
        keyword_top_k: Results to retrieve from keyword search.
        rerank_top_k: Results to pass through reranker.
        final_top_k: Final results to return.
        semantic_weight: Weight for semantic results in fusion.
        keyword_weight: Weight for keyword results in fusion.
        rrf_k: RRF constant.
        enable_reranking: Whether to apply reranking.
        max_matches_per_video: Maximum matches per video in response.
        keyframe_base_url: Base URL for keyframe images.
        clip_base_url: Base URL for video clips.
    """

    qdrant_url: str = ""
    qdrant_collection: str = VIDEO_CHUNKS_QDRANT_COLLECTION
    opensearch_url: str = ""
    opensearch_index: str = VIDEO_CHUNKS_OPENSEARCH_INDEX
    opensearch_username: str = ""
    opensearch_password: str = ""
    semantic_top_k: int = DEFAULT_SEMANTIC_TOP_K
    keyword_top_k: int = DEFAULT_KEYWORD_TOP_K
    rerank_top_k: int = DEFAULT_RERANK_TOP_K
    final_top_k: int = DEFAULT_FINAL_TOP_K
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3
    rrf_k: int = RRF_K
    enable_reranking: bool = True
    max_matches_per_video: int = DEFAULT_MAX_MATCHES_PER_VIDEO
    keyframe_base_url: str = ""
    clip_base_url: str = ""

    def __post_init__(self):
        if not self.qdrant_url:
            self.qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        if not self.opensearch_url:
            self.opensearch_url = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
        if not self.opensearch_username:
            self.opensearch_username = os.getenv("OPENSEARCH_USERNAME", "")
        if not self.opensearch_password:
            self.opensearch_password = os.getenv("OPENSEARCH_PASSWORD", "")


@dataclass
class SearchResult:
    """Internal search result representation."""

    chunk_id: UUID
    video_id: UUID
    tenant_id: UUID
    chunk_index: int
    start_time_ms: int
    end_time_ms: int
    score: float
    rank: int
    fused_text: str = ""
    transcript_text: str = ""
    scene_description: str = ""
    ocr_text: str = ""
    video_title: str = ""
    visibility: str = "private"
    allowed_groups: list[str] = field(default_factory=list)
    source_modalities: list[str] = field(default_factory=list)
    keyframe_path: str | None = None


class VideoRetriever:
    """Orchestrates video chunk retrieval with hybrid search.

    Combines Qdrant semantic search with OpenSearch keyword search
    using RRF fusion, optional reranking, and video-based grouping.

    Example:
        retriever = VideoRetriever()
        response = await retriever.search(
            query="machine learning tutorial",
            query_embedding=embedding_vector,
            tenant_id=tenant_uuid,
        )
    """

    def __init__(
        self,
        config: VideoRetrieverConfig | None = None,
        reranker=None,
    ):
        """Initialize video retriever.

        Args:
            config: Retriever configuration.
            reranker: Optional RerankerService instance for reranking.
        """
        self.config = config or VideoRetrieverConfig()
        self._qdrant: QdrantClient | None = None
        self._opensearch: OpenSearch | None = None
        self._reranker = reranker

    @property
    def qdrant(self) -> QdrantClient:
        """Get or create Qdrant client."""
        if self._qdrant is None:
            self._qdrant = QdrantClient(
                url=self.config.qdrant_url,
                timeout=30,
            )
        return self._qdrant

    @property
    def opensearch(self) -> OpenSearch:
        """Get or create OpenSearch client."""
        if self._opensearch is None:
            http_auth = None
            if self.config.opensearch_username and self.config.opensearch_password:
                http_auth = (
                    self.config.opensearch_username,
                    self.config.opensearch_password,
                )

            self._opensearch = OpenSearch(
                hosts=[self.config.opensearch_url],
                http_auth=http_auth,
                timeout=30,
            )
        return self._opensearch

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        tenant_id: UUID,
        mode: VideoSearchMode = VideoSearchMode.HYBRID,
        top_k: int | None = None,
        video_id: UUID | None = None,
        allowed_groups: list[str] | None = None,
        semantic_weight: float | None = None,
        keyword_weight: float | None = None,
        enable_reranking: bool | None = None,
    ) -> VideoTimelineResponse:
        """Execute video search with hybrid retrieval.

        Args:
            query: Search query text.
            query_embedding: Query embedding vector (1024 dims).
            tenant_id: Tenant UUID for filtering.
            mode: Search mode (hybrid, semantic, keyword).
            top_k: Override default final_top_k.
            video_id: Optional filter to specific video.
            allowed_groups: User's groups for ACL filtering.
            semantic_weight: Override semantic weight.
            keyword_weight: Override keyword weight.
            enable_reranking: Override reranking setting.

        Returns:
            VideoTimelineResponse with grouped results.
        """
        start_time = time.time()
        metrics = VideoSearchMetrics()

        final_top_k = top_k or self.config.final_top_k
        sem_weight = semantic_weight or self.config.semantic_weight
        kw_weight = keyword_weight or self.config.keyword_weight
        do_rerank = (
            enable_reranking if enable_reranking is not None else self.config.enable_reranking
        )

        try:
            # Execute search based on mode
            if mode == VideoSearchMode.SEMANTIC:
                results = await self._semantic_search(
                    query_embedding=query_embedding,
                    tenant_id=tenant_id,
                    top_k=final_top_k * 2,  # Get more for grouping
                    video_id=video_id,
                    allowed_groups=allowed_groups,
                    metrics=metrics,
                )
                metrics.keyword_count = 0
            elif mode == VideoSearchMode.KEYWORD:
                results = await self._keyword_search(
                    query=query,
                    tenant_id=tenant_id,
                    top_k=final_top_k * 2,
                    video_id=video_id,
                    allowed_groups=allowed_groups,
                    metrics=metrics,
                )
                metrics.semantic_count = 0
            else:  # HYBRID
                results = await self._hybrid_search(
                    query=query,
                    query_embedding=query_embedding,
                    tenant_id=tenant_id,
                    video_id=video_id,
                    allowed_groups=allowed_groups,
                    sem_weight=sem_weight,
                    kw_weight=kw_weight,
                    metrics=metrics,
                )

            metrics.fused_count = len(results)

            # Rerank if enabled
            if do_rerank and self._reranker and results:
                rerank_start = time.time()
                results = await self._rerank_results(
                    query=query,
                    results=results[: self.config.rerank_top_k],
                )
                metrics.rerank_ms = (time.time() - rerank_start) * 1000

            # Group by video and format response
            group_start = time.time()
            video_results = self._group_and_format(
                results=results,
                max_per_video=self.config.max_matches_per_video,
                max_videos=final_top_k,
            )
            metrics.grouping_ms = (time.time() - group_start) * 1000

            # Calculate totals
            total_matches = sum(v.match_count for v in video_results)
            metrics.final_count = total_matches
            metrics.total_ms = (time.time() - start_time) * 1000

            return VideoTimelineResponse(
                query=query,
                mode=mode,
                videos=video_results,
                total_videos=len(video_results),
                total_matches=total_matches,
                metrics=metrics,
            )

        except Exception as e:
            logger.exception("Video search failed: %s", e)
            raise VideoSearchError(f"Search failed: {e}") from e

    async def _semantic_search(
        self,
        query_embedding: list[float],
        tenant_id: UUID,
        top_k: int,
        video_id: UUID | None,
        allowed_groups: list[str] | None,
        metrics: VideoSearchMetrics,
    ) -> list[SearchResult]:
        """Execute semantic search on Qdrant.

        Args:
            query_embedding: Query vector.
            tenant_id: Tenant filter.
            top_k: Number of results.
            video_id: Optional video filter.
            allowed_groups: ACL groups.
            metrics: Metrics object to update.

        Returns:
            List of SearchResult objects.
        """
        start_time = time.time()

        # Build filter
        must_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=str(tenant_id)),
            ),
        ]

        if video_id:
            must_conditions.append(
                FieldCondition(
                    key="video_id",
                    match=MatchValue(value=str(video_id)),
                )
            )

        # ACL filter: public OR in allowed_groups
        should_conditions = [
            FieldCondition(
                key="visibility",
                match=MatchValue(value="public"),
            ),
        ]
        if allowed_groups:
            should_conditions.append(
                FieldCondition(
                    key="allowed_groups",
                    match=MatchAny(any=allowed_groups),
                )
            )

        query_filter = Filter(
            must=must_conditions,
            should=should_conditions,
        )

        response = self.qdrant.query_points(
            collection_name=self.config.qdrant_collection,
            query=query_embedding,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

        metrics.semantic_search_ms = (time.time() - start_time) * 1000
        metrics.semantic_count = len(response.points)

        results = []
        for rank, hit in enumerate(response.points, start=1):
            payload = hit.payload or {}
            results.append(
                SearchResult(
                    chunk_id=UUID(str(hit.id)),
                    video_id=UUID(payload.get("video_id", str(UUID(int=0)))),
                    tenant_id=UUID(payload.get("tenant_id", str(tenant_id))),
                    chunk_index=payload.get("chunk_index", 0),
                    start_time_ms=payload.get("start_time_ms", 0),
                    end_time_ms=payload.get("end_time_ms", 0),
                    score=hit.score or 0.0,
                    rank=rank,
                    fused_text=payload.get("fused_text", ""),
                    video_title=payload.get("video_title", ""),
                    visibility=payload.get("visibility", "private"),
                    allowed_groups=payload.get("allowed_groups", []),
                    source_modalities=payload.get("source_modalities", []),
                    keyframe_path=payload.get("keyframe_path"),
                )
            )

        return results

    async def _keyword_search(
        self,
        query: str,
        tenant_id: UUID,
        top_k: int,
        video_id: UUID | None,
        allowed_groups: list[str] | None,
        metrics: VideoSearchMetrics,
    ) -> list[SearchResult]:
        """Execute keyword search on OpenSearch.

        Args:
            query: Search query text.
            tenant_id: Tenant filter.
            top_k: Number of results.
            video_id: Optional video filter.
            allowed_groups: ACL groups.
            metrics: Metrics object to update.

        Returns:
            List of SearchResult objects.
        """
        start_time = time.time()

        # Build query with field boosting
        must = [
            {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "fused_text^1.0",
                        "transcript_text^1.2",
                        "scene_description^0.8",
                        "ocr_text^0.6",
                        "video_title^1.5",
                    ],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                },
            },
        ]

        # Filter clauses
        filter_clauses = [
            {"term": {"tenant_id": str(tenant_id)}},
        ]

        if video_id:
            filter_clauses.append({"term": {"video_id": str(video_id)}})

        # ACL filter
        if allowed_groups:
            filter_clauses.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"visibility": "public"}},
                            {"terms": {"allowed_groups": allowed_groups}},
                        ],
                        "minimum_should_match": 1,
                    },
                }
            )

        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must,
                    "filter": filter_clauses,
                },
            },
            "_source": True,
        }

        response = self.opensearch.search(
            index=self.config.opensearch_index,
            body=body,
        )

        metrics.keyword_search_ms = (time.time() - start_time) * 1000
        metrics.keyword_count = len(response["hits"]["hits"])

        # Normalize BM25 scores to 0-1 range
        max_score = response["hits"]["max_score"] or 1.0

        results = []
        for rank, hit in enumerate(response["hits"]["hits"], start=1):
            source = hit["_source"]
            normalized_score = (hit["_score"] or 0) / max_score

            results.append(
                SearchResult(
                    chunk_id=UUID(source.get("chunk_id", hit["_id"])),
                    video_id=UUID(source.get("video_id", str(UUID(int=0)))),
                    tenant_id=UUID(source.get("tenant_id", str(tenant_id))),
                    chunk_index=source.get("chunk_index", 0),
                    start_time_ms=source.get("start_time_ms", 0),
                    end_time_ms=source.get("end_time_ms", 0),
                    score=normalized_score,
                    rank=rank,
                    fused_text=source.get("fused_text", ""),
                    transcript_text=source.get("transcript_text", ""),
                    scene_description=source.get("scene_description", ""),
                    ocr_text=source.get("ocr_text", ""),
                    video_title=source.get("video_title", ""),
                    visibility=source.get("visibility", "private"),
                    allowed_groups=source.get("allowed_groups", []),
                    source_modalities=source.get("source_modalities", []),
                    keyframe_path=source.get("keyframe_path"),
                )
            )

        return results

    async def _hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        tenant_id: UUID,
        video_id: UUID | None,
        allowed_groups: list[str] | None,
        sem_weight: float,
        kw_weight: float,
        metrics: VideoSearchMetrics,
    ) -> list[SearchResult]:
        """Execute hybrid search combining semantic and keyword.

        Args:
            query: Search query text.
            query_embedding: Query vector.
            tenant_id: Tenant filter.
            video_id: Optional video filter.
            allowed_groups: ACL groups.
            sem_weight: Semantic weight for fusion.
            kw_weight: Keyword weight for fusion.
            metrics: Metrics object to update.

        Returns:
            Fused list of SearchResult objects.
        """
        # Run both searches in parallel
        semantic_task = self._semantic_search(
            query_embedding=query_embedding,
            tenant_id=tenant_id,
            top_k=self.config.semantic_top_k,
            video_id=video_id,
            allowed_groups=allowed_groups,
            metrics=metrics,
        )

        keyword_task = self._keyword_search(
            query=query,
            tenant_id=tenant_id,
            top_k=self.config.keyword_top_k,
            video_id=video_id,
            allowed_groups=allowed_groups,
            metrics=metrics,
        )

        semantic_results, keyword_results = await asyncio.gather(
            semantic_task,
            keyword_task,
        )

        # RRF fusion
        fusion_start = time.time()
        fused = self._rrf_fusion(
            semantic_results=semantic_results,
            keyword_results=keyword_results,
        )
        metrics.fusion_ms = (time.time() - fusion_start) * 1000

        return fused

    def _rrf_fusion(
        self,
        semantic_results: list[SearchResult],
        keyword_results: list[SearchResult],
    ) -> list[SearchResult]:
        """Fuse results using Reciprocal Rank Fusion.

        Args:
            semantic_results: Results from semantic search.
            keyword_results: Results from keyword search.

        Returns:
            Fused and ranked results.
        """
        k = self.config.rrf_k
        rrf_scores: dict[UUID, float] = defaultdict(float)
        items: dict[UUID, SearchResult] = {}
        semantic_info: dict[UUID, tuple[float, int]] = {}
        keyword_info: dict[UUID, tuple[float, int]] = {}

        # Process semantic results
        for result in semantic_results:
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] += 1 / (k + result.rank)
            semantic_info[chunk_id] = (result.score, result.rank)

            if chunk_id not in items:
                items[chunk_id] = result

        # Process keyword results
        for result in keyword_results:
            chunk_id = result.chunk_id
            rrf_scores[chunk_id] += 1 / (k + result.rank)
            keyword_info[chunk_id] = (result.score, result.rank)

            if chunk_id not in items:
                items[chunk_id] = result
            else:
                # Merge additional fields from keyword search
                existing = items[chunk_id]
                if not existing.transcript_text:
                    existing.transcript_text = result.transcript_text
                if not existing.scene_description:
                    existing.scene_description = result.scene_description
                if not existing.ocr_text:
                    existing.ocr_text = result.ocr_text

        # Sort by RRF score
        sorted_chunks = sorted(
            rrf_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        # Build fused results
        fused = []
        for new_rank, (chunk_id, rrf_score) in enumerate(sorted_chunks, start=1):
            item = items[chunk_id]
            item.score = rrf_score
            item.rank = new_rank
            fused.append(item)

        return fused

    async def _rerank_results(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Rerank results using cross-encoder.

        Args:
            query: Search query.
            results: Results to rerank.

        Returns:
            Reranked results.
        """
        if not self._reranker or not results:
            return results

        # Prepare documents for reranker
        documents = [r.fused_text for r in results]
        document_ids = [r.chunk_id for r in results]

        try:
            rerank_response = await self._reranker.rerank(
                query=query,
                documents=documents,
                document_ids=document_ids,
                top_k=len(results),
            )

            # Build ID to result mapping
            result_map = {r.chunk_id: r for r in results}

            # Rebuild in reranked order
            reranked = []
            for new_rank, rr in enumerate(rerank_response.results, start=1):
                original = result_map.get(rr.document_id)
                if original:
                    original.score = rr.relevance_score
                    original.rank = new_rank
                    reranked.append(original)

            return reranked
        except Exception as e:
            logger.warning("Reranking failed, using original order: %s", e)
            return results

    def _group_and_format(
        self,
        results: list[SearchResult],
        max_per_video: int,
        max_videos: int,
    ) -> list[VideoResult]:
        """Group results by video and format for response.

        Args:
            results: Flat list of search results.
            max_per_video: Maximum matches per video.
            max_videos: Maximum videos to return.

        Returns:
            List of VideoResult with grouped matches.
        """
        # Group by video_id
        by_video: dict[UUID, list[SearchResult]] = defaultdict(list)
        for result in results:
            by_video[result.video_id].append(result)

        # Build video results
        video_results = []
        for video_id, matches in by_video.items():
            # Sort by timestamp
            matches.sort(key=lambda m: m.start_time_ms)

            # Limit matches per video
            limited_matches = matches[:max_per_video]

            # Calculate scores
            scores = [m.score for m in limited_matches]
            max_score = max(scores) if scores else 0
            avg_score = sum(scores) / len(scores) if scores else 0

            # Get video metadata from first match
            first = limited_matches[0]

            # Convert to VideoMatch objects
            video_matches = []
            for m in limited_matches:
                keyframe_url = None
                if m.keyframe_path and self.config.keyframe_base_url:
                    keyframe_url = f"{self.config.keyframe_base_url}/{m.keyframe_path}"

                clip_url = None
                if self.config.clip_base_url:
                    clip_url = (
                        f"{self.config.clip_base_url}/{video_id}"
                        f"?start={m.start_time_ms}&end={m.end_time_ms}"
                    )

                video_matches.append(
                    VideoMatch(
                        chunk_id=m.chunk_id,
                        chunk_index=m.chunk_index,
                        start_time_ms=m.start_time_ms,
                        end_time_ms=m.end_time_ms,
                        fused_score=m.score,
                        fused_text_preview=m.fused_text[:500] if m.fused_text else "",
                        transcript_text=m.transcript_text or None,
                        scene_description=m.scene_description or None,
                        keyframe_url=keyframe_url,
                        clip_url=clip_url,
                        source_modalities=m.source_modalities,
                    )
                )

            video_results.append(
                VideoResult(
                    video_id=video_id,
                    tenant_id=first.tenant_id,
                    title=first.video_title,
                    max_score=max_score,
                    avg_score=avg_score,
                    match_count=len(video_matches),
                    matches=video_matches,
                    visibility=first.visibility,
                )
            )

        # Sort videos by max_score and limit
        video_results.sort(key=lambda v: v.max_score, reverse=True)
        return video_results[:max_videos]

    def health_check(self) -> bool:
        """Check health of search backends.

        Returns:
            True if both backends healthy.
        """
        try:
            # Check Qdrant
            self.qdrant.get_collections()

            # Check OpenSearch
            health = self.opensearch.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False

    def close(self) -> None:
        """Close client connections."""
        if self._qdrant is not None:
            self._qdrant.close()
            self._qdrant = None
        if self._opensearch is not None:
            self._opensearch.close()
            self._opensearch = None
