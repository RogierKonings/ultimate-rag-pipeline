"""REST API connector for fetching documents from APIs.

This module provides a connector for ingesting documents from REST APIs
with support for various authentication methods and pagination styles.
"""

import asyncio
import base64
from collections.abc import AsyncIterator
from typing import Any, Literal

import aiohttp
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError
from pydantic import BaseModel, Field, field_validator

from services.ingestion.connectors.base import (
    BaseConnector,
    DocumentMetadata,
    RawDocument,
)


class APIConnectorConfig(BaseModel):
    """Configuration for the REST API connector.

    Supports various authentication methods and pagination styles.
    """

    base_url: str = Field(
        ...,
        description="Base URL of the API (e.g., 'https://api.example.com/v1')",
    )
    list_endpoint: str = Field(
        ...,
        description="Endpoint to list documents (e.g., '/documents')",
    )
    fetch_endpoint: str = Field(
        ...,
        description="Endpoint pattern to fetch a single document (e.g., '/documents/{id}')",
    )
    auth_type: Literal["none", "bearer", "api_key", "basic"] = Field(
        default="none",
        description="Authentication type",
    )
    auth_token: str | None = Field(
        default=None,
        description="Bearer token or API key value",
    )
    api_key_header: str | None = Field(
        default="X-API-Key",
        description="Header name for API key authentication",
    )
    basic_username: str | None = Field(
        default=None,
        description="Username for basic authentication",
    )
    basic_password: str | None = Field(
        default=None,
        description="Password for basic authentication",
    )
    pagination_type: Literal["offset", "cursor", "page", "none"] = Field(
        default="offset",
        description="Pagination style used by the API",
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of items per page",
    )
    # JSONPath expressions for extracting data from responses
    items_json_path: str = Field(
        default="$.items[*]",
        description="JSONPath expression to extract items from list response",
    )
    content_json_path: str = Field(
        default="$.content",
        description="JSONPath expression to extract content from item",
    )
    id_json_path: str = Field(
        default="$.id",
        description="JSONPath expression to extract ID from item",
    )
    # Pagination field names
    offset_param: str = Field(
        default="offset",
        description="Query parameter name for offset pagination",
    )
    limit_param: str = Field(
        default="limit",
        description="Query parameter name for limit/page size",
    )
    cursor_param: str = Field(
        default="cursor",
        description="Query parameter name for cursor pagination",
    )
    page_param: str = Field(
        default="page",
        description="Query parameter name for page number",
    )
    next_cursor_json_path: str = Field(
        default="$.next_cursor",
        description="JSONPath to extract next cursor from response",
    )
    total_json_path: str | None = Field(
        default="$.total",
        description="JSONPath to extract total count from response",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers",
    )
    timeout: int = Field(
        default=30,
        ge=1,
        description="Request timeout in seconds",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of retry attempts",
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0,
        description="Base delay between retries in seconds",
    )

    @field_validator("fetch_endpoint")
    @classmethod
    def validate_fetch_endpoint(cls, v: str) -> str:
        """Validate that fetch endpoint contains {id} placeholder."""
        if "{id}" not in v:
            raise ValueError("fetch_endpoint must contain {id} placeholder")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "base_url": "https://api.example.com/v1",
                    "list_endpoint": "/documents",
                    "fetch_endpoint": "/documents/{id}",
                    "auth_type": "bearer",
                    "auth_token": "eyJhbGciOi...",
                    "pagination_type": "offset",
                    "page_size": 50,
                    "items_json_path": "$.data[*]",
                    "content_json_path": "$.body",
                    "id_json_path": "$.document_id",
                },
                {
                    "base_url": "https://api.example.com",
                    "list_endpoint": "/api/articles",
                    "fetch_endpoint": "/api/articles/{id}",
                    "auth_type": "api_key",
                    "auth_token": "sk_live_...",
                    "api_key_header": "Authorization",
                    "pagination_type": "cursor",
                    "next_cursor_json_path": "$.meta.next_cursor",
                },
            ],
        },
    }


