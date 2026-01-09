"""Query preprocessor for the Retrieval Service.

This module provides the main query preprocessing pipeline that
normalizes, expands, and embeds queries for optimal retrieval.
"""

import hashlib
import re
import time
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import ProcessedQuery, QueryPreprocessorConfig, QueryType


class QueryPreprocessor:
    """Preprocesses queries for optimal retrieval.

    Pipeline:
    1. Normalize (lowercase, whitespace, special chars)
    2. Classify query type
    3. Expand with synonyms (optional)
    4. Generate HyDE document (optional)
    5. Generate query embedding
    """

    def __init__(
        self,
        config: Optional[QueryPreprocessorConfig] = None,
        cache: Optional["QueryCache"] = None,
    ):
        """Initialize query preprocessor.

        Args:
            config: Preprocessor configuration. Uses defaults if not provided.
            cache: Optional cache for processed queries.
        """
        self.config = config or QueryPreprocessorConfig()
        self.cache = cache
        self._http_client: Optional[httpx.AsyncClient] = None
        self._expander: Optional["QueryExpander"] = None
        self._hyde: Optional["HyDEGenerator"] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-initialize HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self.config.llm_gateway_url,
                timeout=self.config.request_timeout,
            )
        return self._http_client

    async def process(self, query: str) -> ProcessedQuery:
        """Process a raw query through the preprocessing pipeline.

        Args:
            query: Raw user query string.

        Returns:
            ProcessedQuery with normalized query, expansions, and embedding.
        """
        start_time = time.time()

        # Check cache first
        if self.cache and self.config.cache_enabled:
            cache_key = self._get_cache_key(query)
            cached = await self.cache.get(cache_key)
            if cached:
                cached.metadata["cached"] = True
                return cached

        # 1. Normalize
        normalized = self._normalize(query)

        # 2. Classify query type
        query_type = self._classify_query(normalized)

        # 3. Expand (optional)
        expanded_queries: list[str] = []
        if self.config.enable_expansion:
            expanded_queries = await self._expand_query(normalized)

        # 4. HyDE (optional)
        hyde_document: Optional[str] = None
        if self.config.enable_hyde and query_type == QueryType.QUESTION:
            hyde_document = await self._generate_hyde(normalized)

        # 5. Generate embedding
        # If HyDE is enabled, embed the hypothetical document instead
        text_to_embed = hyde_document if hyde_document else normalized
        embedding, tokens = await self._generate_embedding(text_to_embed)

        processing_time = (time.time() - start_time) * 1000

        result = ProcessedQuery(
            original_query=query,
            normalized_query=normalized,
            expanded_queries=expanded_queries,
            hyde_document=hyde_document,
            embedding=embedding,
            query_type=query_type,
            tokens=tokens,
            processing_time_ms=processing_time,
        )

        # Cache result
        if self.cache and self.config.cache_enabled:
            await self.cache.set(cache_key, result, ttl=self.config.cache_ttl)

        return result

    def _normalize(self, query: str) -> str:
        """Normalize query text.

        - Strip whitespace
        - Collapse multiple spaces
        - Lowercase (if configured)
        - Remove special characters (if configured)

        Args:
            query: Raw query string.

        Returns:
            Normalized query string.
        """
        result = query

        if self.config.strip_whitespace:
            result = result.strip()
            result = re.sub(r"\s+", " ", result)

        if self.config.lowercase:
            result = result.lower()

        if self.config.remove_special_chars:
            # Keep alphanumeric, spaces, and basic punctuation
            result = re.sub(r"[^a-zA-Z0-9\s\.\?\!\,\-]", "", result)

        return result

    def _classify_query(self, query: str) -> QueryType:
        """Classify query type based on patterns.

        - Questions start with who/what/when/where/why/how
        - Semantic queries contain conceptual terms
        - Simple queries are short keyword phrases

        Args:
            query: Normalized query string.

        Returns:
            Classified QueryType.
        """
        query_lower = query.lower()

        # Question patterns
        question_starters = [
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "is",
            "are",
            "can",
            "could",
            "would",
            "should",
            "do",
            "does",
            "did",
            "will",
        ]

        if any(query_lower.startswith(q + " ") for q in question_starters):
            return QueryType.QUESTION

        if query_lower.endswith("?"):
            return QueryType.QUESTION

        # Semantic indicators (looking for conceptual queries)
        semantic_indicators = [
            "explain",
            "describe",
            "compare",
            "difference",
            "relationship",
            "similar",
            "like",
            "meaning",
            "between",
            "versus",
            "vs",
        ]

        if any(indicator in query_lower for indicator in semantic_indicators):
            return QueryType.SEMANTIC

        # Short queries are typically keyword searches
        word_count = len(query.split())
        if word_count <= 3:
            return QueryType.SIMPLE

        return QueryType.HYBRID

    async def _expand_query(self, query: str) -> list[str]:
        """Expand query with synonyms or related terms.

        Args:
            query: Normalized query string.

        Returns:
            List of expanded query variations.
        """
        if self._expander is None:
            from .expander import QueryExpander

            self._expander = QueryExpander(self.config)

        return await self._expander.expand(query)

    async def _generate_hyde(self, query: str) -> str:
        """Generate Hypothetical Document Embedding (HyDE).

        Uses LLM to generate a hypothetical document that would
        answer the query, then embeds that instead of the query.

        Args:
            query: Normalized query string.

        Returns:
            Hypothetical document text.
        """
        if self._hyde is None:
            from .hyde import HyDEGenerator

            self._hyde = HyDEGenerator(
                llm_gateway_url=self.config.llm_gateway_url,
                model=self.config.hyde_model,
                max_tokens=self.config.hyde_max_tokens,
            )

        return await self._hyde.generate(query)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _generate_embedding(self, text: str) -> tuple[list[float], int]:
        """Generate embedding for text using LLM Gateway.

        Uses BGE query prefix for query embeddings.

        Args:
            text: Text to embed.

        Returns:
            Tuple of (embedding vector, token count).
        """
        prefixed_text = f"{self.config.embedding_prefix}{text}"

        response = await self.http_client.post(
            self.config.embedding_endpoint,
            json={"input": [prefixed_text], "model": self.config.embedding_model},
        )
        response.raise_for_status()

        data = response.json()
        embedding = data["data"][0]["embedding"]
        tokens = data.get("usage", {}).get("total_tokens", 0)

        return embedding, tokens

    def _get_cache_key(self, query: str) -> str:
        """Generate deterministic cache key.

        Includes config options that affect output.

        Args:
            query: Original query string.

        Returns:
            Cache key string.
        """
        # Include config that affects output
        config_str = (
            f"{self.config.enable_expansion}:"
            f"{self.config.enable_hyde}:"
            f"{self.config.embedding_model}"
        )
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        return f"query:{config_hash}:{query_hash}"

    async def close(self):
        """Close HTTP client and cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._hyde:
            await self._hyde.close()
            self._hyde = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
