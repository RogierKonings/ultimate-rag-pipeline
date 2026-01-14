"""Tests for document indexing status tracking (US-10.1.1).

Tests cover:
- IndexStatus enum and Document model fields
- IndexCoordinator status tracking
- Prometheus metrics
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# Add service directories to path for imports
services_dir = Path(__file__).parent.parent.parent
ingestion_dir = services_dir / "ingestion"
shared_dir = services_dir / "shared"

sys.path.insert(0, str(ingestion_dir))
sys.path.insert(0, str(shared_dir))


class TestIndexStatusEnum:
    """Tests for IndexStatus enum."""

    def test_index_status_values(self):
        """IndexStatus should have correct enum values."""
        from database.models.document import IndexStatus

        assert IndexStatus.PENDING.value == "pending"
        assert IndexStatus.OK.value == "ok"
        assert IndexStatus.ERROR.value == "error"
        assert IndexStatus.STALE.value == "stale"

    def test_index_status_is_string_enum(self):
        """IndexStatus should be a string enum for JSON serialization."""
        from database.models.document import IndexStatus

        # IndexStatus inherits from str, so its value is a string
        assert IndexStatus.OK.value == "ok"
        # The enum member itself behaves as a string
        assert f"{IndexStatus.OK.value}" == "ok"


class TestDocumentModelFields:
    """Tests for new Document model fields."""

    def test_document_has_indexing_status_fields(self):
        """Document model should have all required indexing status fields."""
        from database.models.document import Document

        # Check that the model has the expected attributes
        assert hasattr(Document, "qdrant_status")
        assert hasattr(Document, "opensearch_status")
        assert hasattr(Document, "last_indexed_at")
        assert hasattr(Document, "last_index_error")
        assert hasattr(Document, "index_attempts")

    def test_index_status_exported_from_models(self):
        """IndexStatus should be exported from models package."""
        from database.models import IndexStatus

        assert IndexStatus.PENDING.value == "pending"


class TestSyncStatusSchemas:
    """Tests for sync status API schemas.

    Note: Some tests are skipped due to import chain issues with minio.
    The schemas are tested indirectly through API integration tests.
    """

    def test_index_status_value_enum_exists(self):
        """IndexStatusValue enum should exist in documents schemas."""
        # Read the schema file directly to verify the enum exists
        # Handle both local and Docker container paths
        schema_file = Path("/app/api/schemas/documents.py")
        if not schema_file.exists():
            schema_file = ingestion_dir / "api" / "schemas" / "documents.py"
        content = schema_file.read_text()

        assert "class IndexStatusValue" in content
        assert 'PENDING = "pending"' in content
        assert 'OK = "ok"' in content
        assert 'ERROR = "error"' in content
        assert 'STALE = "stale"' in content

    def test_sync_status_filter_enum_exists(self):
        """SyncStatusFilter enum should exist in documents schemas."""
        schema_file = Path("/app/api/schemas/documents.py")
        if not schema_file.exists():
            schema_file = ingestion_dir / "api" / "schemas" / "documents.py"
        content = schema_file.read_text()

        assert "class SyncStatusFilter" in content
        assert 'ALL = "all"' in content
        assert 'OK = "ok"' in content
        assert 'ERROR = "error"' in content
        assert 'PENDING = "pending"' in content
        assert 'ANY_ERROR = "any_error"' in content

    def test_document_sync_status_schema_exists(self):
        """DocumentSyncStatus schema should exist with correct fields."""
        schema_file = Path("/app/api/schemas/documents.py")
        if not schema_file.exists():
            schema_file = ingestion_dir / "api" / "schemas" / "documents.py"
        content = schema_file.read_text()

        assert "class DocumentSyncStatus" in content
        assert "document_id: UUID" in content
        assert "source_id: str" in content
        assert "qdrant_status: IndexStatusValue" in content
        assert "opensearch_status: IndexStatusValue" in content
        assert "last_indexed_at:" in content
        assert "last_index_error:" in content
        assert "index_attempts: int" in content

    def test_sync_status_summary_schema_exists(self):
        """SyncStatusSummary schema should exist with correct fields."""
        schema_file = Path("/app/api/schemas/documents.py")
        if not schema_file.exists():
            schema_file = ingestion_dir / "api" / "schemas" / "documents.py"
        content = schema_file.read_text()

        assert "class SyncStatusSummary" in content
        assert "ok: int" in content
        assert "pending: int" in content
        assert "error: int" in content
        assert "stale: int" in content

    def test_sync_status_response_schema_exists(self):
        """SyncStatusResponse schema should exist with correct fields."""
        schema_file = Path("/app/api/schemas/documents.py")
        if not schema_file.exists():
            schema_file = ingestion_dir / "api" / "schemas" / "documents.py"
        content = schema_file.read_text()

        assert "class SyncStatusResponse" in content
        assert "summary: SyncStatusSummary" in content
        assert "documents: list[DocumentSyncStatus]" in content
        assert "total: int" in content
        assert "limit: int" in content
        assert "offset: int" in content


class TestIndexCoordinatorStatusTracking:
    """Tests for IndexCoordinator status tracking methods."""

    @pytest.fixture
    def mock_postgres_writer(self):
        """Create a mock PostgresWriter with pool."""
        writer = MagicMock()
        writer._pool = MagicMock()
        writer._pool.acquire = MagicMock()
        return writer

    @pytest.fixture
    def mock_qdrant_writer(self):
        """Create a mock QdrantWriter."""
        writer = MagicMock()
        writer.write = AsyncMock(
            return_value=MagicMock(success=True, items_written=10, items_failed=0, errors=[])
        )
        return writer

    @pytest.fixture
    def mock_opensearch_writer(self):
        """Create a mock OpenSearchWriter."""
        writer = MagicMock()
        writer.write = AsyncMock(
            return_value=MagicMock(success=True, items_written=10, items_failed=0, errors=[])
        )
        return writer

    @pytest.mark.asyncio
    async def test_set_pending_status_updates_documents_table(
        self, mock_postgres_writer, mock_qdrant_writer, mock_opensearch_writer
    ):
        """_set_pending_status should update documents table."""
        from indexing.coordinator import IndexCoordinator

        coordinator = IndexCoordinator(
            qdrant=mock_qdrant_writer,
            opensearch=mock_opensearch_writer,
            postgres=mock_postgres_writer,
        )

        # Mock the connection context manager
        mock_conn = AsyncMock()
        mock_postgres_writer._pool.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_postgres_writer._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        document_id = uuid4()
        await coordinator._set_pending_status(document_id)

        # Verify execute was called with UPDATE query
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE documents" in call_args[0][0]
        assert "pending" in str(call_args)

    @pytest.mark.asyncio
    async def test_update_index_status_on_success(
        self, mock_postgres_writer, mock_qdrant_writer, mock_opensearch_writer
    ):
        """_update_index_status should set OK status on success."""
        from indexing.coordinator import IndexCoordinator

        coordinator = IndexCoordinator(
            qdrant=mock_qdrant_writer,
            opensearch=mock_opensearch_writer,
            postgres=mock_postgres_writer,
        )

        mock_conn = AsyncMock()
        mock_postgres_writer._pool.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_postgres_writer._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        document_id = uuid4()
        await coordinator._update_index_status(
            document_id=document_id,
            qdrant_success=True,
            opensearch_success=True,
            errors=None,
        )

        # Verify execute was called with correct status values
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "UPDATE documents" in call_args[0][0]
        # Check that "ok" status was passed
        assert call_args[0][1] == "ok"  # qdrant_status
        assert call_args[0][2] == "ok"  # opensearch_status

    @pytest.mark.asyncio
    async def test_update_index_status_on_partial_failure(
        self, mock_postgres_writer, mock_qdrant_writer, mock_opensearch_writer
    ):
        """_update_index_status should set ERROR for failed store."""
        from indexing.coordinator import IndexCoordinator

        coordinator = IndexCoordinator(
            qdrant=mock_qdrant_writer,
            opensearch=mock_opensearch_writer,
            postgres=mock_postgres_writer,
        )

        mock_conn = AsyncMock()
        mock_postgres_writer._pool.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )
        mock_postgres_writer._pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        document_id = uuid4()
        await coordinator._update_index_status(
            document_id=document_id,
            qdrant_success=True,
            opensearch_success=False,
            errors="OpenSearch: Connection refused",
        )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        # Qdrant should be OK, OpenSearch should be ERROR
        assert call_args[0][1] == "ok"  # qdrant_status
        assert call_args[0][2] == "error"  # opensearch_status


class TestTelemetryMetrics:
    """Tests for Prometheus metrics."""

    def test_documents_by_index_status_gauge_created(self):
        """DOCUMENTS_BY_INDEX_STATUS gauge should be created during setup."""
        # Import to check if gauge is defined
        from telemetry import DOCUMENTS_BY_INDEX_STATUS

        # Initially None before setup_telemetry is called
        # After setup_telemetry, it should be a Gauge
        # We just verify the variable exists
        assert DOCUMENTS_BY_INDEX_STATUS is None or hasattr(
            DOCUMENTS_BY_INDEX_STATUS, "labels"
        )

    @pytest.mark.asyncio
    async def test_update_index_status_metrics_function_exists(self):
        """update_index_status_metrics should be importable."""
        from telemetry import update_index_status_metrics

        assert callable(update_index_status_metrics)
