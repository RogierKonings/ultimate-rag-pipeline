"""Unit tests for the web scraper connector."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from connectors.web import (
    WebConnector,
    WebConnectorConfig,
)

# ============================================================================
# Configuration Tests
# ============================================================================


class TestWebConnectorConfig:
    """Tests for configuration validation."""

    def test_valid_config(self):
        """Test valid web connector config."""
        config = WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
            max_depth=2,
            max_pages=100,
            rate_limit=1.0,
        )
        assert len(config.start_urls) == 1
        assert config.max_depth == 2

    def test_invalid_url(self):
        """Test invalid URL validation."""
        with pytest.raises(ValueError, match="Invalid URL"):
            WebConnectorConfig(
                start_urls=["not-a-valid-url"],
            )

    def test_multiple_start_urls(self):
        """Test multiple start URLs."""
        config = WebConnectorConfig(
            start_urls=[
                "https://example.com/",
                "https://docs.example.com/",
            ],
        )
        assert len(config.start_urls) == 2

    def test_default_values(self):
        """Test default configuration values."""
        config = WebConnectorConfig(
            start_urls=["https://example.com/"],
        )
        assert config.max_depth == 2
        assert config.max_pages == 100
        assert config.rate_limit == 1.0
        assert config.respect_robots_txt is True
        assert config.extract_links is True


# ============================================================================
# Connection Tests
# ============================================================================


class TestWebConnectorConnection:
    """Tests for connection handling."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
        )

    @pytest.mark.asyncio
    async def test_connect_success(self, config):
        """Test successful connection."""
        connector = WebConnector(config)
        await connector.connect()

        assert connector._connected is True
        assert connector._session is not None
        assert connector._rate_semaphore is not None

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, config):
        """Test disconnection."""
        connector = WebConnector(config)
        await connector.connect()
        await connector.disconnect()

        assert connector._connected is False
        assert connector._session is None

    @pytest.mark.asyncio
    async def test_context_manager(self, config):
        """Test async context manager."""
        async with WebConnector(config) as connector:
            assert connector._connected is True

        assert connector._connected is False


# ============================================================================
# URL Handling Tests
# ============================================================================


class TestURLHandling:
    """Tests for URL normalization and filtering."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com", "docs.example.com"],
        )

    def test_normalize_url(self, config):
        """Test URL normalization."""
        connector = WebConnector(config)

        # Remove trailing slash
        assert connector._normalize_url("https://example.com/") == "https://example.com"

        # Preserve path
        assert connector._normalize_url("https://example.com/path/") == "https://example.com/path"

        # Preserve query string
        assert (
            connector._normalize_url("https://example.com/path?q=1")
            == "https://example.com/path?q=1"
        )

    def test_get_domain(self, config):
        """Test domain extraction."""
        connector = WebConnector(config)

        assert connector._get_domain("https://example.com/path") == "example.com"
        assert connector._get_domain("https://sub.example.com/") == "sub.example.com"

    def test_is_allowed_domain(self, config):
        """Test domain allowlist checking."""
        connector = WebConnector(config)

        assert connector._is_allowed_domain("https://example.com/page") is True
        assert connector._is_allowed_domain("https://docs.example.com/") is True
        assert connector._is_allowed_domain("https://other.com/") is False

    def test_is_allowed_domain_no_restrictions(self):
        """Test with no domain restrictions."""
        config = WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=None,
        )
        connector = WebConnector(config)

        assert connector._is_allowed_domain("https://any-domain.com/") is True


# ============================================================================
# Link Extraction Tests
# ============================================================================


class TestLinkExtraction:
    """Tests for HTML link extraction."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
        )

    def test_extract_links_absolute(self, config):
        """Test extracting absolute links."""
        connector = WebConnector(config)
        html = """
        <html>
            <body>
                <a href="https://example.com/page1">Page 1</a>
                <a href="https://example.com/page2">Page 2</a>
            </body>
        </html>
        """
        links = connector._extract_links(html, "https://example.com/")

        assert len(links) == 2
        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links

    def test_extract_links_relative(self, config):
        """Test extracting and resolving relative links."""
        connector = WebConnector(config)
        html = """
        <html>
            <body>
                <a href="/page1">Page 1</a>
                <a href="page2">Page 2</a>
                <a href="../other">Other</a>
            </body>
        </html>
        """
        links = connector._extract_links(html, "https://example.com/docs/")

        assert "https://example.com/page1" in links
        assert "https://example.com/docs/page2" in links
        assert "https://example.com/other" in links

    def test_extract_links_skip_anchors(self, config):
        """Test skipping anchor links."""
        connector = WebConnector(config)
        html = """
        <html>
            <body>
                <a href="#section">Section</a>
                <a href="javascript:void(0)">JS Link</a>
                <a href="mailto:test@example.com">Email</a>
                <a href="tel:+1234567890">Phone</a>
            </body>
        </html>
        """
        links = connector._extract_links(html, "https://example.com/")

        assert len(links) == 0


