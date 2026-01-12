"""Test fixtures for Celery tasks tests.

Provides Celery app configuration for synchronous testing with in-memory backend.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.fixture
def celery_config():
    """Celery configuration for testing.

    Uses in-memory broker and result backend for synchronous test execution.
    """
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True,  # Execute tasks synchronously
        "task_eager_propagates": True,  # Propagate exceptions
    }


@pytest.fixture
def celery_app(celery_config):
    """Celery app configured for testing."""
    from services.ingestion.tasks.celery_app import CeleryConfig, create_celery_app

    config = CeleryConfig(
        broker_url=celery_config["broker_url"],
        result_backend=celery_config["result_backend"],
    )
    app = create_celery_app(config)
    app.conf.update(celery_config)
    return app


@pytest.fixture
def mock_connector():
    """Mock source connector."""
    connector = MagicMock()
    connector.__aenter__ = AsyncMock(return_value=connector)
    connector.__aexit__ = AsyncMock(return_value=None)
    connector.fetch_document = AsyncMock()
    connector.list_documents = AsyncMock()
    return connector


@pytest.fixture
def mock_raw_document():
    """Mock raw document from connector."""
    from services.ingestion.connectors.base import DocumentMetadata, RawDocument

    return RawDocument(
        content=b"This is test content for the document.",
        metadata=DocumentMetadata(
            source_id="test-doc-001",
            source_type="filesystem",
            filename="test.txt",
            mime_type="text/plain",
            size_bytes=38,
        ),
    )


@pytest.fixture
def mock_parsed_document():
    """Mock parsed document from parser."""
    doc = MagicMock()
    doc.text = "This is test content for the document."
    doc.title = "Test Document"
    doc.author = None
    doc.created_date = None
    doc.modified_date = None
    return doc


@pytest.fixture
def mock_enriched_metadata():
    """Mock enriched metadata."""
    metadata = MagicMock()
    metadata.title = "Test Document"
    metadata.author = None
    metadata.model_dump = MagicMock(return_value={"title": "Test Document"})
    return metadata


@pytest.fixture
def mock_chunks():
    """Mock document chunks."""
    from services.ingestion.processors.chunking import Chunk

    return [
        Chunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="This is chunk 1 content.",
            chunk_index=0,
            start_char=0,
            end_char=24,
            token_count=6,
        ),
        Chunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="This is chunk 2 content.",
            chunk_index=1,
            start_char=25,
            end_char=49,
            token_count=6,
        ),
    ]


@pytest.fixture
def mock_embedding_results():
    """Mock embedding results."""
    result = MagicMock()
    result.results = [
        MagicMock(embedding=[0.1] * 1024, chunk_id=uuid4()),
        MagicMock(embedding=[0.2] * 1024, chunk_id=uuid4()),
    ]
    return result


@pytest.fixture
def acl_context():
    """Standard ACL context for testing."""
    return {
        "tenant_id": "test-tenant",
        "visibility": "private",
        "allowed_groups": [],
        "allowed_users": [],
        "custom_metadata": {},
    }


@pytest.fixture
def processing_config():
    """Standard processing config for testing."""
    return {
        "chunking_strategy": "recursive",
        "chunk_size": 300,
        "chunk_overlap": 50,
    }


@pytest.fixture
def source_config():
    """Standard source config for testing."""
    return {
        "base_path": "/tmp/test-docs",
    }


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for DLQ tests."""
    client = MagicMock()
    client.setex = MagicMock(return_value=True)
    client.get = MagicMock(return_value=None)
    client.delete = MagicMock(return_value=1)
    return client


@pytest.fixture
def mock_async_redis():
    """Mock async Redis client for status tracker tests."""
    client = AsyncMock()
    client.scan = AsyncMock(return_value=(0, []))
    client.get = AsyncMock(return_value=None)
    client.delete = AsyncMock(return_value=1)
    client.close = AsyncMock()
    return client
