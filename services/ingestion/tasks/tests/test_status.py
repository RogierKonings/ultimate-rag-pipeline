"""Tests for job status tracking."""

from unittest.mock import MagicMock, patch

import pytest

from .. import status as status_module
from ..models import JobStatus


class TestJobStatusTracker:
    """Tests for JobStatusTracker class."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, mock_async_redis):
        """Test connection management."""
        tracker = status_module.JobStatusTracker(redis_url="redis://localhost:6379/0")

        with patch.object(status_module.redis, "from_url", return_value=mock_async_redis):
            await tracker.connect()
            assert tracker._redis is not None

            await tracker.disconnect()
            mock_async_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_async_redis):
        """Test async context manager."""
        with patch.object(status_module.redis, "from_url", return_value=mock_async_redis):
            async with status_module.JobStatusTracker() as tracker:
                assert tracker._redis is not None

            mock_async_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_status_pending(self):
        """Test getting status of pending job."""
        mock_async_result = MagicMock()
        mock_async_result.status = "PENDING"
        mock_async_result.info = None

        with patch.object(status_module, "AsyncResult", return_value=mock_async_result):
            tracker = status_module.JobStatusTracker()
            status = await tracker.get_job_status("test-job-id")

            assert status.job_id == "test-job-id"
            assert status.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_job_status_progress(self):
        """Test getting status of in-progress job."""
        mock_async_result = MagicMock()
        mock_async_result.status = "PROGRESS"
        mock_async_result.info = {
            "stage": "embedding",
            "processed": 50,
            "total": 100,
            "message": "Processing chunks...",
        }

        with patch.object(status_module, "AsyncResult", return_value=mock_async_result):
            tracker = status_module.JobStatusTracker()
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
        mock_async_result = MagicMock()
        mock_async_result.status = "SUCCESS"
        mock_async_result.info = {
            "documents_processed": 10,
            "chunks_created": 100,
            "duration_seconds": 45.5,
        }

        with patch.object(status_module, "AsyncResult", return_value=mock_async_result):
            tracker = status_module.JobStatusTracker()
            status = await tracker.get_job_status("test-job-id")

            assert status.status == JobStatus.SUCCESS
            assert status.documents_processed == 10
            assert status.chunks_created == 100

    @pytest.mark.asyncio
    async def test_get_job_status_failure(self):
        """Test getting status of failed job."""
        mock_async_result = MagicMock()
        mock_async_result.status = "FAILURE"
        mock_async_result.info = {
            "error": "Connection failed",
            "traceback": "Traceback...",
        }

        with patch.object(status_module, "AsyncResult", return_value=mock_async_result):
            tracker = status_module.JobStatusTracker()
            status = await tracker.get_job_status("test-job-id")

            assert status.status == JobStatus.FAILURE
            assert status.error_message == "Connection failed"

    @pytest.mark.asyncio
    async def test_cancel_job(self):
        """Test cancelling a job."""
        mock_async_result = MagicMock()
        mock_async_result.revoke = MagicMock()

        with patch.object(status_module, "AsyncResult", return_value=mock_async_result):
            tracker = status_module.JobStatusTracker()
            result = await tracker.cancel_job("test-job-id")

            assert result is True
            mock_async_result.revoke.assert_called_once_with(terminate=True)

    @pytest.mark.asyncio
    async def test_list_active_jobs(self):
        """Test listing active jobs."""
        mock_inspect = MagicMock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "job-1"}, {"id": "job-2"}],
            "worker2": [{"id": "job-3"}],
        }

        with patch.object(status_module, "celery_app") as mock_app:
            mock_app.control.inspect.return_value = mock_inspect
            tracker = status_module.JobStatusTracker()
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
        mock_async_redis.get.return_value = json.dumps(
            {
                "task_name": "task1",
                "error": "Connection failed",
            },
        )

        with patch.object(status_module.redis, "from_url", return_value=mock_async_redis):
            async with status_module.JobStatusTracker() as tracker:
                entries = await tracker.list_dlq_entries()

        assert len(entries) == 1
        assert entries[0]["task_name"] == "task1"

    @pytest.mark.asyncio
    async def test_delete_dlq_entry(self, mock_async_redis):
        """Test deleting a DLQ entry."""
        mock_async_redis.delete.return_value = 1

        with patch.object(status_module.redis, "from_url", return_value=mock_async_redis):
            async with status_module.JobStatusTracker() as tracker:
                result = await tracker.delete_dlq_entry("dlq:task1:2024-01-01")

        assert result is True
        mock_async_redis.delete.assert_called_once_with("dlq:task1:2024-01-01")

    @pytest.mark.asyncio
    async def test_get_queue_stats(self):
        """Test getting queue statistics."""
        mock_inspect = MagicMock()
        mock_inspect.reserved.return_value = {"worker1": [1, 2]}
        mock_inspect.active.return_value = {"worker1": [1]}
        mock_inspect.scheduled.return_value = {"worker1": []}

        with patch.object(status_module, "celery_app") as mock_app:
            mock_app.control.inspect.return_value = mock_inspect
            tracker = status_module.JobStatusTracker()
            stats = await tracker.get_queue_stats()

            assert stats["reserved"] == 2
            assert stats["active"] == 1
            assert stats["scheduled"] == 0