class APIConnector(BaseConnector):
    """Connector for REST APIs.

    Supports multiple authentication methods (Bearer, API Key, Basic)
    and pagination styles (offset, cursor, page-based).

    Example:
        ```python
        # Bearer token with offset pagination
        config = APIConnectorConfig(
            base_url="https://api.example.com/v1",
            list_endpoint="/documents",
            fetch_endpoint="/documents/{id}",
            auth_type="bearer",
            auth_token="your-token",
            pagination_type="offset",
            page_size=100,
            items_json_path="$.data[*]",
            content_json_path="$.content",
            id_json_path="$.id"
        )
        async with APIConnector(config) as connector:
            async for doc in connector.stream_documents():
                print(f"Document ID: {doc.metadata.source_id}")

        # API key with cursor pagination
        config = APIConnectorConfig(
            base_url="https://api.example.com",
            list_endpoint="/items",
            fetch_endpoint="/items/{id}",
            auth_type="api_key",
            auth_token="sk_live_xxx",
            api_key_header="X-API-Key",
            pagination_type="cursor",
            next_cursor_json_path="$.pagination.next"
        )
        async with APIConnector(config) as connector:
            async for doc in connector.stream_documents():
                process(doc)
        ```
    """

    def __init__(self, config: APIConnectorConfig):
        """Initialize the API connector.

        Args:
            config: Configuration for the connector.
        """
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._connected = False

        # Pre-compile JSONPath expressions
        try:
            self._items_path = jsonpath_parse(config.items_json_path)
            self._content_path = jsonpath_parse(config.content_json_path)
            self._id_path = jsonpath_parse(config.id_json_path)
            self._next_cursor_path = jsonpath_parse(config.next_cursor_json_path)
            self._total_path = (
                jsonpath_parse(config.total_json_path) if config.total_json_path else None
            )
        except JsonPathParserError as e:
            raise ValueError(f"Invalid JSONPath expression: {e}") from e

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on config.

        Returns:
            Dictionary of authentication headers.
        """
        headers = {}

        if self.config.auth_type == "bearer":
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

        elif self.config.auth_type == "api_key":
            if self.config.auth_token and self.config.api_key_header:
                headers[self.config.api_key_header] = self.config.auth_token

        elif self.config.auth_type == "basic":
            if self.config.basic_username and self.config.basic_password:
                credentials = f"{self.config.basic_username}:{self.config.basic_password}"
                encoded = base64.b64encode(credentials.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def connect(self) -> None:
        """Initialize HTTP session with authentication.

        Raises:
            ConnectionError: If the session cannot be created.
        """
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                **self._build_auth_headers(),
                **self.config.headers,
            }

            timeout = aiohttp.ClientTimeout(total=self.config.timeout)

            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            )

            # Test connection with a simple request
            url = f"{self.config.base_url.rstrip('/')}{self.config.list_endpoint}"
            params = {self.config.limit_param: 1}

            async with self._session.get(url, params=params) as response:
                if response.status == 401:
                    raise ConnectionError("Authentication failed")
                if response.status == 403:
                    raise ConnectionError("Access forbidden")
                if response.status >= 500:
                    raise ConnectionError(f"Server error: {response.status}")

            self._connected = True

        except aiohttp.ClientError as e:
            raise ConnectionError(f"Failed to connect to API: {e}") from e

    async def disconnect(self) -> None:
        """Close HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._connected = False

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request.
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            ConnectionError: If all retries fail.
        """
        last_error = None

        for attempt in range(self.config.max_retries + 1):
            try:
                async with self._session.request(method, url, params=params) as response:
                    if response.status == 429:  # Rate limited
                        retry_after = int(response.headers.get("Retry-After", 5))
                        await asyncio.sleep(retry_after)
                        continue

                    if response.status >= 500:  # Server error
                        if attempt < self.config.max_retries:
                            delay = self.config.retry_delay * (2**attempt)
                            await asyncio.sleep(delay)
                            continue

                    response.raise_for_status()
                    return await response.json()

            except (TimeoutError, aiohttp.ClientError) as e:
                last_error = e
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

        raise ConnectionError(
            f"Request failed after {self.config.max_retries} retries: {last_error}",
        )

    def _extract_items(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract items from API response using JSONPath.

        Args:
            data: API response data.

        Returns:
            List of item dictionaries.
        """
        matches = self._items_path.find(data)
        return [match.value for match in matches]

    def _extract_content(self, item: dict[str, Any]) -> bytes:
        """Extract content from an item using JSONPath.

        Args:
            item: Item dictionary.

        Returns:
            Content as bytes.
        """
        matches = self._content_path.find(item)
        if not matches:
            return b""

        content = matches[0].value

        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        if isinstance(content, str):
            return content.encode("utf-8")
        # Convert other types to JSON string
        import json

        return json.dumps(content).encode("utf-8")

    def _extract_id(self, item: dict[str, Any]) -> str:
        """Extract ID from an item using JSONPath.

        Args:
            item: Item dictionary.

        Returns:
            ID as string.
        """
        matches = self._id_path.find(item)
        if not matches:
            raise ValueError("Could not extract ID from item")
        return str(matches[0].value)

    def _extract_next_cursor(self, data: dict[str, Any]) -> str | None:
        """Extract next cursor from API response.

        Args:
            data: API response data.

        Returns:
            Next cursor string or None if no more pages.
        """
        matches = self._next_cursor_path.find(data)
        if not matches or matches[0].value is None:
            return None
        return str(matches[0].value)

    def _extract_total(self, data: dict[str, Any]) -> int | None:
        """Extract total count from API response.

        Args:
            data: API response data.

        Returns:
            Total count or None if not available.
        """
        if self._total_path is None:
            return None
        matches = self._total_path.find(data)
        if not matches or matches[0].value is None:
            return None
        return int(matches[0].value)

    def _build_metadata(
        self,
        item: dict[str, Any],
        source_id: str,
        content_size: int,
    ) -> DocumentMetadata:
        """Build document metadata from an API item.

        Args:
            item: Item dictionary from API.
            source_id: Extracted document ID.
            content_size: Size of content in bytes.

        Returns:
            DocumentMetadata instance.
        """
        # Include all item fields except content in extra
        extra = {k: v for k, v in item.items() if not isinstance(v, (bytes, bytearray))}

        return DocumentMetadata(
            source_id=source_id,
            source_type="api",
            size_bytes=content_size,
            extra=extra,
        )

    async def _paginate_offset(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate through pages using offset pagination.

        Yields:
            Items from each page.
        """
        url = f"{self.config.base_url.rstrip('/')}{self.config.list_endpoint}"
        offset = 0

        while True:
            params = {
                self.config.offset_param: offset,
                self.config.limit_param: self.config.page_size,
            }

            data = await self._request_with_retry("GET", url, params)
            items = self._extract_items(data)

            if not items:
                break

            for item in items:
                yield item

            # Check if we've received fewer items than requested
            if len(items) < self.config.page_size:
                break

            offset += len(items)

    async def _paginate_cursor(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate through pages using cursor pagination.

        Yields:
            Items from each page.
        """
        url = f"{self.config.base_url.rstrip('/')}{self.config.list_endpoint}"
        cursor: str | None = None

        while True:
            params = {self.config.limit_param: self.config.page_size}
            if cursor:
                params[self.config.cursor_param] = cursor

            data = await self._request_with_retry("GET", url, params)
            items = self._extract_items(data)

            for item in items:
                yield item

            cursor = self._extract_next_cursor(data)
            if cursor is None:
                break

    async def _paginate_page(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate through pages using page number pagination.

        Yields:
            Items from each page.
        """
        url = f"{self.config.base_url.rstrip('/')}{self.config.list_endpoint}"
        page = 1

        while True:
            params = {
                self.config.page_param: page,
                self.config.limit_param: self.config.page_size,
            }

            data = await self._request_with_retry("GET", url, params)
            items = self._extract_items(data)

            if not items:
                break

            for item in items:
                yield item

            # Check if we've received fewer items than requested
            if len(items) < self.config.page_size:
                break

            page += 1

    async def _paginate_none(self) -> AsyncIterator[dict[str, Any]]:
        """Fetch all items without pagination.

        Yields:
            Items from the single response.
        """
        url = f"{self.config.base_url.rstrip('/')}{self.config.list_endpoint}"

        data = await self._request_with_retry("GET", url)
        items = self._extract_items(data)

        for item in items:
            yield item

    async def _paginate(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate through all items using configured pagination.

        Yields:
            Items from all pages.
        """
        if self.config.pagination_type == "offset":
            async for item in self._paginate_offset():
                yield item
        elif self.config.pagination_type == "cursor":
            async for item in self._paginate_cursor():
                yield item
        elif self.config.pagination_type == "page":
            async for item in self._paginate_page():
                yield item
        else:  # none
            async for item in self._paginate_none():
                yield item

    async def list_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List available documents from the API.

        Args:
            path: Ignored for API connector (endpoints are in config).

        Yields:
            DocumentMetadata for each item from the API.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        async for item in self._paginate():
            try:
                source_id = self._extract_id(item)
                content = self._extract_content(item)
                yield self._build_metadata(item, source_id, len(content))
            except Exception:
                # Skip items that can't be processed
                continue

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single document by ID from the API.

        Args:
            source_id: Document ID to fetch.

        Returns:
            RawDocument containing the document content and metadata.

        Raises:
            ConnectionError: If not connected.
            FileNotFoundError: If the document does not exist.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        # Build URL with ID
        endpoint = self.config.fetch_endpoint.replace("{id}", source_id)
        url = f"{self.config.base_url.rstrip('/')}{endpoint}"

        try:
            data = await self._request_with_retry("GET", url)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                raise FileNotFoundError(f"Document not found: {source_id}") from e
            raise

        content = self._extract_content(data)
        metadata = self._build_metadata(data, source_id, len(content))

        return RawDocument(content=content, metadata=metadata)

    async def stream_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Stream all documents from the API.

        Paginates through the list endpoint and yields complete
        documents including content.

        Args:
            path: Ignored for API connector (endpoints are in config).

        Yields:
            RawDocument for each item from the API.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        async for item in self._paginate():
            try:
                source_id = self._extract_id(item)
                content = self._extract_content(item)
                metadata = self._build_metadata(item, source_id, len(content))
                yield RawDocument(content=content, metadata=metadata)
            except Exception:
                # Skip items that can't be processed
                continue
