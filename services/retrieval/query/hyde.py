"""HyDE (Hypothetical Document Embeddings) for the Retrieval Service.

This module provides HyDE and multi-query generation for improved
retrieval quality on complex or ambiguous queries.
"""


import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class HyDEGenerator:
    """Generates Hypothetical Document Embeddings.

    HyDE improves retrieval by:
    1. Using LLM to generate a hypothetical document that answers the query
    2. Embedding that document instead of the query
    3. Searching for real documents similar to the hypothetical one

    This helps bridge the vocabulary gap between queries and documents.

    Reference: https://arxiv.org/abs/2212.10496
    """

    def __init__(
        self,
        llm_gateway_url: str = "http://localhost:8004",
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_tokens: int = 256,
        timeout: float = 30.0,
    ):
        """Initialize HyDE generator.

        Args:
            llm_gateway_url: URL of the LLM Gateway service.
            model: Model to use for document generation.
            max_tokens: Maximum tokens in generated document.
            timeout: Request timeout in seconds.
        """
        self.llm_gateway_url = llm_gateway_url
        self.model = model
        self.max_tokens = max_tokens
        self._http_client = httpx.AsyncClient(
            base_url=llm_gateway_url,
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def generate(self, query: str) -> str:
        """Generate a hypothetical document that would answer the query.

        Args:
            query: User's search query.

        Returns:
            Hypothetical document text.
        """
        prompt = self._build_prompt(query)

        response = await self._http_client.post(
            "/v1/completions",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": self.max_tokens,
                "temperature": 0.7,
                "stop": ["\n\n", "---", "Query:"],
            },
        )
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["text"].strip()


    def _build_prompt(self, query: str) -> str:
        """Build prompt for hypothetical document generation.

        The prompt instructs the LLM to write a document passage
        that would be a relevant answer to the query.

        Args:
            query: User's search query.

        Returns:
            Formatted prompt string.
        """
        return f"""You are a helpful assistant that writes document passages.
Given a search query, write a short, factual document passage that would
directly answer or be highly relevant to the query. Write as if you are
writing part of a technical document or knowledge base article.

Query: {query}

Document passage:"""

    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class MultiQueryGenerator:
    """Generates multiple query variations for improved recall.

    Useful for complex or ambiguous queries where different
    phrasings might match different relevant documents.
    """

    def __init__(
        self,
        llm_gateway_url: str = "http://localhost:8004",
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_queries: int = 3,
        timeout: float = 30.0,
    ):
        """Initialize multi-query generator.

        Args:
            llm_gateway_url: URL of the LLM Gateway service.
            model: Model to use for query generation.
            max_queries: Maximum number of query variations.
            timeout: Request timeout in seconds.
        """
        self.llm_gateway_url = llm_gateway_url
        self.model = model
        self.max_queries = max_queries
        self._http_client = httpx.AsyncClient(
            base_url=llm_gateway_url,
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def generate(self, query: str) -> list[str]:
        """Generate multiple query variations.

        Args:
            query: Original user query.

        Returns:
            List of query variations including the original.
        """
        prompt = f"""You are a helpful assistant that generates search queries.
Given an original query, generate {self.max_queries} alternative versions
that express the same information need but using different words or structure.

Original query: {query}

Generate {self.max_queries} alternative queries, one per line:"""

        response = await self._http_client.post(
            "/v1/completions",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()

        data = response.json()
        text = data["choices"][0]["text"].strip()

        # Parse and include original query
        variations = [query]  # Always include original
        for line in text.split("\n"):
            cleaned = line.strip().lstrip("0123456789.-) ")
            if cleaned and cleaned != query:
                variations.append(cleaned)

        return variations[: self.max_queries + 1]  # +1 for original

    async def close(self):
        """Close HTTP client."""
        await self._http_client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
