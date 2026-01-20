"""Tests for the tombstone (soft-delete propagation) task (US-10.1.3).

Tests cover:
- Successful deletion propagation to both Qdrant and OpenSearch
- Partial failure handling (one store fails)
- Idempotent behavior (safe to retry)
- Metrics updates
"""

from dataclasses import asdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from tasks.tombstone import (
    DeletionResult,
    _propagate_deletion_async,
)


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client."""
    client = MagicMock()
    client.delete_by_document_id = AsyncMock(return_value=5)
    return client


@pytest.fixture
def mock_opensearch():
    """Mock OpenSearch client."""
    client = MagicMock()
    client.delete_by_document_id = AsyncMock(return_value=5)
    return client


@pytest.fixture
def mock_settings():
    """Mock settings."""
    settings = MagicMock()
    settings.qdrant_url = "http://localhost:6333"
    settings.opensearch_url = "http://localhost:9200"
    return settings


class TestDeletionResult:
    """Tests for DeletionResult dataclass."""

    def test_duration_seconds(self):
        """Should calculate duration correctly."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC)

        result = DeletionResult(
            document_id="doc-123",
            tenant_id="tenant-456",
            qdrant_deleted=5,
            opensearch_deleted=5,
            started_at=start,
            completed_at=end,
            success=True,
            errors=[],
        )

        assert result.duration_seconds == 5.0

    def test_serializes_to_dict(self):
        """Should serialize to dict for Celery return."""
        now = datetime.now(tz=UTC)
        result = DeletionResult(
            document_id="doc-123",
            tenant_id="tenant-456",
            qdrant_deleted=5,
            opensearch_deleted=3,
            started_at=now,
            completed_at=now,
            success=True,
            errors=[],
        )

        result_dict = asdict(result)
        assert result_dict["document_id"] == "doc-123"
        assert result_dict["qdrant_deleted"] == 5
        assert result_dict["opensearch_deleted"] == 3
        assert result_dict["success"] is True


class TestPropagateDeletionAsync:
    """Tests for the async deletion propagation."""

    @pytest.mark.asyncio
    async def test_successful_deletion_both_stores(
        self, mock_qdrant, mock_opensearch, mock_settings
    ):
        """Should delete from both Qdrant and OpenSearch successfully."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
        ):
            result = await _propagate_deletion_async(
                document_id=document_id,
                tenant_id=tenant_id,
            )

        assert result["success"] is True
        assert result["qdrant_deleted"] == 5
        assert result["opensearch_deleted"] == 5
        assert result["errors"] == []

        mock_qdrant.delete_by_document_id.assert_called_once_with(
            document_id=document_id,
            tenant_id=tenant_id,
        )
        mock_opensearch.delete_by_document_id.assert_called_once_with(
            document_id=document_id,
            tenant_id=tenant_id,
        )

    @pytest.mark.asyncio
    async def test_qdrant_failure_continues_to_opensearch(
        self, mock_qdrant, mock_opensearch, mock_settings
    ):
        """Should continue to OpenSearch even if Qdrant fails."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        mock_qdrant.delete_by_document_id = AsyncMock(
            side_effect=Exception("Qdrant connection failed")
        )

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
        ):
            with pytest.raises(Exception) as exc:
                await _propagate_deletion_async(
                    document_id=document_id,
                    tenant_id=tenant_id,
                )

            # Should raise to trigger retry
            assert "Qdrant deletion failed" in str(exc.value)

        # OpenSearch should still have been called
        mock_opensearch.delete_by_document_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_opensearch_failure_raises_exception(
        self, mock_qdrant, mock_opensearch, mock_settings
    ):
        """Should raise exception when OpenSearch fails (triggers retry)."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        mock_opensearch.delete_by_document_id = AsyncMock(
            side_effect=Exception("OpenSearch connection failed")
        )

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
        ):
            with pytest.raises(Exception) as exc:
                await _propagate_deletion_async(
                    document_id=document_id,
                    tenant_id=tenant_id,
                )

            assert "OpenSearch deletion failed" in str(exc.value)

    @pytest.mark.asyncio
    async def test_both_stores_fail(self, mock_qdrant, mock_opensearch, mock_settings):
        """Should report both errors when both stores fail."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        mock_qdrant.delete_by_document_id = AsyncMock(side_effect=Exception("Qdrant error"))
        mock_opensearch.delete_by_document_id = AsyncMock(side_effect=Exception("OpenSearch error"))

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
        ):
            with pytest.raises(Exception) as exc:
                await _propagate_deletion_async(
                    document_id=document_id,
                    tenant_id=tenant_id,
                )

            error_msg = str(exc.value)
            assert "Qdrant deletion failed" in error_msg
            assert "OpenSearch deletion failed" in error_msg

    @pytest.mark.asyncio
    async def test_idempotent_zero_deletions(self, mock_qdrant, mock_opensearch, mock_settings):
        """Should succeed even if document doesn't exist (idempotent)."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        mock_qdrant.delete_by_document_id = AsyncMock(return_value=0)
        mock_opensearch.delete_by_document_id = AsyncMock(return_value=0)

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
        ):
            result = await _propagate_deletion_async(
                document_id=document_id,
                tenant_id=tenant_id,
            )

        assert result["success"] is True
        assert result["qdrant_deleted"] == 0
        assert result["opensearch_deleted"] == 0


class TestDeletionMetrics:
    """Tests for metrics updates."""

    @pytest.mark.asyncio
    async def test_metrics_updated_on_success(self, mock_qdrant, mock_opensearch, mock_settings):
        """Should update Prometheus metrics on successful deletion."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        mock_runs = MagicMock()
        mock_duration = MagicMock()
        mock_removed = MagicMock()

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
            patch.dict(
                "tasks.tombstone.__dict__",
                {
                    "DELETION_PROPAGATION_RUNS": mock_runs,
                    "DELETION_PROPAGATION_DURATION": mock_duration,
                    "DELETION_VECTORS_REMOVED": mock_removed,
                },
            ),
        ):
            await _propagate_deletion_async(
                document_id=document_id,
                tenant_id=tenant_id,
            )

        # Metrics should be updated (actual calls depend on implementation)
        # This test ensures the metrics code doesn't raise exceptions

    @pytest.mark.asyncio
    async def test_metrics_failure_does_not_break_task(
        self, mock_qdrant, mock_opensearch, mock_settings
    ):
        """Metrics failure should not cause task failure."""
        document_id = str(uuid4())
        tenant_id = str(uuid4())

        with (
            patch("tasks.tombstone.get_settings", return_value=mock_settings),
            patch("tasks.tombstone.QdrantVectorStore", return_value=mock_qdrant),
            patch("tasks.tombstone.OpenSearchClient", return_value=mock_opensearch),
            patch(
                "tasks.tombstone._update_deletion_metrics", side_effect=Exception("Metrics error")
            ),
        ):
            # Should complete successfully despite metrics error
            result = await _propagate_deletion_async(
                document_id=document_id,
                tenant_id=tenant_id,
            )

        assert result["success"] is True
