# US-9.8: Video Retrieval with Timeline Response

> **Story ID:** US-9.8
> **Epic:** Video RAG Pipeline
> **Priority:** Critical
> **Estimated Effort:** 3 days
> **Dependencies:** US-9.7 (Embedding & Indexing), US-3.4 (Hybrid Fusion), US-3.5 (Reranker)

## User Story

**As a** user
**I want** to search across my videos and see a timeline of matches
**So that** I can quickly find relevant moments

## Context

This story extends the retrieval service to support video content search. Users query using natural language, and the system returns a timeline of matching video moments across all their videos. The response groups results by video and provides keyframe thumbnails, timestamps, and clip URLs for each match.

## Technical Requirements

### Video Retrieval API

```python
# api/routes/video_retrieve.py
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID, uuid4
from datetime import datetime
import time

from ..schemas.video_retrieve import (
    VideoRetrieveRequest,
    VideoTimelineResponse,
    VideoResult,
    VideoMatch,
    VideoSearchMetrics
)
from ..dependencies import get_current_user, get_video_retriever

router = APIRouter(prefix="/retrieve/video", tags=["Video Retrieval"])

@router.post("", response_model=VideoTimelineResponse)
async def retrieve_videos(
    request: VideoRetrieveRequest,
    current_user: dict = Depends(get_current_user),
    retriever = Depends(get_video_retriever)
):
    """
    Search across videos and return a timeline of matching moments.

    **Search Modes:**
    - `hybrid`: Combines semantic and keyword search (default)
    - `semantic`: Vector similarity search only
    - `keyword`: BM25 keyword search only

    **Response Structure:**
    Results are grouped by video, with each video containing a list of
    matching chunks sorted by timestamp. Each match includes:
    - Timestamp range (start_time_ms, end_time_ms)
    - Relevance score
    - Preview text (fused content)
    - Keyframe thumbnail URL
    - Clip URL for on-demand video generation

    **ACL Filtering:**
    Only returns results from videos the user has access to based on
    tenant_id and allowed_groups.
    """
    start_time = time.time()
    query_id = uuid4()

    tenant_id = UUID(current_user["tenant_id"])
    user_groups = current_user.get("groups", [])

    # Build ACL filter
    acl_filter = {
        "tenant_id": str(tenant_id),
        "user_groups": user_groups
    }

    # Execute retrieval
    results = await retriever.retrieve(
        query=request.query,
        mode=request.mode,
        top_k=request.top_k,
        semantic_weight=request.semantic_weight,
        keyword_weight=request.keyword_weight,
        rerank=request.rerank,
        acl_filter=acl_filter,
        video_ids=request.video_ids,
        date_range=request.date_range
    )

    total_time = (time.time() - start_time) * 1000

    return VideoTimelineResponse(
        query=request.query,
        query_id=query_id,
        total_matches=results.total_matches,
        videos=results.videos,
        metrics=VideoSearchMetrics(
            query_embedding_ms=results.metrics.embedding_ms,
            semantic_search_ms=results.metrics.semantic_ms,
            keyword_search_ms=results.metrics.keyword_ms,
            fusion_ms=results.metrics.fusion_ms,
            rerank_ms=results.metrics.rerank_ms,
            total_ms=total_time
        ),
        processed_at=datetime.utcnow()
    )
```

### Request/Response Schemas

```python
# api/schemas/video_retrieve.py
from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import UUID
from datetime import datetime

class DateRange(BaseModel):
    start: datetime | None = None
    end: datetime | None = None

class VideoRetrieveRequest(BaseModel):
    """Request for video content search."""
    query: str = Field(..., min_length=1, max_length=2000)

    # Search configuration
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    top_k: int = Field(default=20, ge=1, le=100)

    # Hybrid weights
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)

    # Reranking
    rerank: bool = True
    rerank_top_k: int = Field(default=50, ge=1, le=200)

    # Filters
    video_ids: list[UUID] | None = None  # Search specific videos
    date_range: DateRange | None = None

    # Response options
    include_transcript: bool = True
    include_thumbnails: bool = True
    max_matches_per_video: int = Field(default=10, ge=1, le=50)

class VideoMatch(BaseModel):
    """A single matching moment within a video."""
    chunk_id: UUID
    chunk_index: int
    start_time_ms: int
    end_time_ms: int
    relevance_score: float = Field(ge=0.0, le=1.0)

    # Content preview
    preview_text: str
    transcript_snippet: str | None = None
    scene_description: str | None = None

    # URLs
    keyframe_url: str | None = None
    clip_url: str  # URL to request clip generation

    # Score breakdown
    semantic_score: float | None = None
    keyword_score: float | None = None
    rerank_score: float | None = None

class VideoResult(BaseModel):
    """Search results for a single video."""
    video_id: UUID
    title: str
    duration_seconds: float
    thumbnail_url: str | None = None
    total_matches: int
    matches: list[VideoMatch]

    # Aggregate score for this video
    max_relevance: float
    avg_relevance: float

class VideoSearchMetrics(BaseModel):
    """Timing metrics for the search operation."""
    query_embedding_ms: float
    semantic_search_ms: float | None = None
    keyword_search_ms: float | None = None
    fusion_ms: float | None = None
    rerank_ms: float | None = None
    total_ms: float

class VideoTimelineResponse(BaseModel):
    """Response with timeline of video matches."""
    query: str
    query_id: UUID
    total_matches: int
    videos: list[VideoResult]
    metrics: VideoSearchMetrics
    processed_at: datetime
```

