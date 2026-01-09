"""Tests for OpenSearchWriter."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from ..opensearch import OpenSearchWriter, OpenSearchWriterConfig
from ..models import IndexedChunk


class TestOpenSearchWriterConfig:
    """Tests for OpenSearchWriterConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OpenSearchWriterConfig()
        assert config.hosts == ["http://localhost:9200"]
        assert config.username is None
        assert config.password is None
        assert config.index_name == "documents"
        assert config.number_of_shards == 1
        assert config.number_of_replicas == 1
        assert config.batch_size == 500
        assert config.timeout == 30

    def test_custom_config(self):
        """Test custom configuration values."""
        config = OpenSearchWriterConfig(
            hosts=["http://opensearch:9200"],
            username="admin",
            password="password",
            index_name="custom_index",
            batch_size=100,
        )
        assert config.hosts == ["http://opensearch:9200"]
        assert config.username == "admin"
        assert config.password == "password"
        assert config.index_name == "custom_index"
        assert config.batch_size == 100


class TestOpenSearchWriter:
    """Tests for OpenSearchWriter."""

    @pytest.fixture
    def writer(self):
        """Create an OpenSearchWriter instance."""
        return OpenSearchWriter(OpenSearchWriterConfig())

    @pytest.fixture
    def mock_client(self):
        """Create a mock AsyncOpenSearch client."""
        client = AsyncMock()
        client.indices = AsyncMock()
        client.indices.exists = AsyncMock(return_value=False)
        client.indices.create = AsyncMock()
        client.bulk = AsyncMock(return_value={"errors": False, "items": []})
        client.delete_by_query = AsyncMock()
        client.close = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_connect_creates_client(self, writer):
        """Test that connect() creates a client."""
        with patch("opensearchpy.AsyncOpenSearch") as mock_class:
            mock_instance = AsyncMock()
            mock_class.return_value = mock_instance

            await writer.connect()

            mock_class.assert_called_once()
            assert writer._client is not None

    @pytest.mark.asyncio
    async def test_connect_with_auth(self):
        """Test that connect() uses auth credentials when provided."""
        config = OpenSearchWriterConfig(
            username="admin",
            password="password",
        )
        writer = OpenSearchWriter(config)

        with patch("opensearchpy.AsyncOpenSearch") as mock_class:
            mock_instance = AsyncMock()
            mock_class.return_value = mock_instance

            await writer.connect()

            call_kwargs = mock_class.call_args.kwargs
            assert call_kwargs["http_auth"] == ("admin", "password")

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self, writer, mock_client):
        """Test that disconnect() closes the client."""
        writer._client = mock_client

        await writer.disconnect()

        mock_client.close.assert_called_once()
        assert writer._client is None

    @pytest.mark.asyncio
    async def test_ensure_index_creates_index(self, writer, mock_client):
        """Test that ensure_index() creates index when it doesn't exist."""
        writer._client = mock_client
        mock_client.indices.exists.return_value = False

        await writer.ensure_index()

        mock_client.indices.create.assert_called_once()
        call_kwargs = mock_client.indices.create.call_args.kwargs
        assert call_kwargs["index"] == "documents"
        assert "mappings" in call_kwargs["body"]

    @pytest.mark.asyncio
    async def test_ensure_index_skips_existing(self, writer, mock_client):
        """Test that ensure_index() skips creation for existing index."""
        writer._client = mock_client
        mock_client.indices.exists.return_value = True

        await writer.ensure_index()

        mock_client.indices.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_uses_bulk_api(self, writer, mock_client, sample_chunk):
        """Test that write() uses bulk API."""
        writer._client = mock_client
        mock_client.bulk.return_value = {
            "errors": False,
            "items": [{"index": {"result": "created"}}],
        }

        result = await writer.write([sample_chunk])

        assert result.success
        assert result.items_written == 1
        mock_client.bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_batches_large_lists(self, writer, mock_client):
        """Test that write() batches large chunk lists."""
        writer._client = mock_client
        writer.config.batch_size = 5
        mock_client.bulk.return_value = {"errors": False, "items": []}

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
        # 12 chunks, batch_size=5 -> 3 batches
        assert mock_client.bulk.call_count == 3

    @pytest.mark.asyncio
    async def test_write_handles_bulk_errors(self, writer, mock_client, sample_chunk):
        """Test that write() handles bulk API errors."""
        writer._client = mock_client
        mock_client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"error": {"type": "mapper_parsing_exception", "reason": "failed"}}}
            ],
        }

        result = await writer.write([sample_chunk])

        assert not result.success
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_delete_uses_bulk_delete(self, writer, mock_client):
        """Test that delete() uses bulk delete API."""
        writer._client = mock_client
        mock_client.bulk.return_value = {"errors": False, "items": []}
        chunk_ids = [uuid4(), uuid4()]

        result = await writer.delete(chunk_ids)

        assert result.success
        mock_client.bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_by_document(self, writer, mock_client):
        """Test that delete_by_document() uses delete_by_query."""
        writer._client = mock_client
        document_id = uuid4()

        result = await writer.delete_by_document(document_id)

        assert result.success
        mock_client.delete_by_query.assert_called_once()

        # Verify query structure
        call_kwargs = mock_client.delete_by_query.call_args.kwargs
        assert call_kwargs["body"]["query"]["term"]["document_id"] == str(document_id)

    @pytest.mark.asyncio
    async def test_write_raises_without_connection(self, writer, sample_chunk):
        """Test that write() raises error without connection."""
        with pytest.raises(RuntimeError, match="Client not connected"):
            await writer.write([sample_chunk])

    @pytest.mark.asyncio
    async def test_context_manager(self, writer):
        """Test async context manager protocol."""
        with patch("opensearchpy.AsyncOpenSearch") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.close = AsyncMock()
            mock_class.return_value = mock_instance

            async with writer:
                assert writer._client is not None

            mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_includes_metadata(self, writer, mock_client):
        """Test that write() includes metadata in documents."""
        writer._client = mock_client
        mock_client.bulk.return_value = {"errors": False, "items": []}

        chunk = IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content="Test content",
            embedding=[0.1] * 1024,
            chunk_index=0,
            token_count=10,
            tenant_id="tenant-1",
            metadata={"custom_field": "custom_value"},
        )

        await writer.write([chunk])

        # Verify bulk was called with correct document
        call_args = mock_client.bulk.call_args
        body = call_args.kwargs["body"]
        # Body alternates between action and document
        doc = body[1]
        assert doc["custom_field"] == "custom_value"
