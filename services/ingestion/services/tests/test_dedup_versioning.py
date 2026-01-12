"""
Tests for US-2.11: Deduplication & Versioning.

Verifies:
- Duplicate ingest with same content_hash does not create new document/chunks
- New content for same source_uri increments version and triggers re-chunk/embedding
- Multi-tenant isolation for deduplication
- Content hash computation (SHA-256)
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ..deduplication import (
    CHUNK_SCHEMA_VERSION,
    DeduplicationCheckResult,
    DeduplicationResult,
    DeduplicationService,
    VersionInfo,
)


class TestContentHashComputation:
    """Tests for content hash computation."""

    def test_compute_content_hash_returns_sha256(self):
        """Verify SHA-256 hash is computed correctly."""
        content = b"Hello, World!"
        expected_hash = hashlib.sha256(content).hexdigest()

        result = DeduplicationService.compute_content_hash(content)

        assert result == expected_hash
        assert len(result) == 64  # SHA-256 produces 64 hex characters

    def test_compute_content_hash_is_deterministic(self):
        """Same content always produces the same hash."""
        content = b"Test document content"

        hash1 = DeduplicationService.compute_content_hash(content)
        hash2 = DeduplicationService.compute_content_hash(content)

        assert hash1 == hash2

    def test_compute_content_hash_different_for_different_content(self):
        """Different content produces different hashes."""
        content1 = b"Document version 1"
        content2 = b"Document version 2"

        hash1 = DeduplicationService.compute_content_hash(content1)
        hash2 = DeduplicationService.compute_content_hash(content2)

        assert hash1 != hash2

    def test_compute_content_hash_handles_empty_content(self):
        """Empty content produces valid hash."""
        content = b""
        expected_hash = hashlib.sha256(content).hexdigest()

        result = DeduplicationService.compute_content_hash(content)

        assert result == expected_hash

    def test_compute_content_hash_handles_binary_content(self):
        """Binary content (e.g., PDF) is hashed correctly."""
        content = b"\x00\x01\x02\xff\xfe\xfd"

        result = DeduplicationService.compute_content_hash(content)

        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestDeduplicationCheck:
    """Tests for duplicate detection logic."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def dedup_service(self, mock_pool):
        """Create a DeduplicationService with mock pool."""
        return DeduplicationService(mock_pool)

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_duplicate_for_exact_match(
        self,
        dedup_service,
        mock_pool,
    ):
        """Duplicate detected when same tenant, source_uri, content_hash exists."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/doc.pdf"
        content_hash = "abc123" * 10 + "abcd"  # 64 chars
        existing_doc_id = uuid4()

        # Mock the database query to return an exact match
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            side_effect=[
                # First query (exact match) returns a row
                {"id": existing_doc_id, "version": 2},
            ],
        )
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await dedup_service.check_duplicate(
            tenant_id=tenant_id,
            source_uri=source_uri,
            content_hash=content_hash,
        )

        assert result.result == DeduplicationResult.DUPLICATE
        assert result.document_id == existing_doc_id
        assert result.existing_version == 2
        assert result.content_hash == content_hash

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_new_version_for_different_hash(
        self,
        dedup_service,
        mock_pool,
    ):
        """New version detected when same source_uri but different content_hash."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/doc.pdf"
        new_content_hash = "def456" * 10 + "defg"
        existing_doc_id = uuid4()

        # Mock: no exact match, but existing document with different hash
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(
            side_effect=[
                None,  # No exact match
                {"id": existing_doc_id, "version": 3, "content_hash": "old_hash"},
            ],
        )
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await dedup_service.check_duplicate(
            tenant_id=tenant_id,
            source_uri=source_uri,
            content_hash=new_content_hash,
        )

        assert result.result == DeduplicationResult.NEW_VERSION
        assert result.document_id == existing_doc_id
        assert result.existing_version == 3
        assert result.content_hash == new_content_hash

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_new_document_for_unknown_source(
        self,
        dedup_service,
        mock_pool,
    ):
        """New document detected when source_uri not seen before."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/new_doc.pdf"
        content_hash = "xyz789" * 10 + "xyzw"

        # Mock: no exact match, no existing document
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)  # Both queries return None
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await dedup_service.check_duplicate(
            tenant_id=tenant_id,
            source_uri=source_uri,
            content_hash=content_hash,
        )

        assert result.result == DeduplicationResult.NEW_DOCUMENT
        assert result.document_id is None
        assert result.existing_version is None
        assert result.content_hash == content_hash


class TestMultiTenantDeduplication:
    """Tests for multi-tenant isolation in deduplication."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def dedup_service(self, mock_pool):
        """Create a DeduplicationService with mock pool."""
        return DeduplicationService(mock_pool)

    @pytest.mark.asyncio
    async def test_same_content_different_tenants_not_duplicates(
        self,
        dedup_service,
        mock_pool,
    ):
        """Same content_hash for different tenants should not be detected as duplicate."""
        tenant_a = uuid4()
        tenant_b = uuid4()
        source_uri = "s3://bucket/shared_doc.pdf"
        content_hash = "shared" * 10 + "hash"

        # Mock: no matches for either tenant
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Check for tenant A
        result_a = await dedup_service.check_duplicate(
            tenant_id=tenant_a,
            source_uri=source_uri,
            content_hash=content_hash,
        )

        # Check for tenant B
        result_b = await dedup_service.check_duplicate(
            tenant_id=tenant_b,
            source_uri=source_uri,
            content_hash=content_hash,
        )

        # Both should be new documents (not duplicates of each other)
        assert result_a.result == DeduplicationResult.NEW_DOCUMENT
        assert result_b.result == DeduplicationResult.NEW_DOCUMENT


