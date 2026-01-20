"""Unit tests for the filesystem connector."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.filesystem import (
    FilesystemConnector,
    FilesystemConnectorConfig,
)

# ============================================================================
# Local Filesystem Tests
# ============================================================================


class TestFilesystemConnectorLocal:
    """Tests for local filesystem operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "test.txt").write_text("Hello, World!")
            (Path(tmpdir) / "test.pdf").write_bytes(b"%PDF-1.4 test")
            (Path(tmpdir) / "subdir").mkdir()
            (Path(tmpdir) / "subdir" / "nested.txt").write_text("Nested content")
            yield tmpdir

    @pytest.fixture
    def config(self, temp_dir):
        """Create a basic local filesystem config."""
        return FilesystemConnectorConfig(
            base_path=temp_dir,
            storage_type="local",
            recursive=True,
        )

    @pytest.mark.asyncio
    async def test_connect_success(self, config):
        """Test successful connection to local filesystem."""
        connector = FilesystemConnector(config)
        await connector.connect()
        assert connector._connected is True
        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_connect_nonexistent_path(self):
        """Test connection failure for nonexistent path."""
        config = FilesystemConnectorConfig(
            base_path="/nonexistent/path",
            storage_type="local",
        )
        connector = FilesystemConnector(config)
        with pytest.raises(ConnectionError, match="does not exist"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_context_manager(self, config):
        """Test async context manager protocol."""
        async with FilesystemConnector(config) as connector:
            assert connector._connected is True
        assert connector._connected is False

    @pytest.mark.asyncio
    async def test_list_documents_recursive(self, config):
        """Test listing documents recursively."""
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]

            assert len(docs) == 3
            filenames = {doc.filename for doc in docs}
            assert filenames == {"test.txt", "test.pdf", "nested.txt"}

    @pytest.mark.asyncio
    async def test_list_documents_non_recursive(self, temp_dir):
        """Test listing documents non-recursively."""
        config = FilesystemConnectorConfig(
            base_path=temp_dir,
            storage_type="local",
            recursive=False,
        )
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]

            assert len(docs) == 2
            filenames = {doc.filename for doc in docs}
            assert filenames == {"test.txt", "test.pdf"}

    @pytest.mark.asyncio
    async def test_list_documents_with_extension_filter(self, temp_dir):
        """Test filtering by file extension."""
        config = FilesystemConnectorConfig(
            base_path=temp_dir,
            storage_type="local",
            file_extensions=[".txt"],
        )
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]

            assert len(docs) == 2
            for doc in docs:
                assert doc.filename.endswith(".txt")

    @pytest.mark.asyncio
    async def test_list_documents_subdirectory(self, config, temp_dir):
        """Test listing documents in a subdirectory."""
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents("subdir")]

            assert len(docs) == 1
            assert docs[0].filename == "nested.txt"

    @pytest.mark.asyncio
    async def test_fetch_document(self, config):
        """Test fetching a single document."""
        async with FilesystemConnector(config) as connector:
            doc = await connector.fetch_document("test.txt")

            assert doc.content == b"Hello, World!"
            assert doc.metadata.source_id == "test.txt"
            assert doc.metadata.source_type == "local"
            assert doc.metadata.filename == "test.txt"
            assert doc.metadata.size_bytes == 13

    @pytest.mark.asyncio
    async def test_fetch_document_not_found(self, config):
        """Test fetching a nonexistent document."""
        async with FilesystemConnector(config) as connector:
            with pytest.raises(FileNotFoundError):
                await connector.fetch_document("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_fetch_document_not_connected(self, config):
        """Test fetching without connection raises error."""
        connector = FilesystemConnector(config)
        with pytest.raises(ConnectionError, match="not connected"):
            await connector.fetch_document("test.txt")

    @pytest.mark.asyncio
    async def test_stream_documents(self, config):
        """Test streaming all documents."""
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.stream_documents()]

            assert len(docs) == 3
            contents = {doc.content for doc in docs}
            assert b"Hello, World!" in contents
            assert b"Nested content" in contents

    @pytest.mark.asyncio
    async def test_document_metadata(self, config):
        """Test that metadata is correctly populated."""
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]

            for doc in docs:
                assert doc.source_id is not None
                assert doc.source_type == "local"
                assert doc.filename is not None
                assert doc.size_bytes > 0
                assert "absolute_path" in doc.extra


# ============================================================================
# S3/MinIO Tests (Mocked)
# ============================================================================