### Video Retriever Service

```python
# retrieval/video_retriever.py
from dataclasses import dataclass, field
from uuid import UUID
from typing import Literal
import logging
import time

logger = logging.getLogger(__name__)

@dataclass
class RetrievalMetrics:
    embedding_ms: float = 0
    semantic_ms: float = 0
    keyword_ms: float = 0
    fusion_ms: float = 0
    rerank_ms: float = 0

@dataclass
class RetrievalResult:
    total_matches: int
    videos: list["VideoResult"]
    metrics: RetrievalMetrics

class VideoRetriever:
    """Retrieves video content using hybrid search."""

    def __init__(
        self,
        qdrant_client,
        opensearch_client,
        embedding_service,
        reranker_service,
        video_service,
        storage_service
    ):
        self.qdrant = qdrant_client
        self.opensearch = opensearch_client
        self.embedding = embedding_service
        self.reranker = reranker_service
        self.video_service = video_service
        self.storage = storage_service

    async def retrieve(
        self,
        query: str,
        mode: Literal["hybrid", "semantic", "keyword"],
        top_k: int,
        semantic_weight: float,
        keyword_weight: float,
        rerank: bool,
        acl_filter: dict,
        video_ids: list[UUID] | None = None,
        date_range: dict | None = None,
        max_matches_per_video: int = 10
    ) -> RetrievalResult:
        """
        Execute video retrieval pipeline.

        1. Embed query
        2. Search Qdrant (semantic) and/or OpenSearch (keyword)
        3. Fuse results with RRF
        4. Rerank top results
        5. Group by video and format response
        """
        metrics = RetrievalMetrics()

        # Step 1: Embed query
        start = time.time()
        # Add BGE instruction prefix for queries
        query_text = f"Represent this sentence for searching relevant passages: {query}"
        query_embedding = await self.embedding.embed_query(query_text)
        metrics.embedding_ms = (time.time() - start) * 1000

        # Build filters
        qdrant_filter = self._build_qdrant_filter(acl_filter, video_ids, date_range)
        opensearch_filter = self._build_opensearch_filter(acl_filter, video_ids, date_range)

        # Step 2: Execute searches based on mode
        semantic_results = []
        keyword_results = []

        if mode in ["hybrid", "semantic"]:
            start = time.time()
            semantic_results = await self._semantic_search(
                query_embedding,
                qdrant_filter,
                top_k=top_k * 3  # Get more for fusion
            )
            metrics.semantic_ms = (time.time() - start) * 1000

        if mode in ["hybrid", "keyword"]:
            start = time.time()
            keyword_results = await self._keyword_search(
                query,
                opensearch_filter,
                top_k=top_k * 3
            )
            metrics.keyword_ms = (time.time() - start) * 1000

        # Step 3: Fuse results
        start = time.time()
        if mode == "hybrid":
            fused = self._rrf_fusion(
                semantic_results,
                keyword_results,
                semantic_weight,
                keyword_weight
            )
        elif mode == "semantic":
            fused = semantic_results
        else:
            fused = keyword_results
        metrics.fusion_ms = (time.time() - start) * 1000

        # Step 4: Rerank
        if rerank and fused:
            start = time.time()
            fused = await self._rerank(query, fused, top_k)
            metrics.rerank_ms = (time.time() - start) * 1000
        else:
            fused = fused[:top_k]

        # Step 5: Group by video and format
        videos = await self._group_and_format(fused, max_matches_per_video)

        total_matches = sum(v.total_matches for v in videos)

        return RetrievalResult(
            total_matches=total_matches,
            videos=videos,
            metrics=metrics
        )

    async def _semantic_search(
        self,
        query_embedding: list[float],
        filter_: dict,
        top_k: int
    ) -> list[dict]:
        """Search Qdrant for semantically similar chunks."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        # Build Qdrant filter
        must_conditions = [
            FieldCondition(key="tenant_id", match=MatchValue(value=filter_["tenant_id"]))
        ]

        # ACL: match visibility=public OR user's groups in allowed_groups
        # This is simplified - real impl needs OR logic
        if filter_.get("user_groups"):
            must_conditions.append(
                FieldCondition(
                    key="allowed_groups",
                    match=MatchAny(any=filter_["user_groups"])
                )
            )

        if filter_.get("video_ids"):
            must_conditions.append(
                FieldCondition(
                    key="video_id",
                    match=MatchAny(any=[str(v) for v in filter_["video_ids"]])
                )
            )

        results = await self.qdrant.search(
            collection_name="video_chunks",
            query_vector=query_embedding,
            query_filter=Filter(must=must_conditions),
            limit=top_k,
            with_payload=True
        )

        return [
            {
                "chunk_id": r.id,
                "video_id": r.payload["video_id"],
                "chunk_index": r.payload["chunk_index"],
                "start_time_ms": r.payload["start_time_ms"],
                "end_time_ms": r.payload["end_time_ms"],
                "fused_text": r.payload.get("fused_text", ""),
                "semantic_score": r.score,
                "source": "semantic"
            }
            for r in results
        ]

    async def _keyword_search(
        self,
        query: str,
        filter_: dict,
        top_k: int
    ) -> list[dict]:
        """Search OpenSearch for keyword matches."""
        must_clauses = [
            {"term": {"tenant_id": filter_["tenant_id"]}},
            {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "fused_text^3",
                        "transcript_text^2",
                        "scene_description",
                        "ocr_text",
                        "video_title"
                    ],
                    "type": "best_fields"
                }
            }
        ]

        # ACL filter
        if filter_.get("user_groups"):
            must_clauses.append({
                "bool": {
                    "should": [
                        {"term": {"visibility": "public"}},
                        {"terms": {"allowed_groups": filter_["user_groups"]}}
                    ],
                    "minimum_should_match": 1
                }
            })

        if filter_.get("video_ids"):
            must_clauses.append({
                "terms": {"video_id": [str(v) for v in filter_["video_ids"]]}
            })

        response = await self.opensearch.search(
            index="video_chunks",
            body={
                "query": {"bool": {"must": must_clauses}},
                "size": top_k,
                "_source": True
            }
        )

        max_score = response["hits"]["max_score"] or 1

        return [
            {
                "chunk_id": hit["_id"],
                "video_id": hit["_source"]["video_id"],
                "chunk_index": hit["_source"]["chunk_index"],
                "start_time_ms": hit["_source"]["start_time_ms"],
                "end_time_ms": hit["_source"]["end_time_ms"],
                "fused_text": hit["_source"].get("fused_text", ""),
                "transcript_text": hit["_source"].get("transcript_text", ""),
                "scene_description": hit["_source"].get("scene_description", ""),
                "keyword_score": hit["_score"] / max_score,  # Normalize
                "source": "keyword"
            }
            for hit in response["hits"]["hits"]
        ]

    def _rrf_fusion(
        self,
        semantic: list[dict],
        keyword: list[dict],
        semantic_weight: float,
        keyword_weight: float,
        k: int = 60
    ) -> list[dict]:
        """Reciprocal Rank Fusion of semantic and keyword results."""
        scores = {}
        items = {}

        # Score semantic results
        for rank, item in enumerate(semantic, 1):
            chunk_id = item["chunk_id"]
            rrf_score = semantic_weight * (1 / (k + rank))
            scores[chunk_id] = scores.get(chunk_id, 0) + rrf_score
            if chunk_id not in items:
                items[chunk_id] = item
            else:
                items[chunk_id]["semantic_score"] = item.get("semantic_score")

        # Score keyword results
        for rank, item in enumerate(keyword, 1):
            chunk_id = item["chunk_id"]
            rrf_score = keyword_weight * (1 / (k + rank))
            scores[chunk_id] = scores.get(chunk_id, 0) + rrf_score
            if chunk_id not in items:
                items[chunk_id] = item
            else:
                items[chunk_id]["keyword_score"] = item.get("keyword_score")
                # Merge additional fields
                if not items[chunk_id].get("transcript_text"):
                    items[chunk_id]["transcript_text"] = item.get("transcript_text")
                if not items[chunk_id].get("scene_description"):
                    items[chunk_id]["scene_description"] = item.get("scene_description")

        # Sort by RRF score
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        # Add fused score to items
        for chunk_id in sorted_ids:
            items[chunk_id]["fused_score"] = scores[chunk_id]

        return [items[chunk_id] for chunk_id in sorted_ids]

    async def _rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int
    ) -> list[dict]:
        """Rerank results using cross-encoder."""
        if not results:
            return []

        # Prepare pairs for reranker
        pairs = [(query, r["fused_text"]) for r in results[:50]]

        # Get rerank scores
        rerank_scores = await self.reranker.rerank(pairs)

        # Combine with results
        for i, result in enumerate(results[:50]):
            result["rerank_score"] = rerank_scores[i] if i < len(rerank_scores) else 0

        # Sort by rerank score
        results[:50] = sorted(results[:50], key=lambda x: x.get("rerank_score", 0), reverse=True)

        return results[:top_k]

    async def _group_and_format(
        self,
        results: list[dict],
        max_per_video: int
    ) -> list["VideoResult"]:
        """Group results by video and format response."""
        from collections import defaultdict

        # Group by video
        by_video = defaultdict(list)
        for r in results:
            by_video[r["video_id"]].append(r)

        # Format each video's results
        videos = []
        for video_id, chunks in by_video.items():
            # Get video metadata
            video = await self.video_service.get_video_by_id(UUID(video_id))
            if not video:
                continue

            # Sort chunks by timestamp
            chunks.sort(key=lambda x: x["start_time_ms"])

            # Limit matches per video
            chunks = chunks[:max_per_video]

            # Format matches
            matches = []
            for chunk in chunks:
                # Generate URLs
                keyframe_url = await self.storage.get_keyframe_url(
                    video.tenant_id,
                    UUID(video_id),
                    chunk["chunk_index"]
                ) if chunk.get("chunk_index") is not None else None

                clip_url = f"/api/v1/videos/{video_id}/clip?start={chunk['start_time_ms']}&end={chunk['end_time_ms']}"

                matches.append(VideoMatch(
                    chunk_id=UUID(chunk["chunk_id"]) if "-" in str(chunk["chunk_id"]) else uuid4(),
                    chunk_index=chunk["chunk_index"],
                    start_time_ms=chunk["start_time_ms"],
                    end_time_ms=chunk["end_time_ms"],
                    relevance_score=chunk.get("rerank_score") or chunk.get("fused_score", 0),
                    preview_text=chunk.get("fused_text", "")[:500],
                    transcript_snippet=chunk.get("transcript_text", "")[:200] if chunk.get("transcript_text") else None,
                    scene_description=chunk.get("scene_description", "")[:200] if chunk.get("scene_description") else None,
                    keyframe_url=keyframe_url,
                    clip_url=clip_url,
                    semantic_score=chunk.get("semantic_score"),
                    keyword_score=chunk.get("keyword_score"),
                    rerank_score=chunk.get("rerank_score")
                ))

            # Calculate video-level scores
            scores = [m.relevance_score for m in matches]
            max_relevance = max(scores) if scores else 0
            avg_relevance = sum(scores) / len(scores) if scores else 0

            # Get video thumbnail
            thumbnail_url = await self.storage.get_thumbnail_url(
                video.tenant_id,
                UUID(video_id)
            ) if video.thumbnail_path else None

            videos.append(VideoResult(
                video_id=UUID(video_id),
                title=video.title or video.filename,
                duration_seconds=float(video.duration_seconds) if video.duration_seconds else 0,
                thumbnail_url=thumbnail_url,
                total_matches=len(matches),
                matches=matches,
                max_relevance=max_relevance,
                avg_relevance=avg_relevance
            ))

        # Sort videos by max relevance
        videos.sort(key=lambda v: v.max_relevance, reverse=True)

        return videos

    def _build_qdrant_filter(self, acl: dict, video_ids: list | None, date_range: dict | None) -> dict:
        return {
            "tenant_id": acl["tenant_id"],
            "user_groups": acl.get("user_groups", []),
            "video_ids": video_ids,
            "date_range": date_range
        }

    def _build_opensearch_filter(self, acl: dict, video_ids: list | None, date_range: dict | None) -> dict:
        return {
            "tenant_id": acl["tenant_id"],
            "user_groups": acl.get("user_groups", []),
            "video_ids": video_ids,
            "date_range": date_range
        }

from uuid import uuid4  # Import at module level
```

