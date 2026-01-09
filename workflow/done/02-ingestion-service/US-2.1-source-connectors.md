# US-2.1: Source Connectors

> **Story ID:** US-2.1  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Epic 1 (Infrastructure Setup)

## User Story

**As a** data engineer  
**I want** connectors for various data sources  
**So that** I can ingest documents from different systems

## Context

The ingestion service requires pluggable connectors to load documents from multiple sources. Each connector must implement a common interface to ensure consistency and extensibility. The connectors are the entry point of the ingestion pipeline.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── connectors/
    ├── __init__.py
    ├── base.py           # Abstract base class
    ├── filesystem.py     # Local + S3 connector
    ├── database.py       # PostgreSQL, MySQL connector
    ├── web.py            # Web scraper connector
    └── api.py            # REST API connector
```

### Base Connector Interface

Create an abstract base class that all connectors must implement:

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from pydantic import BaseModel
from datetime import datetime

class DocumentMetadata(BaseModel):
    source_id: str
    source_type: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    size_bytes: Optional[int] = None
    extra: dict = {}

class RawDocument(BaseModel):
    content: bytes
    metadata: DocumentMetadata

class BaseConnector(ABC):
    """Abstract base class for all source connectors."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the data source."""
        pass
    
    @abstractmethod
    async def list_documents(self, path: Optional[str] = None) -> AsyncIterator[DocumentMetadata]:
        """List available documents at the given path."""
        pass
    
    @abstractmethod
    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single document by its source ID."""
        pass
    
    @abstractmethod
    async def stream_documents(self, path: Optional[str] = None) -> AsyncIterator[RawDocument]:
        """Stream all documents from the given path."""
        pass
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

### 1. Filesystem Connector

Support both local filesystem and S3-compatible storage:

```python
from typing import Optional, AsyncIterator
import aiofiles
import aioboto3
from pathlib import Path

class FilesystemConnectorConfig(BaseModel):
    base_path: str
    storage_type: Literal["local", "s3"] = "local"
    s3_endpoint: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    recursive: bool = True
    file_extensions: Optional[list[str]] = None  # e.g., [".pdf", ".docx"]

class FilesystemConnector(BaseConnector):
    def __init__(self, config: FilesystemConnectorConfig):
        self.config = config
        self._s3_client = None
    
    # Implement all abstract methods
    # Support glob patterns for file filtering
    # Handle large files with streaming
    # Extract file metadata (size, mtime, mime type)
```

**Requirements:**
- Use `aiofiles` for async local file operations
- Use `aioboto3` for S3 operations
- Support MinIO as S3-compatible storage (architecture default)
- Detect MIME types using `python-magic`
- Support recursive directory traversal
- Filter by file extensions

### 2. Database Connector

Support PostgreSQL and MySQL:

```python
class DatabaseConnectorConfig(BaseModel):
    connection_string: str
    db_type: Literal["postgresql", "mysql"]
    query: str  # SQL query to fetch documents
    content_column: str  # Column containing document content
    id_column: str  # Column for unique identifier
    metadata_columns: list[str] = []  # Additional columns for metadata
    batch_size: int = 1000

class DatabaseConnector(BaseConnector):
    def __init__(self, config: DatabaseConnectorConfig):
        self.config = config
        self._pool = None
    
    # Use asyncpg for PostgreSQL
    # Use aiomysql for MySQL
    # Stream results with server-side cursors
    # Handle BLOB/TEXT content
```

**Requirements:**
- Use `asyncpg` for PostgreSQL connections
- Use `aiomysql` for MySQL connections
- Support connection pooling
- Stream large result sets using cursors
- Handle binary (BLOB) and text content

### 3. Web Scraper Connector

Crawl and scrape web pages:

```python
class WebConnectorConfig(BaseModel):
    start_urls: list[str]
    allowed_domains: Optional[list[str]] = None
    max_depth: int = 2
    max_pages: int = 100
    rate_limit: float = 1.0  # requests per second
    user_agent: str = "RAGPipeline/1.0"
    respect_robots_txt: bool = True
    extract_links: bool = True
    headers: dict[str, str] = {}

class WebConnector(BaseConnector):
    def __init__(self, config: WebConnectorConfig):
        self.config = config
        self._session = None
        self._visited = set()
    
    # Use aiohttp for async HTTP requests
    # Implement breadth-first crawling
    # Parse robots.txt
    # Extract and follow links
    # Handle rate limiting
```

**Requirements:**
- Use `aiohttp` for async HTTP requests
- Implement rate limiting with `asyncio.Semaphore`
- Parse `robots.txt` and respect directives
- Extract links using `beautifulsoup4`
- Handle redirects and error pages
- Store raw HTML content

### 4. REST API Connector

Fetch documents from REST APIs:

```python
class APIConnectorConfig(BaseModel):
    base_url: str
    list_endpoint: str  # Endpoint to list documents
    fetch_endpoint: str  # Endpoint pattern to fetch single doc (e.g., "/docs/{id}")
    auth_type: Literal["none", "bearer", "api_key", "basic"] = "none"
    auth_token: Optional[str] = None
    api_key_header: Optional[str] = None
    pagination_type: Literal["offset", "cursor", "page"] = "offset"
    page_size: int = 100
    content_json_path: str  # JSONPath to content field
    id_json_path: str  # JSONPath to ID field
    headers: dict[str, str] = {}

class APIConnector(BaseConnector):
    def __init__(self, config: APIConnectorConfig):
        self.config = config
        self._session = None
    
    # Handle various auth methods
    # Support pagination styles
    # Parse JSON responses
    # Handle rate limiting
```

**Requirements:**
- Use `aiohttp` for async HTTP requests
- Support Bearer token, API key, and Basic auth
- Implement pagination (offset, cursor, page-based)
- Use `jsonpath-ng` for extracting content from JSON
- Handle API rate limits with retry logic

## Acceptance Criteria

- [ ] Abstract `BaseConnector` class defined with all required methods
- [ ] `FilesystemConnector` supports local files and S3/MinIO
- [ ] `DatabaseConnector` supports PostgreSQL and MySQL with streaming
- [ ] `WebConnector` crawls with rate limiting and robots.txt respect
- [ ] `APIConnector` supports multiple auth and pagination methods
- [ ] All connectors implement async context manager protocol
- [ ] All connectors have type hints and Pydantic config models
- [ ] Unit tests for each connector with mocked dependencies
- [ ] Integration tests with real services (can use testcontainers)

## Testing Requirements

```python
# Example test structure
import pytest
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer

@pytest.fixture
async def minio_container():
    with MinioContainer() as minio:
        yield minio

@pytest.mark.asyncio
async def test_filesystem_connector_s3(minio_container):
    config = FilesystemConnectorConfig(
        base_path="test-bucket",
        storage_type="s3",
        s3_endpoint=minio_container.get_url(),
        # ...
    )
    async with FilesystemConnector(config) as connector:
        docs = [doc async for doc in connector.stream_documents()]
        assert len(docs) > 0
```

## Dependencies

- `aiofiles>=23.0.0`
- `aioboto3>=12.0.0`
- `asyncpg>=0.29.0`
- `aiomysql>=0.2.0`
- `aiohttp>=3.9.0`
- `beautifulsoup4>=4.12.0`
- `python-magic>=0.4.27`
- `jsonpath-ng>=1.6.0`
- `pydantic>=2.0.0`

## Definition of Done

- [ ] All connectors implemented and passing tests
- [ ] >90% test coverage for connector module
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
- [ ] Performance tested with large file sets (1000+ files)