class TestFilesystemConnectorS3:
    """Tests for S3 operations using mocked aioboto3."""

    @pytest.fixture
    def s3_config(self):
        """Create an S3 config."""
        return FilesystemConnectorConfig(
            base_path="test-bucket",
            storage_type="s3",
            s3_endpoint="http://localhost:9000",
            s3_access_key="test-key",
            s3_secret_key="test-secret",
            s3_bucket="test-bucket",
            s3_region="us-east-1",
        )

    @pytest.mark.asyncio
    async def test_connect_s3_success(self, s3_config):
        """Test successful S3 connection."""
        with patch("services.ingestion.connectors.filesystem.aioboto3") as mock_boto:
            # Mock the session and client
            mock_session = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.head_bucket = AsyncMock()
            mock_session.client.return_value = mock_client
            mock_boto.Session.return_value = mock_session

            connector = FilesystemConnector(s3_config)
            await connector.connect()

            assert connector._connected is True
            await connector.disconnect()

    @pytest.mark.asyncio
    async def test_connect_s3_failure(self, s3_config):
        """Test S3 connection failure."""
        with patch("services.ingestion.connectors.filesystem.aioboto3") as mock_boto:
            mock_session = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.head_bucket = AsyncMock(side_effect=Exception("Access Denied"))
            mock_session.client.return_value = mock_client
            mock_boto.Session.return_value = mock_session

            connector = FilesystemConnector(s3_config)
            with pytest.raises(ConnectionError, match="Failed to connect to S3"):
                await connector.connect()

    @pytest.mark.asyncio
    async def test_list_documents_s3(self, s3_config):
        """Test listing S3 objects."""
        from services.ingestion.connectors.base import DocumentMetadata

        connector = FilesystemConnector(s3_config)
        connector._connected = True

        # Create mock metadata objects
        mock_metadata = [
            DocumentMetadata(
                source_id="documents/file1.txt",
                source_type="s3",
                filename="file1.txt",
                mime_type="text/plain",
                size_bytes=100,
                extra={"bucket": "test-bucket"},
            ),
            DocumentMetadata(
                source_id="documents/file2.pdf",
                source_type="s3",
                filename="file2.pdf",
                mime_type="application/pdf",
                size_bytes=200,
                extra={"bucket": "test-bucket"},
            ),
        ]

        # Mock the internal method
        async def mock_list_s3(prefix=None):
            for meta in mock_metadata:
                yield meta

        with patch.object(connector, "_list_s3_files", mock_list_s3):
            docs = [doc async for doc in connector.list_documents("documents/")]

            assert len(docs) == 2
            assert docs[0].source_id == "documents/file1.txt"
            assert docs[0].source_type == "s3"
            assert docs[0].filename == "file1.txt"
            assert docs[0].size_bytes == 100
            assert "bucket" in docs[0].extra

    @pytest.mark.asyncio
    async def test_fetch_document_s3(self, s3_config):
        """Test fetching an S3 object."""
        test_content = b"Test S3 content"

        with patch("services.ingestion.connectors.filesystem.aioboto3") as mock_boto:
            mock_session = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.head_bucket = AsyncMock()

            # Mock download_fileobj to write content to buffer
            async def mock_download(Bucket, Key, Fileobj):
                Fileobj.write(test_content)

            mock_client.download_fileobj = mock_download
            mock_client.head_object = AsyncMock(
                return_value={
                    "ContentType": "text/plain",
                    "LastModified": datetime.now(UTC),
                    "ETag": '"abc123"',
                },
            )

            mock_session.client.return_value = mock_client
            mock_boto.Session.return_value = mock_session

            connector = FilesystemConnector(s3_config)
            await connector.connect()

            doc = await connector.fetch_document("test/file.txt")

            assert doc.content == test_content
            assert doc.metadata.source_id == "test/file.txt"
            assert doc.metadata.source_type == "s3"
            assert doc.metadata.mime_type == "text/plain"

            await connector.disconnect()


# ============================================================================
# MIME Type Detection Tests
# ============================================================================


class TestMimeTypeDetection:
    """Tests for MIME type detection."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_detect_mime_type_by_extension(self, temp_dir):
        """Test MIME type detection falls back to extension."""
        # Create files with known extensions
        (Path(temp_dir) / "test.txt").write_text("Hello")
        (Path(temp_dir) / "test.html").write_text("<html></html>")

        config = FilesystemConnectorConfig(base_path=temp_dir, storage_type="local")

        async with FilesystemConnector(config) as connector:
            txt_doc = await connector.fetch_document("test.txt")
            html_doc = await connector.fetch_document("test.html")

            # Extension-based detection
            assert txt_doc.metadata.mime_type in ("text/plain", "application/octet-stream")
            assert html_doc.metadata.mime_type in ("text/html", "application/octet-stream")


# ============================================================================
# Configuration Tests
# ============================================================================


class TestFilesystemConnectorConfig:
    """Tests for configuration validation."""

    def test_valid_local_config(self):
        """Test valid local filesystem config."""
        config = FilesystemConnectorConfig(
            base_path="/tmp/test",
            storage_type="local",
        )
        assert config.storage_type == "local"
        assert config.recursive is True

    def test_valid_s3_config(self):
        """Test valid S3 config."""
        config = FilesystemConnectorConfig(
            base_path="my-bucket",
            storage_type="s3",
            s3_endpoint="http://localhost:9000",
            s3_access_key="key",
            s3_secret_key="secret",
        )
        assert config.storage_type == "s3"
        assert config.s3_region == "us-east-1"

    def test_file_extensions_filter(self):
        """Test file extensions configuration."""
        config = FilesystemConnectorConfig(
            base_path="/tmp",
            file_extensions=[".PDF", ".txt", ".DOCX"],
        )
        # Extensions should be stored as-is but compared case-insensitively
        assert len(config.file_extensions) == 3