## Sequence Diagram

```
┌──────┐     ┌─────────┐     ┌────────┐     ┌──────────┐     ┌─────────┐
│Client│     │Retrieval│     │Qdrant  │     │OpenSearch│     │Reranker │
└──┬───┘     └────┬────┘     └───┬────┘     └────┬─────┘     └────┬────┘
   │              │              │               │                │
   │POST /retrieve/video        │               │                │
   │──────────────>              │               │                │
   │              │              │               │                │
   │              │ embed(query) │               │                │
   │              │─────┐        │               │                │
   │              │     │        │               │                │
   │              │<────┘        │               │                │
   │              │              │               │                │
   │              │ search(vector, filter)       │                │
   │              │──────────────>               │                │
   │              │   semantic_results           │                │
   │              │<─────────────│               │                │
   │              │              │               │                │
   │              │ search(query, filter)        │                │
   │              │─────────────────────────────>│                │
   │              │          keyword_results     │                │
   │              │<────────────────────────────│                │
   │              │              │               │                │
   │              │ RRF fusion   │               │                │
   │              │─────┐        │               │                │
   │              │     │        │               │                │
   │              │<────┘        │               │                │
   │              │              │               │                │
   │              │ rerank(query, fused)         │                │
   │              │──────────────────────────────────────────────>│
   │              │              │               │    rerank_scores
   │              │<──────────────────────────────────────────────│
   │              │              │               │                │
   │ VideoTimelineResponse       │               │                │
   │<─────────────│              │               │                │
```

