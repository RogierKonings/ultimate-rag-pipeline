"""Tests for index writer data models."""

from datetime import datetime
from uuid import uuid4

from ..models import DocumentRecord, DocumentStatus, IndexedChunk, WriteResult


class TestIndexedChunk:
    """Tests for IndexedChunk model."""

    def test_required_fields(self):
        """Test that required fields must be provided."""
        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            embedding=[0.1] * 1024,
            chunk_index=0,
            token_count=10,
            tenant_id="tenant-1",
        )
        assert chunk.content == "Test content"
        assert chunk.chunk_index == 0
        assert chunk.tenant_id == "tenant-1"

    def test_default_values(self):
        """Test default values for optional fields."""
        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test",
            embedding=[0.1] * 10,
            chunk_index=0,
            token_count=5,
            tenant_id="tenant-1",
        )
        assert chunk.parent_chunk_id is None
        assert chunk.source_page is None
        assert chunk.source_section is None
        assert chunk.metadata == {}
        assert chunk.visibility == "private"
        assert chunk.allowed_groups == []
        assert chunk.allowed_users == []

    def test_optional_fields(self):
        """Test setting optional fields."""
        parent_id = uuid4()
        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test",
            embedding=[0.1] * 10,
            chunk_index=0,
            token_count=5,
            tenant_id="tenant-1",
            parent_chunk_id=parent_id,
            source_page=5,
            source_section="Introduction",
            metadata={"key": "value"},
            visibility="group",
            allowed_groups=["group-1", "group-2"],
            allowed_users=["user-1"],
        )
        assert chunk.parent_chunk_id == parent_id
        assert chunk.source_page == 5
        assert chunk.source_section == "Introduction"
        assert chunk.metadata == {"key": "value"}
        assert chunk.visibility == "group"
        assert chunk.allowed_groups == ["group-1", "group-2"]
        assert chunk.allowed_users == ["user-1"]

    def test_embedding_as_list(self):
        """Test that embedding is stored as list."""
        embedding = [0.1, 0.2, 0.3]
        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test",
            embedding=embedding,
            chunk_index=0,
            token_count=5,
            tenant_id="tenant-1",
        )
        assert chunk.embedding == embedding
        assert isinstance(chunk.embedding, list)


class TestDocumentRecord:
    """Tests for DocumentRecord model."""

    def test_required_fields(self):
        """Test that required fields must be provided."""
        doc = DocumentRecord(
            document_id=uuid4(),
            source_uri="s3://bucket/source-123",
            source_type="filesystem",
            tenant_id="tenant-1",
        )
        assert doc.source_uri == "s3://bucket/source-123"
        assert doc.source_type == "filesystem"
        assert doc.tenant_id == "tenant-1"

    def test_default_values(self):
        """Test default values for optional fields."""
        doc = DocumentRecord(
            document_id=uuid4(),
            source_uri="s3://bucket/source-123",
            source_type="filesystem",
            tenant_id="tenant-1",
        )
        assert doc.filename is None
        assert doc.mime_type is None
        assert doc.title is None
        assert doc.author is None
        assert doc.chunk_count == 0
        assert doc.total_tokens == 0
        assert doc.content_hash == ""  # US-2.11: default empty
        assert doc.version == 1  # US-2.11: default version
        assert doc.visibility == "private"
        assert doc.allowed_groups == []
        assert doc.allowed_users == []
        assert doc.status == "pending"
        assert doc.error_message is None
        assert doc.indexed_at is None
        assert isinstance(doc.created_at, datetime)
        assert isinstance(doc.updated_at, datetime)

    def test_optional_fields(self):
        """Test setting optional fields."""
        doc = DocumentRecord(
            document_id=uuid4(),
            source_uri="s3://bucket/source-123",
            source_type="filesystem",
            tenant_id="tenant-1",
            filename="document.pdf",
            mime_type="application/pdf",
            title="Test Document",
            author="Test Author",
            chunk_count=10,
            total_tokens=1000,
            content_hash="abc123def456" * 5 + "abcd",  # 64 char hash
            version=2,
            visibility="public",
            allowed_groups=["group-1"],
            allowed_users=["user-1", "user-2"],
            status="indexed",
        )
        assert doc.filename == "document.pdf"
        assert doc.mime_type == "application/pdf"
        assert doc.title == "Test Document"
        assert doc.author == "Test Author"
        assert doc.chunk_count == 10
        assert doc.total_tokens == 1000
        assert doc.content_hash == "abc123def456" * 5 + "abcd"
        assert doc.version == 2
        assert doc.visibility == "public"
        assert doc.status == "indexed"


class TestWriteResult:
    """Tests for WriteResult model."""

    def test_success_result(self):
        """Test successful write result."""
        result = WriteResult(
            success=True,
            items_written=10,
            items_failed=0,
            duration_ms=50.5,
        )
        assert result.success
        assert result.items_written == 10
        assert result.items_failed == 0
        assert result.errors == []
        assert result.duration_ms == 50.5

    def test_failure_result(self):
        """Test failed write result."""
        result = WriteResult(
            success=False,
            items_written=5,
            items_failed=5,
            errors=["Error 1", "Error 2"],
            duration_ms=100.0,
        )
        assert not result.success
        assert result.items_written == 5
        assert result.items_failed == 5
        assert len(result.errors) == 2

    def test_default_errors(self):
        """Test that errors defaults to empty list."""
        result = WriteResult(
            success=True,
            items_written=1,
            items_failed=0,
            duration_ms=10.0,
        )
        assert result.errors == []


class TestDocumentStatus:
    """Tests for DocumentStatus enum."""

    def test_status_values(self):
        """Test that status enum has correct values."""
        assert DocumentStatus.PENDING == "pending"
        assert DocumentStatus.INDEXED == "indexed"
        assert DocumentStatus.FAILED == "failed"

    def test_status_is_string(self):
        """Test that status values are strings."""
        assert isinstance(DocumentStatus.PENDING.value, str)
        assert isinstance(DocumentStatus.INDEXED.value, str)
        assert isinstance(DocumentStatus.FAILED.value, str)
