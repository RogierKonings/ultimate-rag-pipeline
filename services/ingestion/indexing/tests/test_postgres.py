"""Tests for PostgresWriter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from ..postgres import PostgresWriter, PostgresWriterConfig
from ..models import DocumentRecord


class TestPostgresWriterConfig:
    """Tests for PostgresWriterConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PostgresWriterConfig()
        assert config.connection_string == "postgresql://localhost:5432/rag_pipeline"
        assert config.min_pool_size == 2
        assert config.max_pool_size == 10
        assert config.table_name == "documents"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = PostgresWriterConfig(
            connection_string="postgresql://user:pass@host:5432/db",
            min_pool_size=5,
            max_pool_size=20,
            table_name="custom_documents",
        )
        assert config.connection_string == "postgresql://user:pass@host:5432/db"
        assert config.min_pool_size == 5
        assert config.max_pool_size == 20
        assert config.table_name == "custom_documents"


class TestPostgresWriter:
    """Tests for PostgresWriter."""

    @pytest.fixture
    def writer(self):
        """Create a PostgresWriter instance."""
        return PostgresWriter(PostgresWriterConfig())

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = AsyncMock()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock()
        conn.transaction = MagicMock(return_value=AsyncMock())

        # Make the connection context manager work
        pool.acquire = MagicMock(return_value=AsyncMock())
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock()

        pool.close = AsyncMock()

        return pool, conn

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self, writer):
        """Test that connect() creates a connection pool."""
        with patch("asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool

            await writer.connect()

            mock_create_pool.assert_called_once()
            assert writer._pool is not None

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self, writer, mock_pool):
        """Test that disconnect() closes the pool."""
        pool, _ = mock_pool
        writer._pool = pool

        await writer.disconnect()

        pool.close.assert_called_once()
        assert writer._pool is None

    @pytest.mark.asyncio
    async def test_ensure_index_creates_table(self, writer, mock_pool):
        """Test that ensure_index() creates table and indices."""
        pool, conn = mock_pool
        writer._pool = pool

        await writer.ensure_index()

        # Should execute CREATE TABLE and CREATE INDEX statements
        assert conn.execute.call_count >= 4  # 1 table + 4 indices

    @pytest.mark.asyncio
    async def test_write_upserts_documents(self, writer, mock_pool, sample_document):
        """Test that write() upserts documents."""
        pool, conn = mock_pool
        writer._pool = pool

        # Setup transaction context manager
        transaction = AsyncMock()
        transaction.__aenter__ = AsyncMock()
        transaction.__aexit__ = AsyncMock()
        conn.transaction.return_value = transaction

        result = await writer.write([sample_document])

        assert result.success
        assert result.items_written == 1
        assert conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_write_handles_errors(self, writer, mock_pool, sample_document):
        """Test that write() handles database errors."""
        pool, conn = mock_pool
        writer._pool = pool

        transaction = AsyncMock()
        transaction.__aenter__ = AsyncMock()
        transaction.__aexit__ = AsyncMock()
        conn.transaction.return_value = transaction

        conn.execute.side_effect = Exception("Database error")

        result = await writer.write([sample_document])

        assert not result.success
        assert result.items_failed == 1
        assert len(result.errors) == 1
        assert "Database error" in result.errors[0]

    @pytest.mark.asyncio
    async def test_delete_removes_documents(self, writer, mock_pool):
        """Test that delete() removes documents by ID."""
        pool, conn = mock_pool
        writer._pool = pool
        document_ids = [uuid4(), uuid4()]

        result = await writer.delete(document_ids)

        assert result.success
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_by_document(self, writer, mock_pool):
        """Test that delete_by_document() calls delete()."""
        pool, conn = mock_pool
        writer._pool = pool
        document_id = uuid4()

        result = await writer.delete_by_document(document_id)

        assert result.success
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status(self, writer, mock_pool):
        """Test that update_status() updates document status."""
        pool, conn = mock_pool
        writer._pool = pool
        document_id = uuid4()

        await writer.update_status(document_id, "indexed")

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "UPDATE" in call_args[0][0]
        assert call_args[0][1] == "indexed"

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, writer, mock_pool):
        """Test that update_status() includes error message."""
        pool, conn = mock_pool
        writer._pool = pool
        document_id = uuid4()

        await writer.update_status(document_id, "failed", "Error message")

        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert call_args[0][2] == "Error message"

    @pytest.mark.asyncio
    async def test_get_document_returns_record(self, writer, mock_pool):
        """Test that get_document() returns DocumentRecord."""
        pool, conn = mock_pool
        writer._pool = pool

        document_id = uuid4()
        conn.fetchrow.return_value = {
            "document_id": document_id,
            "source_uri": "s3://bucket/test-source",
            "source_type": "filesystem",
            "filename": "test.pdf",
            "mime_type": "application/pdf",
            "title": "Test",
            "author": "Author",
            "chunk_count": 10,
            "total_tokens": 100,
            "content_hash": "a" * 64,
            "version": 1,
            "tenant_id": "tenant-1",
            "visibility": "private",
            "allowed_groups": ["group-1"],
            "allowed_users": ["user-1"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "indexed_at": None,
            "status": "pending",
            "error_message": None,
        }

        result = await writer.get_document(document_id)

        assert result is not None
        assert result.document_id == document_id
        assert result.source_uri == "s3://bucket/test-source"
        assert result.tenant_id == "tenant-1"

    @pytest.mark.asyncio
    async def test_get_document_returns_none_for_missing(self, writer, mock_pool):
        """Test that get_document() returns None for missing document."""
        pool, conn = mock_pool
        writer._pool = pool
        conn.fetchrow.return_value = None

        result = await writer.get_document(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_write_raises_without_connection(self, writer, sample_document):
        """Test that write() raises error without connection."""
        with pytest.raises(RuntimeError, match="Pool not connected"):
            await writer.write([sample_document])

    @pytest.mark.asyncio
    async def test_context_manager(self, writer):
        """Test async context manager protocol."""
        with patch("asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_pool.close = AsyncMock()
            mock_create_pool.return_value = mock_pool

            async with writer:
                assert writer._pool is not None

            mock_pool.close.assert_called_once()
