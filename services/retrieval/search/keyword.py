"""Keyword search using OpenSearch BM25."""

import time
from typing import Any
from uuid import UUID

from opensearchpy import AsyncOpenSearch

from search.base import BaseSearcher
from search.exceptions import SearchConnectionError, SearchFilterError
from search.models import (
    KeywordSearchResponse,
    OpenSearchConfig,
    SearchResultItem,
)


class KeywordSearcher(BaseSearcher):
    """
    Keyword search using OpenSearch BM25.

    Supports multi-field search with boosting, custom analyzers,
    fuzzy matching, and highlighting.
    """

    def __init__(self, config: OpenSearchConfig | None = None):
        self.config = config or OpenSearchConfig()
        self._client: AsyncOpenSearch | None = None

    async def connect(self) -> None:
        """Establish connection to OpenSearch."""
        try:
            auth = None
            if self.config.username and self.config.password:
                auth = (self.config.username, self.config.password)

            self._client = AsyncOpenSearch(
                hosts=[self.config.url],
                http_auth=auth,
                use_ssl=self.config.use_ssl,
                verify_certs=self.config.verify_certs,
                timeout=self.config.timeout,
            )
        except Exception as e:
            raise SearchConnectionError(
                f"Failed to connect to OpenSearch: {e}",
                details={"url": self.config.url},
            ) from e

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
        fields: list[str] | None = None,
        field_boosts: dict[str, float] | None = None,
        highlight: bool = True,
        min_score: float = 0.0,
    ) -> KeywordSearchResponse:
        """
        Execute BM25 keyword search.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: OpenSearch filter dict (built by ACLFilter)
            fields: Fields to search (default: content, title)
            field_boosts: Field boost weights
            highlight: Enable result highlighting
            min_score: Minimum BM25 score threshold

        Returns:
            KeywordSearchResponse with ranked results
        """
        if not self._client:
            await self.connect()

        start_time = time.time()

        # Build query
        search_fields = fields or ["content", "title"]
        boosts = field_boosts or {"title": 2.0, "content": 1.0}

        # Apply boosts to field list
        boosted_fields = [f"{field}^{boosts.get(field, 1.0)}" for field in search_fields]

        # Build OpenSearch query
        es_query = self._build_query(query, boosted_fields, filters)

        # Add highlighting
        highlight_config = None
        if highlight:
            highlight_config = {
                "fields": {field: {} for field in search_fields},
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fragment_size": 150,
                "number_of_fragments": 3,
            }

        # Build search body
        body: dict[str, Any] = {
            "query": es_query,
            "size": top_k,
            "track_total_hits": self.config.track_total_hits,
            "_source": True,
        }

        if min_score > 0:
            body["min_score"] = min_score

        if highlight_config:
            body["highlight"] = highlight_config

        # Execute search
        response = await self._client.search(
            index=self.config.index_name,
            body=body,
        )

        search_time = (time.time() - start_time) * 1000

        # Convert to response model
        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total

        items = [self._convert_hit(hit) for hit in hits]

        # Normalize scores
        if items:
            items = self._normalize_scores(items)

        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time,
        )

    def _build_query(
        self,
        query: str,
        boosted_fields: list[str],
        filters: dict | None = None,
    ) -> dict:
        """
        Build OpenSearch query with bool structure.

        Uses multi_match for text search with BM25 scoring.
        """
        # Base text query
        text_query = {
            "multi_match": {
                "query": query,
                "fields": boosted_fields,
                "type": "best_fields",
                "operator": self.config.default_operator.lower(),
                "fuzziness": self.config.fuzziness,
                "prefix_length": 2,  # Require first 2 chars to match exactly
                "analyzer": self.config.analyzer,
            },
        }

        # If no filters, return simple query
        if not filters:
            return text_query

        # Build bool query with filters
        filter_clauses = self._build_filter_clauses(filters)

        return {"bool": {"must": [text_query], "filter": filter_clauses}}

    def _build_filter_clauses(self, filters: dict) -> list[dict]:
        """
        Build OpenSearch filter clauses from filter dict.

        Supports nested bool structure matching ACL filter format.
        """
        clauses = []

        for key, value in filters.items():
            if key == "must":
                for condition in value:
                    clauses.append(self._build_filter_condition(condition))
            elif key == "should":
                # Wrap should conditions in a bool
                should_clauses = [self._build_filter_condition(c) for c in value]
                clauses.append(
                    {"bool": {"should": should_clauses, "minimum_should_match": 1}},
                )
            elif key == "must_not":
                must_not_clauses = [self._build_filter_condition(c) for c in value]
                clauses.append({"bool": {"must_not": must_not_clauses}})
            else:
                # Simple key-value filter
                clauses.append({"term": {key: value}})

        return clauses

    def _build_filter_condition(self, condition: dict) -> dict:
        """Build a single filter condition."""
        key = condition.get("key")

        if "match" in condition:
            match_spec = condition["match"]
            if "value" in match_spec:
                return {"term": {key: match_spec["value"]}}
            if "any" in match_spec:
                return {"terms": {key: match_spec["any"]}}

        elif "range" in condition:
            range_spec = condition["range"]
            return {"range": {key: range_spec}}

        raise SearchFilterError(
            f"Unsupported condition: {condition}",
            details={"condition": condition},
        )

    def _convert_hit(self, hit: dict) -> SearchResultItem:
        """Convert OpenSearch hit to SearchResultItem."""
        source = hit["_source"]
        highlights = hit.get("highlight", {})

        # Use highlighted content if available
        content = source.get("content", "")
        if "content" in highlights:
            content = " ... ".join(highlights["content"])

        # Handle UUID conversion
        chunk_id = self._parse_uuid(hit["_id"])
        document_id = self._parse_uuid(
            source.get("document_id", "00000000-0000-0000-0000-000000000000"),
        )

        return SearchResultItem(
            chunk_id=chunk_id,
            document_id=document_id,
            content=content,
            score=hit["_score"],
            metadata={
                k: v
                for k, v in source.items()
                if k not in ["content", "document_id", "chunk_id", "embedding"]
            },
            title=source.get("title"),
            source=source.get("source"),
            chunk_index=source.get("chunk_index", 0),
            total_chunks=source.get("total_chunks", 1),
            created_at=source.get("created_at"),
            updated_at=source.get("updated_at"),
            highlights=highlights if highlights else None,
        )

    def _parse_uuid(self, value: str) -> UUID:
        """Parse a string as UUID, with fallback for non-UUID strings."""
        try:
            return UUID(value)
        except (ValueError, TypeError):
            # If not a valid UUID, create one from hash
            return UUID(int=hash(value) & ((1 << 128) - 1))

    def _normalize_scores(
        self,
        results: list[SearchResultItem],
    ) -> list[SearchResultItem]:
        """
        Normalize BM25 scores to 0-1 range.

        BM25 scores are unbounded, so we use min-max normalization.
        """
        if not results:
            return results

        scores = [r.score for r in results]
        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            for r in results:
                r.score = 1.0
            return results

        for r in results:
            r.score = (r.score - min_score) / (max_score - min_score)

        return results

    async def search_phrase(
        self,
        phrase: str,
        top_k: int = 10,
        filters: dict | None = None,
        slop: int = 0,
    ) -> KeywordSearchResponse:
        """
        Execute phrase search for exact or near-exact matches.

        Args:
            phrase: Exact phrase to search for
            top_k: Number of results
            filters: ACL and metadata filters
            slop: Number of positions allowed between terms

        Returns:
            KeywordSearchResponse with phrase matches
        """
        if not self._client:
            await self.connect()

        start_time = time.time()

        query: dict[str, Any] = {
            "bool": {
                "must": [{"match_phrase": {"content": {"query": phrase, "slop": slop}}}],
            },
        }

        if filters:
            query["bool"]["filter"] = self._build_filter_clauses(filters)

        response = await self._client.search(
            index=self.config.index_name,
            body={"query": query, "size": top_k, "_source": True},
        )

        search_time = (time.time() - start_time) * 1000

        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total

        items = [self._convert_hit(hit) for hit in hits]
        items = self._normalize_scores(items)

        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time,
        )

    async def search_with_expansion(
        self,
        queries: list[str],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> KeywordSearchResponse:
        """
        Search with multiple query variations (from query expansion).

        Combines results using a should clause (OR).
        """
        if not self._client:
            await self.connect()

        start_time = time.time()

        # Build multi-query with should
        should_clauses = []
        for q in queries:
            should_clauses.append(
                {
                    "multi_match": {
                        "query": q,
                        "fields": ["content", "title^2"],
                        "type": "best_fields",
                        "fuzziness": self.config.fuzziness,
                    },
                },
            )

        query: dict[str, Any] = {
            "bool": {"should": should_clauses, "minimum_should_match": 1},
        }

        if filters:
            query["bool"]["filter"] = self._build_filter_clauses(filters)

        response = await self._client.search(
            index=self.config.index_name,
            body={"query": query, "size": top_k, "_source": True},
        )

        search_time = (time.time() - start_time) * 1000

        hits = response["hits"]["hits"]
        total = response["hits"]["total"]
        total_count = total["value"] if isinstance(total, dict) else total

        items = [self._convert_hit(hit) for hit in hits]
        items = self._normalize_scores(items)

        return KeywordSearchResponse(
            results=items,
            total_found=total_count,
            search_time_ms=search_time,
        )

    async def get_index_info(self) -> dict:
        """Get index statistics."""
        if not self._client:
            await self.connect()

        stats = await self._client.indices.stats(index=self.config.index_name)
        index_stats = stats["indices"][self.config.index_name]["total"]

        return {
            "name": self.config.index_name,
            "docs_count": index_stats["docs"]["count"],
            "docs_deleted": index_stats["docs"]["deleted"],
            "store_size": index_stats["store"]["size_in_bytes"],
            "store_size_human": self._format_bytes(index_stats["store"]["size_in_bytes"]),
        }

    def _format_bytes(self, size: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"

    async def health_check(self) -> bool:
        """Check if OpenSearch is healthy."""
        try:
            if not self._client:
                await self.connect()

            health = await self._client.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False

    async def close(self) -> None:
        """Close OpenSearch client."""
        if self._client:
            await self._client.close()
            self._client = None