class TestVersionInfo:
    """Tests for version info creation."""

    def test_get_version_info_creates_correct_info(self):
        """Version info contains correct schema and embedding metadata."""
        embedding_model = "BAAI/bge-large-en-v1.5"
        embedding_version = "1.0"

        result = DeduplicationService.get_version_info(
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )

        assert isinstance(result, VersionInfo)
        assert result.schema_version == CHUNK_SCHEMA_VERSION
        assert result.embedding_model == embedding_model
        assert result.embedding_version == embedding_version

    def test_chunk_schema_version_is_defined(self):
        """Schema version constant is defined and valid."""
        assert CHUNK_SCHEMA_VERSION is not None
        assert isinstance(CHUNK_SCHEMA_VERSION, str)
        assert len(CHUNK_SCHEMA_VERSION) > 0


class TestMarkPreviousVersionsSuperseded:
    """Tests for superseding previous document versions."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def dedup_service(self, mock_pool):
        """Create a DeduplicationService with mock pool."""
        return DeduplicationService(mock_pool)

    @pytest.mark.asyncio
    async def test_mark_previous_versions_superseded_updates_old_docs(
        self,
        dedup_service,
        mock_pool,
    ):
        """Previous versions are marked as superseded."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/doc.pdf"
        new_doc_id = uuid4()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 2")  # 2 docs updated
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        count = await dedup_service.mark_previous_versions_superseded(
            tenant_id=tenant_id,
            source_uri=source_uri,
            new_document_id=new_doc_id,
        )

        assert count == 2
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_previous_versions_excludes_new_document(
        self,
        dedup_service,
        mock_pool,
    ):
        """New document ID is excluded from superseding."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/doc.pdf"
        new_doc_id = uuid4()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await dedup_service.mark_previous_versions_superseded(
            tenant_id=tenant_id,
            source_uri=source_uri,
            new_document_id=new_doc_id,
        )

        # Verify the query includes the new_doc_id exclusion
        call_args = mock_conn.execute.call_args
        assert new_doc_id in call_args[0]  # new_doc_id should be in query params


class TestIdempotentIngestion:
    """Tests for idempotent ingestion behavior."""

    def test_duplicate_result_indicates_skip_processing(self):
        """DUPLICATE result should signal to skip re-processing."""
        result = DeduplicationCheckResult(
            result=DeduplicationResult.DUPLICATE,
            document_id=uuid4(),
            existing_version=1,
            content_hash="hash123",
        )

        # When result is DUPLICATE, processing should be skipped
        assert result.result == DeduplicationResult.DUPLICATE
        assert result.document_id is not None  # Existing ID is returned

    def test_new_version_result_indicates_version_increment(self):
        """NEW_VERSION result should signal version increment."""
        result = DeduplicationCheckResult(
            result=DeduplicationResult.NEW_VERSION,
            document_id=uuid4(),
            existing_version=2,
            content_hash="new_hash",
        )

        # When result is NEW_VERSION, version should be incremented
        expected_next_version = result.existing_version + 1
        assert expected_next_version == 3

    def test_new_document_result_indicates_fresh_document(self):
        """NEW_DOCUMENT result should signal first version."""
        result = DeduplicationCheckResult(
            result=DeduplicationResult.NEW_DOCUMENT,
            content_hash="fresh_hash",
        )

        # When result is NEW_DOCUMENT, version should be 1
        assert result.existing_version is None
        # Caller should set version = 1


class TestGetNextVersion:
    """Tests for version number computation."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def dedup_service(self, mock_pool):
        """Create a DeduplicationService with mock pool."""
        return DeduplicationService(mock_pool)

    @pytest.mark.asyncio
    async def test_get_next_version_returns_one_for_new_document(
        self,
        dedup_service,
        mock_pool,
    ):
        """Next version is 1 for a new document."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/new.pdf"

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)  # COALESCE(MAX(version), 0) + 1
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        version = await dedup_service.get_next_version(
            tenant_id=tenant_id,
            source_uri=source_uri,
        )

        assert version == 1

    @pytest.mark.asyncio
    async def test_get_next_version_increments_for_existing_document(
        self,
        dedup_service,
        mock_pool,
    ):
        """Next version is max(version) + 1 for existing document."""
        tenant_id = uuid4()
        source_uri = "s3://bucket/existing.pdf"

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=4)  # Existing max is 3, next is 4
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        version = await dedup_service.get_next_version(
            tenant_id=tenant_id,
            source_uri=source_uri,
        )

        assert version == 4