## Acceptance Criteria

- [ ] New endpoint: `POST /api/v1/retrieve/video`
- [ ] Hybrid search across video_chunks (semantic + keyword)
- [ ] RRF fusion and reranking
- [ ] Group results by video
- [ ] Sort matches by timestamp within each video
- [ ] Return timeline response with: video metadata, matching chunks, keyframe URLs, clip URLs
- [ ] Include relevance scores and preview text

## Testing Requirements

```python
class TestVideoRetrieval:
    @pytest.mark.asyncio
    async def test_hybrid_search(self, client, auth_headers, indexed_videos):
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "machine learning presentation", "mode": "hybrid"},
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "videos" in data
        assert data["total_matches"] > 0

    @pytest.mark.asyncio
    async def test_semantic_only(self, client, auth_headers):
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "test", "mode": "semantic"},
            headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["metrics"]["keyword_search_ms"] is None

    @pytest.mark.asyncio
    async def test_groups_by_video(self, client, auth_headers, indexed_videos):
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "test content"},
            headers=auth_headers
        )

        data = response.json()
        video_ids = [v["video_id"] for v in data["videos"]]
        assert len(video_ids) == len(set(video_ids))  # No duplicates

    @pytest.mark.asyncio
    async def test_sorts_matches_by_timestamp(self, client, auth_headers):
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "test"},
            headers=auth_headers
        )

        for video in response.json()["videos"]:
            timestamps = [m["start_time_ms"] for m in video["matches"]]
            assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_includes_clip_urls(self, client, auth_headers):
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "test"},
            headers=auth_headers
        )

        for video in response.json()["videos"]:
            for match in video["matches"]:
                assert "clip_url" in match
                assert "start=" in match["clip_url"]
                assert "end=" in match["clip_url"]

    @pytest.mark.asyncio
    async def test_respects_acl(self, client, user_without_access):
        headers = get_auth_headers(user_without_access)
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "private content"},
            headers=headers
        )

        # Should not return private videos user doesn't have access to
        assert response.json()["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_video_ids(self, client, auth_headers, indexed_videos):
        target_video = indexed_videos[0]
        response = client.post(
            "/api/v1/retrieve/video",
            json={"query": "test", "video_ids": [str(target_video.id)]},
            headers=auth_headers
        )

        for video in response.json()["videos"]:
            assert video["video_id"] == str(target_video.id)
```

## Performance Requirements

| Metric | Target |
|--------|--------|
| Query embedding | <20ms |
| Semantic search | <50ms |
| Keyword search | <30ms |
| Reranking | <150ms |
| Total E2E | <300ms (p95) |

## Definition of Done

- [ ] Video retrieval endpoint implemented
- [ ] Hybrid, semantic, keyword modes working
- [ ] RRF fusion producing ranked results
- [ ] Reranking improving relevance
- [ ] Results grouped by video
- [ ] Timestamps sorted within videos
- [ ] Clip URLs included in response
- [ ] ACL filtering enforced
- [ ] Metrics tracking all stages
- [ ] >90% test coverage
