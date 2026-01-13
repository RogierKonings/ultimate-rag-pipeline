"""Semantic search using Qdrant vector database."""

import time
from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    DatetimeRange,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    QuantizationSearchParams,
    Range,
    SearchParams,
)

from search.base import BaseSearcher
from search.exceptions import SearchConnectionError, SearchFilterError
from search.models import (
    QdrantConfig,
    SearchResultItem,
    SemanticSearchResponse,
)


class SemanticSearcher(BaseSearcher):
    """
    Semantic search using Qdrant vector database.

    Uses HNSW indexing for fast approximate nearest neighbor search.
    Supports filtering by metadata and ACL fields.
    """

    def __init__(self, config: QdrantConfig | None = None):
        self.config = config or QdrantConfig()
        self._client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        """Establish connection to Qdrant."""
        try:
            self._client = AsyncQdrantClient(
                url=self.config.url,
                api_key=self.config.api_key,
                timeout=self.config.timeout,
            )
        except Exception as e:
            raise SearchConnectionError(
                f"Failed to connect to Qdrant: {e}",
                details={"url": self.config.url},
            ) from e

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filters: dict | None = None,
        score_threshold: float = 0.0,
        include_metadata: bool = True,
        include_vectors: bool = False,
    ) -> SemanticSearchResponse:
        """
        Execute vector similarity search.

        Args:
            query_embedding: Query vector (1024 dimensions for BGE)
            top_k: Number of results to return
            filters: Qdrant filter dict (built by ACLFilter)
            score_threshold: Minimum similarity score (0-1)
            include_metadata: Include payload in results
            include_vectors: Include vectors in results

        Returns:
            SemanticSearchResponse with ranked results
        """
        if not self._client:
            await self.connect()

        start_time = time.time()

        # Build Qdrant filter from dict
        qdrant_filter = self._build_filter(filters) if filters else None

        # Configure search parameters
        search_params = SearchParams(
            hnsw_ef=self.config.hnsw_ef,
            exact=self.config.exact_search,
        )

        # Add quantization params if enabled
        if self.config.use_quantization:
            search_params.quantization = QuantizationSearchParams(
                rescore=self.config.quantization_rescore,
            )

        # Execute search using query_points (replaces deprecated search method)
        response = await self._client.query_points(
            collection_name=self.config.collection_name,
            query=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=include_metadata,
            with_vectors=include_vectors,
            search_params=search_params,
        )
        results = response.points

        search_time = (time.time() - start_time) * 1000

        # Convert to response model
        items = [self._convert_result(r) for r in results]

        return SemanticSearchResponse(
            results=items,
            total_found=len(items),
            search_time_ms=search_time,
        )

    def _build_filter(self, filter_dict: dict) -> Filter:
        """
        Build Qdrant Filter from dictionary specification.

        Supports nested must/should/must_not conditions.
        """
        conditions = []
        should_conditions = []
        must_not_conditions = []

        for key, value in filter_dict.items():
            if key == "must":
                for condition in value:
                    conditions.append(self._build_condition(condition))
            elif key == "should":
                for condition in value:
                    should_conditions.append(self._build_condition(condition))
            elif key == "must_not":
                for condition in value:
                    must_not_conditions.append(self._build_condition(condition))
            else:
                # Simple key-value filter
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value)),
                )

        return Filter(
            must=conditions if conditions else None,
            should=should_conditions if should_conditions else None,
            must_not=must_not_conditions if must_not_conditions else None,
        )

    def _build_condition(self, condition: dict) -> FieldCondition:
        """Build a single field condition."""
        key = condition.get("key")

        if "match" in condition:
            match_spec = condition["match"]
            if "value" in match_spec:
                return FieldCondition(key=key, match=MatchValue(value=match_spec["value"]))
            if "any" in match_spec:
                return FieldCondition(key=key, match=MatchAny(any=match_spec["any"]))

        elif "range" in condition:
            range_spec = condition["range"]
            # Check if any value looks like a datetime string
            values = [v for v in range_spec.values() if v is not None]
            is_datetime = any(isinstance(v, str) and ("-" in v or "T" in v) for v in values)

            if is_datetime:
                return FieldCondition(
                    key=key,
                    range=DatetimeRange(
                        gte=range_spec.get("gte"),
                        gt=range_spec.get("gt"),
                        lte=range_spec.get("lte"),
                        lt=range_spec.get("lt"),
                    ),
                )
            return FieldCondition(
                key=key,
                range=Range(
                    gte=range_spec.get("gte"),
                    gt=range_spec.get("gt"),
                    lte=range_spec.get("lte"),
                    lt=range_spec.get("lt"),
                ),
            )

        raise SearchFilterError(
            f"Unsupported condition: {condition}",
            details={"condition": condition},
        )

    def _convert_result(self, result: Any) -> SearchResultItem:
        """Convert Qdrant result to SearchResultItem."""
        payload = result.payload or {}

        # Handle UUID conversion
        if isinstance(result.id, str):
            try:
                chunk_id = UUID(result.id)
            except ValueError:
                # If not a valid UUID string, create one from hash
                chunk_id = UUID(int=hash(result.id) & ((1 << 128) - 1))
        else:
            chunk_id = UUID(int=result.id & ((1 << 128) - 1))

        # Parse document_id
        doc_id_str = payload.get("document_id", "00000000-0000-0000-0000-000000000000")
        try:
            document_id = UUID(doc_id_str)
        except (ValueError, TypeError):
            document_id = UUID("00000000-0000-0000-0000-000000000000")

        return SearchResultItem(
            chunk_id=chunk_id,
            document_id=document_id,
            content=payload.get("content", ""),
            score=self._normalize_score(result.score),
            metadata={
                k: v for k, v in payload.items() if k not in ["content", "document_id", "chunk_id"]
            },
            title=payload.get("title"),
            source=payload.get("source"),
            chunk_index=payload.get("chunk_index", 0),
            total_chunks=payload.get("total_chunks", 1),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    def _normalize_score(self, score: float) -> float:
        """
        Normalize score to 0-1 range.

        Qdrant cosine similarity is already in [-1, 1] range.
        Map to [0, 1] for consistency.
        """
        # Cosine similarity: -1 to 1 -> 0 to 1
        return max(0.0, min(1.0, (score + 1) / 2))

    async def search_multi_vector(
        self,
        query_embeddings: list[list[float]],
        top_k: int = 10,
        filters: dict | None = None,
        aggregation: str = "max",  # "max", "avg", or "rrf"
    ) -> SemanticSearchResponse:
        """
        Search with multiple query vectors (for multi-query expansion).

        Args:
            query_embeddings: List of query vectors
            top_k: Number of final results
            filters: ACL and metadata filters
            aggregation: How to combine scores from multiple queries

        Returns:
            Aggregated search results
        """
        if not self._client:
            await self.connect()

        start_time = time.time()

        # Execute searches for all query embeddings
        all_results: list[list[SearchResultItem]] = []
        for embedding in query_embeddings:
            response = await self.search(
                query_embedding=embedding,
                top_k=top_k * 2,  # Get more to allow for deduplication
                filters=filters,
                score_threshold=0.0,
            )
            all_results.append(response.results)

        # Aggregate results
        aggregated = self._aggregate_results(all_results, aggregation, top_k)

        search_time = (time.time() - start_time) * 1000

        return SemanticSearchResponse(
            results=aggregated,
            total_found=len(aggregated),
            search_time_ms=search_time,
        )

    def _aggregate_results(
        self,
        result_lists: list[list[SearchResultItem]],
        method: str,
        top_k: int,
    ) -> list[SearchResultItem]:
        """
        Aggregate results from multiple queries.
        """
        # Track scores by chunk_id
        scores: dict[UUID, list[float]] = {}
        items: dict[UUID, SearchResultItem] = {}

        for results in result_lists:
            for item in results:
                if item.chunk_id not in scores:
                    scores[item.chunk_id] = []
                    items[item.chunk_id] = item
                scores[item.chunk_id].append(item.score)

        # Aggregate scores
        final_scores: dict[UUID, float] = {}

        if method == "max":
            for chunk_id, score_list in scores.items():
                final_scores[chunk_id] = max(score_list)
        elif method == "avg":
            for chunk_id, score_list in scores.items():
                final_scores[chunk_id] = sum(score_list) / len(score_list)
        elif method == "rrf":
            # Reciprocal Rank Fusion
            k = 60  # RRF constant
            for chunk_id in scores:
                rrf_score = 0.0
                for results in result_lists:
                    for rank, item in enumerate(results, 1):
                        if item.chunk_id == chunk_id:
                            rrf_score += 1 / (k + rank)
                            break
                final_scores[chunk_id] = rrf_score

        # Sort by final score and return top_k
        sorted_chunks = sorted(
            final_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        result = []
        for chunk_id, score in sorted_chunks:
            item = items[chunk_id].model_copy()
            item.score = min(score, 1.0) if method == "rrf" else score
            result.append(item)

        return result

    async def get_collection_info(self) -> dict:
        """Get collection statistics."""
        if not self._client:
            await self.connect()

        info = await self._client.get_collection(self.config.collection_name)

        return {
            "name": self.config.collection_name,
            "vectors_count": info.vectors_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "status": info.status.value,
        }

    async def health_check(self) -> bool:
        """Check if Qdrant is healthy."""
        try:
            if not self._client:
                await self.connect()

            # Try to get collection info
            await self._client.get_collection(self.config.collection_name)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close Qdrant client."""
        if self._client:
            await self._client.close()
            self._client = None