# ============================================================================
# Page Fetching Tests (Mocked)
# ============================================================================


class TestPageFetching:
    """Tests for page fetching with mocked aiohttp."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
            rate_limit=10.0,  # Higher rate for tests
        )

    @pytest.mark.asyncio
    async def test_fetch_page_success(self, config):
        """Test successful page fetch."""
        html_content = b"<html><body>Hello World</body></html>"

        connector = WebConnector(config)
        connector._connected = True
        connector._rate_semaphore = asyncio.Semaphore(10)
        connector._last_request_time = {}

        # Create a properly structured mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=html_content)
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        connector._session = mock_session

        result = await connector._fetch_page("https://example.com/")

        assert result is not None
        content, headers = result
        assert content == html_content
        assert headers["Content-Type"] == "text/html"

    @pytest.mark.asyncio
    async def test_fetch_page_error(self, config):
        """Test page fetch with error response."""
        connector = WebConnector(config)
        connector._connected = True
        connector._rate_semaphore = asyncio.Semaphore(10)
        connector._last_request_time = {}

        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        connector._session = mock_session

        result = await connector._fetch_page("https://example.com/notfound")

        assert result is None


# ============================================================================
# Crawling Tests (Mocked)
# ============================================================================


class TestCrawling:
    """Tests for crawling functionality."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
            max_depth=1,
            max_pages=3,
            rate_limit=100.0,  # High rate for tests
            respect_robots_txt=False,
        )

    @pytest.mark.asyncio
    async def test_stream_documents(self, config):
        """Test streaming documents via crawling."""
        pages = {
            "https://example.com": (
                b'<html><body><a href="/page1">Link</a></body></html>',
                {"Content-Type": "text/html"},
            ),
            "https://example.com/page1": (
                b"<html><body>Page 1 Content</body></html>",
                {"Content-Type": "text/html"},
            ),
        }

        connector = WebConnector(config)

        # Mock _fetch_page
        async def mock_fetch(url):
            normalized = connector._normalize_url(url)
            return pages.get(normalized)

        connector._fetch_page = mock_fetch
        connector._connected = True

        docs = [doc async for doc in connector.stream_documents()]

        assert len(docs) == 2
        assert any(b"Page 1 Content" in doc.content for doc in docs)

    @pytest.mark.asyncio
    async def test_max_pages_limit(self, config):
        """Test that max_pages limit is respected."""
        connector = WebConnector(config)

        # Mock to return same page always with many links
        html = (
            b"<html><body>"
            + b"".join(f'<a href="/page{i}">Link {i}</a>'.encode() for i in range(100))
            + b"</body></html>"
        )

        async def mock_fetch(url):
            return (html, {"Content-Type": "text/html"})

        connector._fetch_page = mock_fetch
        connector._connected = True

        docs = [doc async for doc in connector.stream_documents()]

        # Should stop at max_pages
        assert len(docs) <= config.max_pages

    @pytest.mark.asyncio
    async def test_domain_filtering(self):
        """Test that only allowed domains are crawled."""
        config = WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
            max_depth=1,
            max_pages=10,
            rate_limit=100.0,
            respect_robots_txt=False,
        )

        connector = WebConnector(config)

        html = b"""<html><body>
            <a href="https://example.com/page1">Internal</a>
            <a href="https://external.com/page">External</a>
        </body></html>"""

        pages = {
            "https://example.com": (html, {"Content-Type": "text/html"}),
            "https://example.com/page1": (b"<html>Page 1</html>", {"Content-Type": "text/html"}),
        }

        async def mock_fetch(url):
            normalized = connector._normalize_url(url)
            return pages.get(normalized)

        connector._fetch_page = mock_fetch
        connector._connected = True

        docs = [doc async for doc in connector.stream_documents()]

        # Only example.com pages should be crawled
        for doc in docs:
            assert "example.com" in doc.metadata.source_id


