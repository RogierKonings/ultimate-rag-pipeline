"""Integration tests for connectors using testcontainers.

These tests require Docker to be running and will spin up real
instances of MinIO, PostgreSQL, and HTTP servers for testing.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

# Skip all integration tests if testcontainers is not available
pytest.importorskip("testcontainers")

from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer

from services.ingestion.connectors.filesystem import (
    FilesystemConnector,
    FilesystemConnectorConfig,
)
from services.ingestion.connectors.database import (
    DatabaseConnector,
    DatabaseConnectorConfig,
)


# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


# ============================================================================
# MinIO/S3 Integration Tests
# ============================================================================


class TestFilesystemConnectorMinIO:
    """Integration tests for S3 connector with MinIO."""

    @pytest.fixture(scope="class")
    def minio_container(self):
        """Start MinIO container for testing."""
        with MinioContainer() as minio:
            # Get connection details
            yield {
                "endpoint": f"http://{minio.get_container_host_ip()}:{minio.get_exposed_port(9000)}",
                "access_key": minio.access_key,
                "secret_key": minio.secret_key,
            }

    @pytest.fixture
    def test_bucket(self, minio_container):
        """Create a test bucket with sample files."""
        import boto3
        from botocore.config import Config
        
        s3_client = boto3.client(
            "s3",
            endpoint_url=minio_container["endpoint"],
            aws_access_key_id=minio_container["access_key"],
            aws_secret_access_key=minio_container["secret_key"],
            config=Config(signature_version="s3v4"),
        )
        
        bucket_name = "test-bucket"
        
        # Create bucket
        try:
            s3_client.create_bucket(Bucket=bucket_name)
        except s3_client.exceptions.BucketAlreadyOwnedByYou:
            pass
        
        # Upload test files
        test_files = {
            "documents/file1.txt": b"Content of file 1",
            "documents/file2.txt": b"Content of file 2",
            "documents/subdir/file3.txt": b"Nested file content",
            "images/image.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        }
        
        for key, content in test_files.items():
            s3_client.put_object(Bucket=bucket_name, Key=key, Body=content)
        
        yield bucket_name, test_files
        
        # Cleanup
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        for obj in response.get("Contents", []):
            s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])
        s3_client.delete_bucket(Bucket=bucket_name)

    @pytest.mark.asyncio
    async def test_connect_to_minio(self, minio_container, test_bucket):
        """Test connecting to MinIO."""
        bucket_name, _ = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
        )
        
        async with FilesystemConnector(config) as connector:
            assert connector._connected is True

    @pytest.mark.asyncio
    async def test_list_documents_minio(self, minio_container, test_bucket):
        """Test listing documents from MinIO."""
        bucket_name, test_files = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]
            
            assert len(docs) == len(test_files)
            source_ids = {doc.source_id for doc in docs}
            assert "documents/file1.txt" in source_ids

    @pytest.mark.asyncio
    async def test_list_documents_with_prefix(self, minio_container, test_bucket):
        """Test listing documents with prefix filter."""
        bucket_name, _ = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents("documents/")]
            
            assert len(docs) == 3  # Only documents/ prefix

    @pytest.mark.asyncio
    async def test_fetch_document_minio(self, minio_container, test_bucket):
        """Test fetching a single document from MinIO."""
        bucket_name, test_files = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
        )
        
        async with FilesystemConnector(config) as connector:
            doc = await connector.fetch_document("documents/file1.txt")
            
            assert doc.content == test_files["documents/file1.txt"]
            assert doc.metadata.source_id == "documents/file1.txt"
            assert doc.metadata.source_type == "s3"

    @pytest.mark.asyncio
    async def test_stream_documents_minio(self, minio_container, test_bucket):
        """Test streaming all documents from MinIO."""
        bucket_name, test_files = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.stream_documents()]
            
            assert len(docs) == len(test_files)
            # Verify content matches
            for doc in docs:
                expected_content = test_files[doc.metadata.source_id]
                assert doc.content == expected_content

    @pytest.mark.asyncio
    async def test_file_extension_filter_minio(self, minio_container, test_bucket):
        """Test file extension filtering."""
        bucket_name, _ = test_bucket
        
        config = FilesystemConnectorConfig(
            base_path=bucket_name,
            storage_type="s3",
            s3_endpoint=minio_container["endpoint"],
            s3_access_key=minio_container["access_key"],
            s3_secret_key=minio_container["secret_key"],
            s3_bucket=bucket_name,
            file_extensions=[".txt"],
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]
            
            assert len(docs) == 3  # Only .txt files
            for doc in docs:
                assert doc.filename.endswith(".txt")


# ============================================================================
# PostgreSQL Integration Tests
# ============================================================================


class TestDatabaseConnectorPostgres:
    """Integration tests for database connector with PostgreSQL."""

    @pytest.fixture(scope="class")
    def postgres_container(self):
        """Start PostgreSQL container for testing."""
        with PostgresContainer("postgres:16") as postgres:
            yield {
                "connection_string": postgres.get_connection_url().replace(
                    "postgresql+psycopg2://", "postgresql://"
                ),
                "host": postgres.get_container_host_ip(),
                "port": postgres.get_exposed_port(5432),
                "user": postgres.username,
                "password": postgres.password,
                "database": postgres.dbname,
            }

    @pytest.fixture
    def test_data(self, postgres_container):
        """Create test table and data."""
        import psycopg2
        
        conn = psycopg2.connect(postgres_container["connection_string"])
        cursor = conn.cursor()
        
        # Create test table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                title VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Insert test data
        test_docs = [
            ("Content of document 1", "Document 1"),
            ("Content of document 2", "Document 2"),
            ("Content of document 3", "Document 3"),
        ]
        
        for content, title in test_docs:
            cursor.execute(
                "INSERT INTO documents (content, title) VALUES (%s, %s)",
                (content, title)
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        yield test_docs
        
        # Cleanup
        conn = psycopg2.connect(postgres_container["connection_string"])
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS documents")
        conn.commit()
        cursor.close()
        conn.close()

    @pytest.mark.asyncio
    async def test_connect_to_postgres(self, postgres_container, test_data):
        """Test connecting to PostgreSQL."""
        config = DatabaseConnectorConfig(
            connection_string=postgres_container["connection_string"],
            db_type="postgresql",
            query="SELECT id, content, title FROM documents",
            content_column="content",
            id_column="id",
        )
        
        async with DatabaseConnector(config) as connector:
            assert connector._connected is True

    @pytest.mark.asyncio
    async def test_stream_documents_postgres(self, postgres_container, test_data):
        """Test streaming documents from PostgreSQL."""
        config = DatabaseConnectorConfig(
            connection_string=postgres_container["connection_string"],
            db_type="postgresql",
            query="SELECT id, content, title FROM documents ORDER BY id",
            content_column="content",
            id_column="id",
            metadata_columns=["title"],
        )
        
        async with DatabaseConnector(config) as connector:
            docs = [doc async for doc in connector.stream_documents()]
            
            assert len(docs) == len(test_data)
            
            # Verify content
            for i, doc in enumerate(docs):
                expected_content, expected_title = test_data[i]
                assert doc.content == expected_content.encode("utf-8")
                assert doc.metadata.extra.get("title") == expected_title

    @pytest.mark.asyncio
    async def test_fetch_document_postgres(self, postgres_container, test_data):
        """Test fetching a single document from PostgreSQL."""
        config = DatabaseConnectorConfig(
            connection_string=postgres_container["connection_string"],
            db_type="postgresql",
            query="SELECT id, content, title FROM documents",
            content_column="content",
            id_column="id",
        )
        
        async with DatabaseConnector(config) as connector:
            doc = await connector.fetch_document("1")
            
            assert doc.content == test_data[0][0].encode("utf-8")
            assert doc.metadata.source_id == "1"

    @pytest.mark.asyncio
    async def test_batch_streaming_postgres(self, postgres_container):
        """Test batch streaming with larger dataset."""
        import psycopg2
        
        # Insert more data
        conn = psycopg2.connect(postgres_container["connection_string"])
        cursor = conn.cursor()
        
        for i in range(100):
            cursor.execute(
                "INSERT INTO documents (content, title) VALUES (%s, %s)",
                (f"Batch content {i}", f"Batch Doc {i}")
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        config = DatabaseConnectorConfig(
            connection_string=postgres_container["connection_string"],
            db_type="postgresql",
            query="SELECT id, content, title FROM documents",
            content_column="content",
            id_column="id",
            batch_size=20,  # Small batches
        )
        
        async with DatabaseConnector(config) as connector:
            docs = [doc async for doc in connector.stream_documents()]
            
            # 3 original + 100 new
            assert len(docs) >= 100


# ============================================================================
# Local Filesystem Integration Tests
# ============================================================================


class TestFilesystemConnectorLocal:
    """Integration tests for local filesystem connector."""

    @pytest.fixture
    def test_directory(self):
        """Create a temporary directory with test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            
            # Create directory structure
            (base / "docs").mkdir()
            (base / "docs" / "subdir").mkdir()
            (base / "images").mkdir()
            
            # Create test files
            (base / "docs" / "readme.txt").write_text("README content")
            (base / "docs" / "manual.pdf").write_bytes(b"%PDF-1.4 fake pdf")
            (base / "docs" / "subdir" / "nested.txt").write_text("Nested content")
            (base / "images" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            
            yield tmpdir

    @pytest.mark.asyncio
    async def test_connect_local(self, test_directory):
        """Test connecting to local filesystem."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
        )
        
        async with FilesystemConnector(config) as connector:
            assert connector._connected is True

    @pytest.mark.asyncio
    async def test_list_all_files(self, test_directory):
        """Test listing all files recursively."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
            recursive=True,
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]
            
            assert len(docs) == 4
            filenames = {doc.filename for doc in docs}
            assert "readme.txt" in filenames
            assert "nested.txt" in filenames

    @pytest.mark.asyncio
    async def test_list_with_extension_filter(self, test_directory):
        """Test listing with file extension filter."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
            file_extensions=[".txt"],
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]
            
            assert len(docs) == 2  # Only .txt files
            for doc in docs:
                assert doc.filename.endswith(".txt")

    @pytest.mark.asyncio
    async def test_fetch_document_local(self, test_directory):
        """Test fetching a single local file."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
        )
        
        async with FilesystemConnector(config) as connector:
            doc = await connector.fetch_document("docs/readme.txt")
            
            assert doc.content == b"README content"
            assert doc.metadata.filename == "readme.txt"

    @pytest.mark.asyncio
    async def test_stream_documents_local(self, test_directory):
        """Test streaming all local documents."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.stream_documents()]
            
            assert len(docs) == 4
            
            # Check that content is loaded
            contents = {doc.content for doc in docs}
            assert b"README content" in contents

    @pytest.mark.asyncio
    async def test_subdirectory_listing(self, test_directory):
        """Test listing a subdirectory."""
        config = FilesystemConnectorConfig(
            base_path=test_directory,
            storage_type="local",
        )
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents("docs")]
            
            assert len(docs) == 3  # Files in docs/ and docs/subdir/


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Performance tests for connectors."""

    @pytest.fixture
    def large_test_directory(self):
        """Create a directory with many files for performance testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            
            # Create 1000+ files
            for i in range(1100):
                subdir = base / f"dir_{i // 100}"
                subdir.mkdir(exist_ok=True)
                (subdir / f"file_{i}.txt").write_text(f"Content of file {i}")
            
            yield tmpdir

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_list_1000_files_performance(self, large_test_directory):
        """Test listing 1000+ files completes in reasonable time."""
        import time
        
        config = FilesystemConnectorConfig(
            base_path=large_test_directory,
            storage_type="local",
        )
        
        start_time = time.time()
        
        async with FilesystemConnector(config) as connector:
            docs = [doc async for doc in connector.list_documents()]
        
        elapsed = time.time() - start_time
        
        assert len(docs) >= 1000
        assert elapsed < 30  # Should complete within 30 seconds

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_stream_1000_files_performance(self, large_test_directory):
        """Test streaming 1000+ files completes in reasonable time."""
        import time
        
        config = FilesystemConnectorConfig(
            base_path=large_test_directory,
            storage_type="local",
        )
        
        start_time = time.time()
        count = 0
        
        async with FilesystemConnector(config) as connector:
            async for doc in connector.stream_documents():
                count += 1
                # Simulate some processing
                _ = len(doc.content)
        
        elapsed = time.time() - start_time
        
        assert count >= 1000
        assert elapsed < 60  # Should complete within 60 seconds


# ============================================================================
# Conftest for Integration Tests
# ============================================================================


def pytest_configure(config):
    """Add custom markers for integration tests."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
