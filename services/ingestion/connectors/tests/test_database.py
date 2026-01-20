"""Unit tests for the database connector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from connectors.database import (
    DatabaseConnector,
    DatabaseConnectorConfig,
)

# ============================================================================
# PostgreSQL Tests (Mocked)
# ============================================================================


class TestDatabaseConnectorPostgres:
    """Tests for PostgreSQL database operations."""

    @pytest.fixture
    def pg_config(self):
        """Create a PostgreSQL config."""
        return DatabaseConnectorConfig(
            connection_string="postgresql://user:pass@localhost:5432/testdb",
            db_type="postgresql",
            query="SELECT id, content, title FROM documents",
            content_column="content",
            id_column="id",
            metadata_columns=["title"],
            batch_size=100,
        )

    @pytest.mark.asyncio
    async def test_connect_postgresql_success(self, pg_config):
        """Test successful PostgreSQL connection."""
        mock_pool = AsyncMock()

        with patch.object(
            DatabaseConnector,
            "_connect_postgresql",
            new_callable=AsyncMock,
        ) as mock_connect:
            connector = DatabaseConnector(pg_config)
            connector._pool = mock_pool  # Simulate pool being created
            await connector.connect()

            assert connector._connected is True
            mock_connect.assert_called_once()

            await connector.disconnect()

    @pytest.mark.asyncio
    async def test_connect_postgresql_failure(self, pg_config):
        """Test PostgreSQL connection failure."""
        with patch.object(
            DatabaseConnector,
            "_connect_postgresql",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            connector = DatabaseConnector(pg_config)
            with pytest.raises(ConnectionError, match="Failed to connect"):
                await connector.connect()

    @pytest.mark.asyncio
    async def test_disconnect_postgresql(self, pg_config):
        """Test PostgreSQL disconnection."""
        mock_pool = AsyncMock()

        connector = DatabaseConnector(pg_config)
        connector._pool = mock_pool
        connector._connected = True

        await connector.disconnect()

        assert connector._connected is False
        assert connector._pool is None
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_documents_postgresql(self, pg_config):
        """Test streaming documents from PostgreSQL."""
        # Create mock rows
        mock_rows = [
            (1, b"Document 1 content", "Title 1"),
            (2, b"Document 2 content", "Title 2"),
            (3, "Text content", "Title 3"),  # Text content to test encoding
        ]
        columns = ["id", "content", "title"]

        async def mock_stream():
            for row in mock_rows:
                yield row, columns

        connector = DatabaseConnector(pg_config)
        connector._connected = True

        with patch.object(connector, "_stream_postgresql", mock_stream):
            docs = [doc async for doc in connector.stream_documents()]

            assert len(docs) == 3
            assert docs[0].content == b"Document 1 content"
            assert docs[0].metadata.source_id == "1"
            assert docs[0].metadata.source_type == "postgresql"
            assert docs[0].metadata.extra.get("title") == "Title 1"

            # Text content should be encoded to bytes
            assert docs[2].content == b"Text content"

    @pytest.mark.asyncio
    async def test_fetch_document_postgresql(self, pg_config):
        """Test fetching a single document from PostgreSQL."""
        connector = DatabaseConnector(pg_config)
        connector._connected = True

        # Mock fetchrow return
        mock_row = MagicMock()
        mock_row.keys.return_value = ["id", "content", "title"]
        mock_row.__getitem__ = lambda self, i: ["123", b"Test content", "Test Title"][i]

        async def mock_fetch(source_id):
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=mock_row)
            return mock_row, ["id", "content", "title"]

        with patch.object(connector, "_fetch_postgresql", new_callable=AsyncMock) as mock_fetch_pg:
            mock_fetch_pg.return_value.content = b"Test content"
            mock_fetch_pg.return_value.metadata.source_id = "123"

            # Use direct internal implementation test
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=mock_row)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            connector._pool = mock_pool

            doc = await connector.fetch_document("123")

            assert doc.content == b"Test content"
            assert doc.metadata.source_id == "123"

    @pytest.mark.asyncio
    async def test_fetch_document_not_found_postgresql(self, pg_config):
        """Test fetching nonexistent document from PostgreSQL."""
        connector = DatabaseConnector(pg_config)
        connector._connected = True

        # Create a proper async context manager mock for pool.acquire()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)
        connector._pool = mock_pool

        with pytest.raises(FileNotFoundError, match="Document not found"):
            await connector.fetch_document("nonexistent")


# ============================================================================
# MySQL Tests (Mocked)
# ============================================================================


class TestDatabaseConnectorMySQL:
    """Tests for MySQL database operations."""

    @pytest.fixture
    def mysql_config(self):
        """Create a MySQL config."""
        return DatabaseConnectorConfig(
            connection_string="mysql://user:pass@localhost:3306/testdb",
            db_type="mysql",
            query="SELECT id, body, author FROM articles",
            content_column="body",
            id_column="id",
            metadata_columns=["author"],
            batch_size=100,
        )

    @pytest.mark.asyncio
    async def test_connect_mysql_success(self, mysql_config):
        """Test successful MySQL connection."""
        with patch.object(
            DatabaseConnector,
            "_connect_mysql",
            new_callable=AsyncMock,
        ) as mock_connect:
            connector = DatabaseConnector(mysql_config)
            await connector.connect()

            assert connector._connected is True
            mock_connect.assert_called_once()

            await connector.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_mysql(self, mysql_config):
        """Test MySQL disconnection."""
        mock_pool = MagicMock()
        mock_pool.close = MagicMock()
        mock_pool.wait_closed = AsyncMock()

        connector = DatabaseConnector(mysql_config)
        connector._pool = mock_pool
        connector._connected = True

        await connector.disconnect()

        assert connector._connected is False
        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_documents_mysql(self, mysql_config):
        """Test streaming documents from MySQL."""
        # Create mock rows
        mock_rows = [
            (1, b"Article 1 body", "Author 1"),
            (2, b"Article 2 body", "Author 2"),
        ]
        columns = ["id", "body", "author"]

        async def mock_stream():
            for row in mock_rows:
                yield row, columns

        connector = DatabaseConnector(mysql_config)
        connector._connected = True

        with patch.object(connector, "_stream_mysql", mock_stream):
            docs = [doc async for doc in connector.stream_documents()]

            assert len(docs) == 2
            assert docs[0].content == b"Article 1 body"
            assert docs[0].metadata.source_id == "1"
            assert docs[0].metadata.source_type == "mysql"
            assert docs[0].metadata.extra.get("author") == "Author 1"


# ============================================================================
# Content Extraction Tests
# ============================================================================


class TestContentExtraction:
    """Tests for content extraction and encoding."""

    @pytest.fixture
    def pg_config(self):
        return DatabaseConnectorConfig(
            connection_string="postgresql://user:pass@localhost:5432/testdb",
            db_type="postgresql",
            query="SELECT id, content FROM docs",
            content_column="content",
            id_column="id",
        )

    def test_extract_content_bytes(self, pg_config):
        """Test extracting bytes content."""
        connector = DatabaseConnector(pg_config)
        content = connector._extract_content((1, b"Hello bytes"), 1)
        assert content == b"Hello bytes"

    def test_extract_content_text(self, pg_config):
        """Test extracting text content (encoded to bytes)."""
        connector = DatabaseConnector(pg_config)
        content = connector._extract_content((1, "Hello text"), 1)
        assert content == b"Hello text"

    def test_extract_content_none(self, pg_config):
        """Test extracting None content (returns empty bytes)."""
        connector = DatabaseConnector(pg_config)
        content = connector._extract_content((1, None), 1)
        assert content == b""

    def test_extract_content_memoryview(self, pg_config):
        """Test extracting memoryview content."""
        connector = DatabaseConnector(pg_config)
        data = b"Memory content"
        content = connector._extract_content((1, memoryview(data)), 1)
        assert content == data


# ============================================================================
# Configuration Tests
# ============================================================================


class TestDatabaseConnectorConfig:
    """Tests for configuration validation."""

    def test_valid_postgresql_config(self):
        """Test valid PostgreSQL config."""
        config = DatabaseConnectorConfig(
            connection_string="postgresql://user:pass@localhost:5432/db",
            db_type="postgresql",
            query="SELECT * FROM docs",
            content_column="content",
            id_column="id",
        )
        assert config.db_type == "postgresql"
        assert config.batch_size == 1000

    def test_valid_mysql_config(self):
        """Test valid MySQL config."""
        config = DatabaseConnectorConfig(
            connection_string="mysql://user:pass@localhost:3306/db",
            db_type="mysql",
            query="SELECT * FROM docs",
            content_column="body",
            id_column="doc_id",
        )
        assert config.db_type == "mysql"

    def test_custom_pool_size(self):
        """Test custom pool size configuration."""
        config = DatabaseConnectorConfig(
            connection_string="postgresql://localhost/db",
            db_type="postgresql",
            query="SELECT * FROM docs",
            content_column="content",
            id_column="id",
            pool_min_size=5,
            pool_max_size=20,
        )
        assert config.pool_min_size == 5
        assert config.pool_max_size == 20

    def test_batch_size_limits(self):
        """Test batch size validation."""
        config = DatabaseConnectorConfig(
            connection_string="postgresql://localhost/db",
            db_type="postgresql",
            query="SELECT * FROM docs",
            content_column="content",
            id_column="id",
            batch_size=5000,
        )
        assert config.batch_size == 5000


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.fixture
    def pg_config(self):
        return DatabaseConnectorConfig(
            connection_string="postgresql://user:pass@localhost:5432/testdb",
            db_type="postgresql",
            query="SELECT id, content FROM docs",
            content_column="content",
            id_column="id",
        )

    @pytest.mark.asyncio
    async def test_list_documents_not_connected(self, pg_config):
        """Test listing documents without connection."""
        connector = DatabaseConnector(pg_config)
        with pytest.raises(ConnectionError, match="not connected"):
            async for _ in connector.list_documents():
                pass

    @pytest.mark.asyncio
    async def test_stream_documents_not_connected(self, pg_config):
        """Test streaming documents without connection."""
        connector = DatabaseConnector(pg_config)
        with pytest.raises(ConnectionError, match="not connected"):
            async for _ in connector.stream_documents():
                pass

    @pytest.mark.asyncio
    async def test_fetch_document_not_connected(self, pg_config):
        """Test fetching document without connection."""
        connector = DatabaseConnector(pg_config)
        with pytest.raises(ConnectionError, match="not connected"):
            await connector.fetch_document("1")

    @pytest.mark.asyncio
    async def test_missing_driver_postgresql(self, pg_config):
        """Test error when asyncpg is not installed."""
        with patch.object(
            DatabaseConnector,
            "_connect_postgresql",
            new_callable=AsyncMock,
            side_effect=ImportError("No module named 'asyncpg'"),
        ):
            connector = DatabaseConnector(pg_config)
            with pytest.raises(ImportError, match="asyncpg"):
                await connector.connect()


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestContextManager:
    """Tests for async context manager protocol."""

    @pytest.fixture
    def pg_config(self):
        return DatabaseConnectorConfig(
            connection_string="postgresql://localhost/db",
            db_type="postgresql",
            query="SELECT * FROM docs",
            content_column="content",
            id_column="id",
        )

    @pytest.mark.asyncio
    async def test_context_manager(self, pg_config):
        """Test async context manager."""
        with patch.object(
            DatabaseConnector,
            "_connect_postgresql",
            new_callable=AsyncMock,
        ):
            async with DatabaseConnector(pg_config) as connector:
                assert connector._connected is True

            assert connector._connected is False
