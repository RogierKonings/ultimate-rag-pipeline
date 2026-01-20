"""Tests for IndexCoordinator."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ..coordinator import IndexCoordinator
from ..models import DocumentRecord, IndexedChunk, WriteResult
from ..opensearch import OpenSearchWriter
from ..postgres import PostgresWriter
from ..qdrant import QdrantWriter


class TestIndexCoordinator:
    """Tests for IndexCoordinator."""

    @pytest.fixture
    def mock_qdrant(self):
        """Create a mock QdrantWriter."""
        writer = AsyncMock(spec=QdrantWriter)
        writer.connect = AsyncMock()
        writer.disconnect = AsyncMock()
        writer.ensure_index = AsyncMock()
        writer.write = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=1,
                items_failed=0,
                duration_ms=10,
            ),
        )
        writer.delete = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        writer.delete_by_document = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        return writer

    @pytest.fixture
    def mock_opensearch(self):
        """Create a mock OpenSearchWriter."""
        writer = AsyncMock(spec=OpenSearchWriter)
        writer.connect = AsyncMock()
        writer.disconnect = AsyncMock()
        writer.ensure_index = AsyncMock()
        writer.write = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=1,
                items_failed=0,
                duration_ms=10,
            ),
        )
        writer.delete = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        writer.delete_by_document = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        return writer

    @pytest.fixture
    def mock_postgres(self):
        """Create a mock PostgresWriter."""
        writer = AsyncMock(spec=PostgresWriter)
        writer.connect = AsyncMock()
        writer.disconnect = AsyncMock()
        writer.ensure_index = AsyncMock()
        writer.write = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=1,
                items_failed=0,
                duration_ms=10,
            ),
        )
        writer.delete = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        writer.delete_by_document = AsyncMock(
            return_value=WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=5,
            ),
        )
        writer.update_status = AsyncMock()
        # The coordinator accesses _pool directly to set pending status
        # Set to None so _set_pending_status returns early
        writer._pool = None
        return writer

    @pytest.fixture
    def coordinator(self, mock_qdrant, mock_opensearch, mock_postgres):
        """Create an IndexCoordinator with mock writers."""
        return IndexCoordinator(mock_qdrant, mock_opensearch, mock_postgres)

    @pytest.mark.asyncio
    async def test_ensure_indices(self, coordinator, mock_qdrant, mock_opensearch, mock_postgres):
        """Test that ensure_indices() calls all writers."""
        await coordinator.ensure_indices()

        mock_qdrant.ensure_index.assert_called_once()
        mock_opensearch.ensure_index.assert_called_once()
        mock_postgres.ensure_index.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_document_success(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
        sample_document,
        sample_chunk,
    ):
        """Test successful document indexing."""
        results = await coordinator.index_document(sample_document, [sample_chunk])

        assert results["qdrant"].success
        assert results["opensearch"].success
        assert results["postgres"].success

        # Coordinator passes collection_name/index_name kwargs
        mock_qdrant.write.assert_called_once()
        assert mock_qdrant.write.call_args[0][0] == [sample_chunk]
        mock_opensearch.write.assert_called_once()
        assert mock_opensearch.write.call_args[0][0] == [sample_chunk]
        mock_postgres.write.assert_called_once_with([sample_document])
        mock_postgres.update_status.assert_called_once_with(
            sample_document.document_id,
            "indexed",
            None,
        )

    @pytest.mark.asyncio
    async def test_index_document_partial_failure(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
        sample_document,
        sample_chunk,
    ):
        """Test document indexing with partial failure."""
        mock_qdrant.write.return_value = WriteResult(
            success=False,
            items_written=0,
            items_failed=1,
            errors=["Qdrant error"],
            duration_ms=10,
        )

        results = await coordinator.index_document(sample_document, [sample_chunk])

        assert not results["qdrant"].success
        assert results["opensearch"].success
        assert results["postgres"].success

        # Status should be failed
        mock_postgres.update_status.assert_called_once()
        call_args = mock_postgres.update_status.call_args
        assert call_args[0][1] == "failed"
        assert "qdrant" in call_args[0][2].lower()

    @pytest.mark.asyncio
    async def test_index_document_handles_exception(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
        sample_document,
        sample_chunk,
    ):
        """Test document indexing handles exceptions."""
        mock_opensearch.write.side_effect = Exception("Connection timeout")

        results = await coordinator.index_document(sample_document, [sample_chunk])

        assert results["qdrant"].success
        assert not results["opensearch"].success
        assert "Connection timeout" in results["opensearch"].errors[0]

    @pytest.mark.asyncio
    async def test_delete_document(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
    ):
        """Test document deletion."""
        document_id = uuid4()

        results = await coordinator.delete_document(document_id)

        assert results["qdrant"].success
        assert results["opensearch"].success
        assert results["postgres"].success

        # Coordinator passes collection_name/index_name kwargs
        mock_qdrant.delete_by_document.assert_called_once()
        assert mock_qdrant.delete_by_document.call_args[0][0] == document_id
        mock_opensearch.delete_by_document.assert_called_once()
        assert mock_opensearch.delete_by_document.call_args[0][0] == document_id
        mock_postgres.delete.assert_called_once_with([document_id])

    @pytest.mark.asyncio
    async def test_delete_document_partial_failure(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
    ):
        """Test document deletion with partial failure."""
        mock_postgres.delete.return_value = WriteResult(
            success=False,
            items_written=0,
            items_failed=1,
            errors=["Database error"],
            duration_ms=5,
        )

        results = await coordinator.delete_document(uuid4())

        assert results["qdrant"].success
        assert results["opensearch"].success
        assert not results["postgres"].success

    @pytest.mark.asyncio
    async def test_reindex_document(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
        sample_document,
        sample_chunk,
    ):
        """Test document reindexing."""
        results = await coordinator.reindex_document(sample_document, [sample_chunk])

        # Should delete first, then index (coordinator passes collection_name/index_name kwargs)
        mock_qdrant.delete_by_document.assert_called_once()
        assert mock_qdrant.delete_by_document.call_args[0][0] == sample_document.document_id
        mock_opensearch.delete_by_document.assert_called_once()
        assert mock_opensearch.delete_by_document.call_args[0][0] == sample_document.document_id

        mock_qdrant.write.assert_called_once()
        assert mock_qdrant.write.call_args[0][0] == [sample_chunk]
        mock_opensearch.write.assert_called_once()
        assert mock_opensearch.write.call_args[0][0] == [sample_chunk]
        mock_postgres.write.assert_called_once_with([sample_document])

        assert results["qdrant"].success
        assert results["opensearch"].success
        assert results["postgres"].success

    @pytest.mark.asyncio
    async def test_connect_all(self, coordinator, mock_qdrant, mock_opensearch, mock_postgres):
        """Test connecting to all stores."""
        await coordinator.connect_all()

        mock_qdrant.connect.assert_called_once()
        mock_opensearch.connect.assert_called_once()
        mock_postgres.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all(self, coordinator, mock_qdrant, mock_opensearch, mock_postgres):
        """Test disconnecting from all stores."""
        await coordinator.disconnect_all()

        mock_qdrant.disconnect.assert_called_once()
        mock_opensearch.disconnect.assert_called_once()
        mock_postgres.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, coordinator, mock_qdrant, mock_opensearch, mock_postgres):
        """Test async context manager protocol."""
        async with coordinator:
            mock_qdrant.connect.assert_called_once()
            mock_opensearch.connect.assert_called_once()
            mock_postgres.connect.assert_called_once()

        mock_qdrant.disconnect.assert_called_once()
        mock_opensearch.disconnect.assert_called_once()
        mock_postgres.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_document_with_multiple_chunks(
        self,
        coordinator,
        mock_qdrant,
        mock_opensearch,
        mock_postgres,
    ):
        """Test indexing document with multiple chunks."""
        document_id = uuid4()
        document = DocumentRecord(
            document_id=document_id,
            source_uri="s3://bucket/test-source",
            source_type="filesystem",
            tenant_id="tenant-1",
            chunk_count=5,
            total_tokens=50,
        )

        chunks = [
            IndexedChunk(
                chunk_id=uuid4(),
                document_id=document_id,
                content=f"Content {i}",
                embedding=[0.1] * 1024,
                chunk_index=i,
                token_count=10,
                tenant_id="tenant-1",
            )
            for i in range(5)
        ]

        mock_qdrant.write.return_value = WriteResult(
            success=True,
            items_written=5,
            items_failed=0,
            duration_ms=50,
        )
        mock_opensearch.write.return_value = WriteResult(
            success=True,
            items_written=5,
            items_failed=0,
            duration_ms=30,
        )

        results = await coordinator.index_document(document, chunks)

        assert results["qdrant"].items_written == 5
        assert results["opensearch"].items_written == 5
        assert results["postgres"].items_written == 1

        mock_postgres.update_status.assert_called_once_with(
            document_id,
            "indexed",
            None,
        )
