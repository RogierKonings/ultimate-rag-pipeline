"""Web scraper connector for crawling and scraping web pages.

This module provides a connector for ingesting documents from web pages
with support for crawling, rate limiting, and robots.txt compliance.
"""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator

from services.ingestion.connectors.base import (
    BaseConnector,
    DocumentMetadata,
    RawDocument,
)


class WebConnectorConfig(BaseModel):
    """Configuration for the web scraper connector."""

    start_urls: list[str] = Field(
        ...,
        min_length=1,
        description="List of URLs to start crawling from",
    )
    allowed_domains: list[str] | None = Field(
        default=None,
        description="List of domains to restrict crawling to",
    )
    max_depth: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Maximum crawl depth from start URLs",
    )
    max_pages: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum number of pages to crawl",
    )
    rate_limit: float = Field(
        default=1.0,
        gt=0,
        description="Maximum requests per second",
    )
    user_agent: str = Field(
        default="RAGPipeline/1.0 (+https://example.com/bot)",
        description="User-Agent header for HTTP requests",
    )
    respect_robots_txt: bool = Field(
        default=True,
        description="Whether to respect robots.txt directives",
    )
    extract_links: bool = Field(
        default=True,
        description="Whether to extract and follow links",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to include in requests",
    )
    timeout: int = Field(
        default=30,
        ge=1,
        description="Request timeout in seconds",
    )
    follow_redirects: bool = Field(
        default=True,
        description="Whether to follow HTTP redirects",
    )

    @field_validator("start_urls")
    @classmethod
    def validate_urls(cls, v: list[str]) -> list[str]:
        """Validate that all start URLs are properly formatted."""
        for url in v:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"Invalid URL: {url}")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "start_urls": ["https://docs.example.com/"],
                    "allowed_domains": ["docs.example.com"],
                    "max_depth": 3,
                    "max_pages": 500,
                    "rate_limit": 2.0,
                    "respect_robots_txt": True,
                    "extract_links": True,
                },
            ],
        },
    }


