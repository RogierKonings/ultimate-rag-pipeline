"""Tests for QdrantWriter."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from .. import qdrant as qdrant_module
from ..models import IndexedChunk
from ..qdrant import QdrantWriter, QdrantWriterConfig


class TestQdrantWriterConfig:
    """Tests for QdrantWriterConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = QdrantWriterConfig()
        assert config.url == "http://localhost:6333"
        assert config.api_key is None
        assert config.collection_name == "documents"
        assert config.vector_size == 1024
        assert config.distance == "Cosine"
        assert config.hnsw_m == 16
        assert config.hnsw_ef_construct == 100
        assert config.batch_size == 100
        assert config.timeout == 60.0

    def test_custom_config(self):
        """Test custom configuration values."""
        config = QdrantWriterConfig(
            url="http://qdrant:6333",
            api_key="test-api-key",
            collection_name="custom_collection",
            vector_size=512,
            batch_size=50,
        )
        assert config.url == "http://qdrant:6333"
        assert config.api_key == "test-api-key"
        assert config.collection_name == "custom_collection"
        assert config.vector_size == 512
        assert config.batch_size == 50


class TestQdrantWriter:
    """Tests for QdrantWriter."""

    @pytest.fixture
    def writer(self):
        """Create a QdrantWriter instance."""
        return QdrantWriter(QdrantWriterConfig())

    @pytest.fixture
    def mock_client(self):
        """Create a mock AsyncQdrantClient."""
        client = AsyncMock()
        client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
        client.create_collection = AsyncMock()
        client.create_payload_index = AsyncMock()
        client.upsert = AsyncMock()
        client.delete = AsyncMock()
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_connect_creates_client(self, writer):
        """Test that connect() creates a client."""
        with patch.object(qdrant_module, "AsyncQdrantClient") as mock_class:
            mock_instance = AsyncMock()
            mock_class.return_value = mock_instance

            await writer.connect()

            mock_class.assert_called_once()
            assert writer._client is not None

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self, writer, mock_client):
        """Test that disconnect() closes the client."""
        writer._client = mock_client

        await writer.disconnect()

        mock_client.close.assert_called_once()
        assert writer._client is None

    @pytest.mark.asyncio
    async def test_ensure_index_creates_collection(self, writer, mock_client):
        """Test that ensure_index() creates collection when it doesn't exist."""
        writer._client = mock_client
        mock_client.get_collections.return_value = MagicMock(collections=[])

        await writer.ensure_index()

        mock_client.create_collection.assert_called_once()
        # Should create 7 payload indices (document_id, tenant_id, visibility,
        # allowed_groups, allowed_users, source_type, status)
        assert mock_client.create_payload_index.call_count == 7

    @pytest.mark.asyncio
    async def test_ensure_index_skips_existing_collection(self, writer, mock_client):
        """Test that ensure_index() skips creation for existing collection."""
        writer._client = mock_client
        existing_collection = MagicMock()
        existing_collection.name = "documents"
        mock_client.get_collections.return_value = MagicMock(
            collections=[existing_collection],
        )

        await writer.ensure_index()

        mock_client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_upserts_chunks(self, writer, mock_client, sample_chunk):
        """Test that write() upserts chunks to Qdrant."""
        writer._client = mock_client

        result = await writer.write([sample_chunk])

        assert result.success
        assert result.items_written == 1
        assert result.items_failed == 0
        mock_client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_batches_large_lists(self, writer, mock_client):
        """Test that write() batches large chunk lists."""
        writer._client = mock_client
        writer.config.batch_size = 5

        # Create 12 chunks (should result in 3 batches: 5, 5, 2)
        chunks = [
            IndexedChunk(
                chunk_id=uuid4(),
                document_id=uuid4(),
                content=f"Content {i}",
                embedding=[0.1] * 1024,
                chunk_index=i,
                token_count=10,
                tenant_id="tenant-1",
            )
            for i in range(12)
        ]

        result = await writer.write(chunks)

        assert result.success
        assert result.items_written == 12
        assert mock_client.upsert.call_count == 3

    @pytest.mark.asyncio
    async def test_write_handles_errors(self, writer, mock_client, sample_chunk):
        """Test that write() handles errors gracefully."""
        writer._client = mock_client
        mock_client.upsert.side_effect = Exception("Connection error")

        result = await writer.write([sample_chunk])

        assert not result.success
        assert result.items_failed == 1
        assert len(result.errors) == 1
        assert "Connection error" in result.errors[0]

    @pytest.mark.asyncio
    async def test_delete_removes_chunks(self, writer, mock_client):
        """Test that delete() removes chunks by ID."""
        writer._client = mock_client
        chunk_ids = [uuid4(), uuid4()]

        result = await writer.delete(chunk_ids)

        assert result.success
        mock_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_by_document(self, writer, mock_client):
        """Test that delete_by_document() removes all chunks for a document."""
        writer._client = mock_client
        document_id = uuid4()

        result = await writer.delete_by_document(document_id)

        assert result.success
        mock_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_raises_without_connection(self, writer, sample_chunk):
        """Test that write() raises error without connection."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await writer.write([sample_chunk])

    @pytest.mark.asyncio
    async def test_context_manager(self, writer):
        """Test async context manager protocol."""
        with patch.object(qdrant_module, "AsyncQdrantClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.close = AsyncMock()
            mock_class.return_value = mock_instance

            async with writer:
                assert writer._client is not None

            mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_includes_optional_fields(self, writer, mock_client):
        """Test that write() includes optional fields in payload."""
        writer._client = mock_client

        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            embedding=[0.1] * 1024,
            chunk_index=0,
            token_count=10,
            tenant_id="tenant-1",
            parent_chunk_id=uuid4(),
            source_page=5,
            source_section="Introduction",
        )

        await writer.write([chunk])

        # Verify upsert was called with correct payload
        call_args = mock_client.upsert.call_args
        points = call_args.kwargs["points"]
        payload = points[0].payload

        assert "parent_chunk_id" in payload
        assert payload["source_page"] == 5
        assert payload["source_section"] == "Introduction"
