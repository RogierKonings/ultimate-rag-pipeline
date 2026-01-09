"""Tests for job status tracking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from ..status import JobStatusTracker
from ..models import JobStatus

# Module path for patching
STATUS_MODULE = "services.ingestion.tasks.status"


class TestJobStatusTracker:
    """Tests for JobStatusTracker class."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, mock_async_redis):
        """Test connection management."""
        tracker = JobStatusTracker(redis_url="redis://localhost:6379/0")

        with patch(f"{STATUS_MODULE}.redis.from_url", return_value=mock_async_redis):
            await tracker.connect()
            assert tracker._redis is not None

            await tracker.disconnect()
            mock_async_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_async_redis):
        """Test async context manager."""
        with patch(f"{STATUS_MODULE}.redis.from_url", return_value=mock_async_redis):
            async with JobStatusTracker() as tracker:
                assert tracker._redis is not None

            mock_async_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_status_pending(self):
        """Test getting status of pending job."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.AsyncResult") as mock_result:
            mock_result.return_value.status = "PENDING"
            mock_result.return_value.info = None

            status = await tracker.get_job_status("test-job-id")

            assert status.job_id == "test-job-id"
            assert status.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_job_status_progress(self):
        """Test getting status of in-progress job."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.AsyncResult") as mock_result:
            mock_result.return_value.status = "PROGRESS"
            mock_result.return_value.info = {
                "stage": "embedding",
                "processed": 50,
                "total": 100,
                "message": "Processing chunks...",
            }

            status = await tracker.get_job_status("test-job-id")

            assert status.job_id == "test-job-id"
            assert status.status == JobStatus.PROGRESS
            assert status.progress is not None
            assert status.progress.current == 50
            assert status.progress.total == 100
            assert status.progress.stage == "embedding"

    @pytest.mark.asyncio
    async def test_get_job_status_success(self):
        """Test getting status of successful job."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.AsyncResult") as mock_result:
            mock_result.return_value.status = "SUCCESS"
            mock_result.return_value.info = {
                "documents_processed": 10,
                "chunks_created": 100,
                "duration_seconds": 45.5,
            }

            status = await tracker.get_job_status("test-job-id")

            assert status.status == JobStatus.SUCCESS
            assert status.documents_processed == 10
            assert status.chunks_created == 100

    @pytest.mark.asyncio
    async def test_get_job_status_failure(self):
        """Test getting status of failed job."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.AsyncResult") as mock_result:
            mock_result.return_value.status = "FAILURE"
            mock_result.return_value.info = {
                "error": "Connection failed",
                "traceback": "Traceback...",
            }

            status = await tracker.get_job_status("test-job-id")

            assert status.status == JobStatus.FAILURE
            assert status.error_message == "Connection failed"

    @pytest.mark.asyncio
    async def test_cancel_job(self):
        """Test cancelling a job."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.AsyncResult") as mock_result:
            mock_async_result = MagicMock()
            mock_async_result.revoke = MagicMock()
            mock_result.return_value = mock_async_result

            result = await tracker.cancel_job("test-job-id")

            assert result is True
            mock_async_result.revoke.assert_called_once_with(terminate=True)

    @pytest.mark.asyncio
    async def test_list_active_jobs(self):
        """Test listing active jobs."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.celery_app") as mock_app:
            mock_inspect = MagicMock()
            mock_inspect.active.return_value = {
                "worker1": [{"id": "job-1"}, {"id": "job-2"}],
                "worker2": [{"id": "job-3"}],
            }
            mock_app.control.inspect.return_value = mock_inspect

            jobs = await tracker.list_active_jobs()

            assert len(jobs) == 3
            assert "job-1" in jobs
            assert "job-2" in jobs
            assert "job-3" in jobs

    @pytest.mark.asyncio
    async def test_list_dlq_entries(self, mock_async_redis):
        """Test listing DLQ entries."""
        import json

        mock_async_redis.scan.return_value = (0, ["dlq:task1:2024-01-01"])
        mock_async_redis.get.return_value = json.dumps({
            "task_name": "task1",
            "error": "Connection failed",
        })

        with patch(f"{STATUS_MODULE}.redis.from_url", return_value=mock_async_redis):
            async with JobStatusTracker() as tracker:
                entries = await tracker.list_dlq_entries()

        assert len(entries) == 1
        assert entries[0]["task_name"] == "task1"

    @pytest.mark.asyncio
    async def test_delete_dlq_entry(self, mock_async_redis):
        """Test deleting a DLQ entry."""
        mock_async_redis.delete.return_value = 1

        with patch(f"{STATUS_MODULE}.redis.from_url", return_value=mock_async_redis):
            async with JobStatusTracker() as tracker:
                result = await tracker.delete_dlq_entry("dlq:task1:2024-01-01")

        assert result is True
        mock_async_redis.delete.assert_called_once_with("dlq:task1:2024-01-01")

    @pytest.mark.asyncio
    async def test_get_queue_stats(self):
        """Test getting queue statistics."""
        tracker = JobStatusTracker()

        with patch(f"{STATUS_MODULE}.celery_app") as mock_app:
            mock_inspect = MagicMock()
            mock_inspect.reserved.return_value = {"worker1": [1, 2]}
            mock_inspect.active.return_value = {"worker1": [1]}
            mock_inspect.scheduled.return_value = {"worker1": []}
            mock_app.control.inspect.return_value = mock_inspect

            stats = await tracker.get_queue_stats()

            assert stats["reserved"] == 2
            assert stats["active"] == 1
            assert stats["scheduled"] == 0