class WebConnector(BaseConnector):
    """Connector for web crawling and scraping.

    Implements breadth-first crawling with rate limiting and
    robots.txt compliance. Extracts and stores raw HTML content.

    Example:
        ```python
        config = WebConnectorConfig(
            start_urls=["https://docs.example.com/"],
            allowed_domains=["docs.example.com"],
            max_depth=2,
            max_pages=100,
            rate_limit=1.0,  # 1 request per second
            respect_robots_txt=True
        )
        async with WebConnector(config) as connector:
            async for doc in connector.stream_documents():
                print(f"Scraped: {doc.metadata.source_id}")
                soup = BeautifulSoup(doc.content, "html.parser")
                text = soup.get_text()
        ```
    """

    def __init__(self, config: WebConnectorConfig):
        """Initialize the web connector.

        Args:
            config: Configuration for the connector.
        """
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._visited: set[str] = set()
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._rate_semaphore: asyncio.Semaphore | None = None
        self._last_request_time: dict[str, float] = {}
        self._connected = False

    async def connect(self) -> None:
        """Initialize HTTP session and rate limiting.

        Raises:
            ConnectionError: If the session cannot be created.
        """
        try:
            headers = {
                "User-Agent": self.config.user_agent,
                **self.config.headers,
            }

            timeout = aiohttp.ClientTimeout(total=self.config.timeout)

            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            )

            # Semaphore to limit concurrent requests
            max_concurrent = max(1, int(self.config.rate_limit * 2))
            self._rate_semaphore = asyncio.Semaphore(max_concurrent)

            self._visited = set()
            self._robots_cache = {}
            self._last_request_time = {}
            self._connected = True

        except Exception as e:
            raise ConnectionError(f"Failed to create HTTP session: {e}") from e

    async def disconnect(self) -> None:
        """Close HTTP session and clean up resources."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._visited = set()
        self._robots_cache = {}
        self._last_request_time = {}
        self._connected = False

    def _normalize_url(self, url: str) -> str:
        """Normalize a URL for deduplication.

        Args:
            url: URL to normalize.

        Returns:
            Normalized URL string.
        """
        parsed = urlparse(url)
        # Remove fragment and normalize
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        # Remove trailing slash for consistency
        return normalized.rstrip("/")

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL.

        Args:
            url: URL to extract domain from.

        Returns:
            Domain string.
        """
        return urlparse(url).netloc

    def _is_allowed_domain(self, url: str) -> bool:
        """Check if a URL's domain is in the allowed list.

        Args:
            url: URL to check.

        Returns:
            True if domain is allowed, False otherwise.
        """
        if self.config.allowed_domains is None:
            return True
        domain = self._get_domain(url)
        return any(
            domain == allowed or domain.endswith(f".{allowed}")
            for allowed in self.config.allowed_domains
        )

    async def _get_robots_parser(self, url: str) -> RobotFileParser | None:
        """Get or fetch robots.txt parser for a URL's domain.

        Args:
            url: URL to get robots.txt for.

        Returns:
            RobotFileParser instance or None if not available.
        """
        if not self.config.respect_robots_txt:
            return None

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url not in self._robots_cache:
            robots_url = f"{base_url}/robots.txt"
            parser = RobotFileParser()

            try:
                async with self._session.get(robots_url) as response:
                    if response.status == 200:
                        content = await response.text()
                        parser.parse(content.splitlines())
                    else:
                        # No robots.txt - allow all
                        parser.parse([])
            except Exception:
                # Error fetching robots.txt - allow all
                parser.parse([])

            self._robots_cache[base_url] = parser

        return self._robots_cache[base_url]

    async def _is_allowed_by_robots(self, url: str) -> bool:
        """Check if a URL is allowed by robots.txt.

        Args:
            url: URL to check.

        Returns:
            True if allowed, False otherwise.
        """
        parser = await self._get_robots_parser(url)
        if parser is None:
            return True
        return parser.can_fetch(self.config.user_agent, url)

    async def _apply_rate_limit(self, domain: str) -> None:
        """Apply rate limiting for a domain.

        Args:
            domain: Domain to rate limit.
        """
        min_interval = 1.0 / self.config.rate_limit

        if domain in self._last_request_time:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time[domain]
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

        self._last_request_time[domain] = asyncio.get_event_loop().time()

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        """Extract links from HTML content.

        Args:
            html: HTML content to extract links from.
            base_url: Base URL for resolving relative links.

        Returns:
            List of absolute URLs.
        """
        links = []
        soup = BeautifulSoup(html, "html.parser")

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]

            # Skip anchors, javascript, mailto, etc.
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)

            # Only include http(s) URLs
            if absolute_url.startswith(("http://", "https://")):
                links.append(absolute_url)

        return links

    def _generate_source_id(self, url: str) -> str:
        """Generate a unique source ID for a URL.

        Args:
            url: URL to generate ID for.

        Returns:
            URL itself as the source ID.
        """
        return self._normalize_url(url)

    async def _fetch_page(self, url: str) -> tuple[bytes, dict] | None:
        """Fetch a single page with rate limiting.

        Args:
            url: URL to fetch.

        Returns:
            Tuple of (content, headers) or None if fetch failed.
        """
        domain = self._get_domain(url)

        async with self._rate_semaphore:
            await self._apply_rate_limit(domain)

            try:
                async with self._session.get(
                    url,
                    allow_redirects=self.config.follow_redirects,
                ) as response:
                    if response.status != 200:
                        return None

                    content = await response.read()
                    headers = dict(response.headers)

                    return content, headers

            except (TimeoutError, aiohttp.ClientError):
                return None

    async def list_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List available documents by crawling.

        Performs breadth-first crawling and yields metadata for each
        discovered page. This does not yield the full content.

        Args:
            path: Optional URL to start from (overrides start_urls).

        Yields:
            DocumentMetadata for each discovered page.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        # Initialize crawl queue with start URLs
        start_urls = [path] if path else self.config.start_urls
        queue: deque[tuple[str, int]] = deque()  # (url, depth)

        for url in start_urls:
            normalized = self._normalize_url(url)
            if normalized not in self._visited:
                queue.append((normalized, 0))
                self._visited.add(normalized)

        pages_crawled = 0

        while queue and pages_crawled < self.config.max_pages:
            url, depth = queue.popleft()

            # Check domain allowlist
            if not self._is_allowed_domain(url):
                continue

            # Check robots.txt
            if not await self._is_allowed_by_robots(url):
                continue

            # Fetch the page
            result = await self._fetch_page(url)
            if result is None:
                continue

            content, headers = result
            pages_crawled += 1

            # Build metadata
            content_type = headers.get("Content-Type", "text/html")

            yield DocumentMetadata(
                source_id=url,
                source_type="web",
                filename=url.split("/")[-1] or "index.html",
                mime_type=content_type.split(";")[0].strip(),
                size_bytes=len(content),
                extra={
                    "depth": depth,
                    "headers": {
                        k: v
                        for k, v in headers.items()
                        if k.lower() in ("content-type", "last-modified", "etag")
                    },
                },
            )

            # Extract and queue links if within depth limit
            if self.config.extract_links and depth < self.config.max_depth:
                try:
                    html = content.decode("utf-8", errors="ignore")
                    links = self._extract_links(html, url)

                    for link in links:
                        normalized_link = self._normalize_url(link)
                        if normalized_link not in self._visited:
                            self._visited.add(normalized_link)
                            queue.append((normalized_link, depth + 1))

                except Exception:
                    # Error extracting links - continue without them
                    pass

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single page by URL.

        Args:
            source_id: URL of the page to fetch.

        Returns:
            RawDocument containing the page content and metadata.

        Raises:
            ConnectionError: If not connected.
            FileNotFoundError: If the page cannot be fetched.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        url = source_id

        # Check domain allowlist
        if not self._is_allowed_domain(url):
            raise FileNotFoundError(f"Domain not allowed: {url}")

        # Check robots.txt
        if not await self._is_allowed_by_robots(url):
            raise FileNotFoundError(f"Blocked by robots.txt: {url}")

        # Fetch the page
        result = await self._fetch_page(url)
        if result is None:
            raise FileNotFoundError(f"Failed to fetch: {url}")

        content, headers = result
        content_type = headers.get("Content-Type", "text/html")

        metadata = DocumentMetadata(
            source_id=url,
            source_type="web",
            filename=url.split("/")[-1] or "index.html",
            mime_type=content_type.split(";")[0].strip(),
            size_bytes=len(content),
            extra={
                "headers": {
                    k: v
                    for k, v in headers.items()
                    if k.lower() in ("content-type", "last-modified", "etag")
                },
            },
        )

        return RawDocument(content=content, metadata=metadata)

    async def stream_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Stream all documents from crawling.

        Performs breadth-first crawling and yields full documents
        including content for each discovered page.

        Args:
            path: Optional URL to start from (overrides start_urls).

        Yields:
            RawDocument for each crawled page.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        # Reset visited set for fresh crawl
        self._visited = set()

        # Initialize crawl queue with start URLs
        start_urls = [path] if path else self.config.start_urls
        queue: deque[tuple[str, int]] = deque()  # (url, depth)

        for url in start_urls:
            normalized = self._normalize_url(url)
            if normalized not in self._visited:
                queue.append((normalized, 0))
                self._visited.add(normalized)

        pages_crawled = 0

        while queue and pages_crawled < self.config.max_pages:
            url, depth = queue.popleft()

            # Check domain allowlist
            if not self._is_allowed_domain(url):
                continue

            # Check robots.txt
            if not await self._is_allowed_by_robots(url):
                continue

            # Fetch the page
            result = await self._fetch_page(url)
            if result is None:
                continue

            content, headers = result
            pages_crawled += 1

            # Build metadata
            content_type = headers.get("Content-Type", "text/html")

            metadata = DocumentMetadata(
                source_id=url,
                source_type="web",
                filename=url.split("/")[-1] or "index.html",
                mime_type=content_type.split(";")[0].strip(),
                size_bytes=len(content),
                extra={
                    "depth": depth,
                    "headers": {
                        k: v
                        for k, v in headers.items()
                        if k.lower() in ("content-type", "last-modified", "etag")
                    },
                },
            )

            yield RawDocument(content=content, metadata=metadata)

            # Extract and queue links if within depth limit
            if self.config.extract_links and depth < self.config.max_depth:
                try:
                    html = content.decode("utf-8", errors="ignore")
                    links = self._extract_links(html, url)

                    for link in links:
                        normalized_link = self._normalize_url(link)
                        if normalized_link not in self._visited:
                            self._visited.add(normalized_link)
                            queue.append((normalized_link, depth + 1))

                except Exception:
                    # Error extracting links - continue without them
                    pass