# ============================================================================
# Robots.txt Tests
# ============================================================================


class TestRobotsTxt:
    """Tests for robots.txt handling."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            respect_robots_txt=True,
        )

    @pytest.mark.asyncio
    async def test_robots_txt_parsing(self, config):
        """Test robots.txt parsing."""
        robots_content = """
User-agent: *
Disallow: /private/
Allow: /public/
"""
        connector = WebConnector(config)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=robots_content)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        connector._session = mock_session

        parser = await connector._get_robots_parser("https://example.com/page")

        assert parser is not None
        # Can fetch public but not private
        assert parser.can_fetch("*", "https://example.com/public/page")
        assert not parser.can_fetch("*", "https://example.com/private/page")


# ============================================================================
# Fetch Document Tests
# ============================================================================


class TestFetchDocument:
    """Tests for single document fetching."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            allowed_domains=["example.com"],
            respect_robots_txt=False,
        )

    @pytest.mark.asyncio
    async def test_fetch_document_success(self, config):
        """Test fetching a single document by URL."""
        html_content = b"<html><body>Test Content</body></html>"

        connector = WebConnector(config)

        async def mock_fetch(url):
            return (html_content, {"Content-Type": "text/html; charset=utf-8"})

        connector._fetch_page = mock_fetch
        connector._connected = True

        doc = await connector.fetch_document("https://example.com/page")

        assert doc.content == html_content
        assert doc.metadata.source_id == "https://example.com/page"
        assert doc.metadata.source_type == "web"
        assert doc.metadata.mime_type == "text/html"

    @pytest.mark.asyncio
    async def test_fetch_document_not_found(self, config):
        """Test fetching nonexistent document."""
        connector = WebConnector(config)

        async def mock_fetch(url):
            return None

        connector._fetch_page = mock_fetch
        connector._connected = True

        with pytest.raises(FileNotFoundError, match="Failed to fetch"):
            await connector.fetch_document("https://example.com/notfound")

    @pytest.mark.asyncio
    async def test_fetch_document_domain_not_allowed(self, config):
        """Test fetching from disallowed domain."""
        connector = WebConnector(config)
        connector._connected = True

        with pytest.raises(FileNotFoundError, match="Domain not allowed"):
            await connector.fetch_document("https://other-domain.com/page")

    @pytest.mark.asyncio
    async def test_fetch_document_not_connected(self, config):
        """Test fetching without connection."""
        connector = WebConnector(config)

        with pytest.raises(ConnectionError, match="not connected"):
            await connector.fetch_document("https://example.com/page")


# ============================================================================
# Metadata Tests
# ============================================================================


class TestMetadata:
    """Tests for document metadata generation."""

    @pytest.fixture
    def config(self):
        return WebConnectorConfig(
            start_urls=["https://example.com/"],
            respect_robots_txt=False,
        )

    @pytest.mark.asyncio
    async def test_metadata_extraction(self, config):
        """Test metadata extraction from crawled pages."""
        connector = WebConnector(config)

        html = b"<html><body>Content</body></html>"
        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            "ETag": '"abc123"',
        }

        async def mock_fetch(url):
            return (html, headers)

        connector._fetch_page = mock_fetch
        connector._connected = True

        doc = await connector.fetch_document("https://example.com/docs/page.html")

        assert doc.metadata.source_type == "web"
        assert doc.metadata.filename == "page.html"
        assert doc.metadata.mime_type == "text/html"
        assert doc.metadata.size_bytes == len(html)
        assert "headers" in doc.metadata.extra
