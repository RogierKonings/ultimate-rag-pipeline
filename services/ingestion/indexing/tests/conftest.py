"""Pytest fixtures for index writer tests."""

from uuid import uuid4

import pytest

from ..models import DocumentRecord, IndexedChunk


@pytest.fixture
def sample_chunk() -> IndexedChunk:
    """Create a sample IndexedChunk for testing."""
    return IndexedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="This is test content for the chunk.",
        embedding=[0.1] * 1024,
        chunk_index=0,
        token_count=10,
        tenant_id="tenant-1",
        visibility="private",
        allowed_groups=["group-1"],
        allowed_users=["user-1"],
        metadata={"source": "test"},
    )


@pytest.fixture
def sample_document() -> DocumentRecord:
    """Create a sample DocumentRecord for testing."""
    return DocumentRecord(
        document_id=uuid4(),
        source_uri="s3://bucket/test-source-id",
        source_type="filesystem",
        filename="test.pdf",
        mime_type="application/pdf",
        title="Test Document",
        author="Test Author",
        chunk_count=1,
        total_tokens=10,
        content_hash="a" * 64,  # SHA-256 placeholder
        version=1,
        tenant_id="tenant-1",
        visibility="private",
        allowed_groups=["group-1"],
        allowed_users=["user-1"],
    )


@pytest.fixture
def sample_chunks(sample_document) -> list[IndexedChunk]:
    """Create multiple sample IndexedChunks for testing."""
    chunks = []
    for i in range(10):
        chunks.append(
            IndexedChunk(
                chunk_id=uuid4(),
                document_id=sample_document.document_id,
                content=f"Test content for chunk {i}.",
                embedding=[0.1 + i * 0.01] * 1024,
                chunk_index=i,
                token_count=10,
                tenant_id="tenant-1",
                visibility="private",
                allowed_groups=["group-1"],
                allowed_users=["user-1"],
            ),
        )
    return chunks
