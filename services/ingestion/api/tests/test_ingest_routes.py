"""Tests for ingestion API routes."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from tasks.models import IngestJobResult, JobProgress, JobStatus


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert response.json()["service"] == "ingestion"


class TestStartIngestion:
    """Tests for POST /ingest endpoint."""

    def test_requires_auth(self, client_no_auth):
        """Returns 401 without auth token."""
        response = client_no_auth.post("/ingest", json={})
        assert response.status_code == 401

    def test_start_ingestion_success(self, client, auth_headers):
        """Successfully starts ingestion job."""
        with patch("api.routes.ingest.batch_ingest") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest",
                json={
                    "source_type": "filesystem",
                    "source_config": {"path": "/data", "storage_type": "local"},
                    "acl": {"tenant_id": "tenant-123"},
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            assert "job_id" in response.json()
            assert response.json()["status"] == "pending"

    def test_tenant_isolation(self, client, auth_headers):
        """Returns 403 when ingesting for different tenant."""
        response = client.post(
            "/ingest",
            json={
                "source_type": "filesystem",
                "source_config": {"path": "/data"},
                "acl": {"tenant_id": "other-tenant"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_validates_source_config(self, client, auth_headers):
        """Validates source config matches source type."""
        response = client.post(
            "/ingest",
            json={
                "source_type": "database",
                "source_config": {
                    # Missing required fields for database
                    "path": "/data",
                },
                "acl": {"tenant_id": "tenant-123"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestGetJobStatus:
    """Tests for GET /ingest/{job_id} endpoint."""

    def test_get_job_status_success(self, client_with_job_tracker, auth_headers, mock_job_tracker):
        """Returns job status."""
        job_id = uuid4()
        mock_job_tracker.get_job_status.return_value = IngestJobResult(
            job_id=str(job_id),
            status=JobStatus.PROGRESS,
            progress=JobProgress(current=5, total=10, stage="embedding"),
            documents_processed=5,
            chunks_created=50,
        )

        response = client_with_job_tracker.get(f"/ingest/{job_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == str(job_id)
        assert data["status"] == "progress"
        assert data["progress"]["current"] == 5
        mock_job_tracker.get_job_status.assert_called_once()

    def test_job_not_found(self, client_with_job_tracker, auth_headers, mock_job_tracker):
        """Returns 404 for non-existent job."""
        job_id = uuid4()
        mock_job_tracker.get_job_status.return_value = None

        response = client_with_job_tracker.get(f"/ingest/{job_id}", headers=auth_headers)

        assert response.status_code == 404


class TestCancelJob:
    """Tests for DELETE /ingest/{job_id} endpoint."""

    def test_cancel_job_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        job_id = uuid4()
        response = client_no_auth.delete(f"/ingest/{job_id}")
        assert response.status_code == 401


class TestListActiveJobs:
    """Tests for GET /ingest endpoint."""

    def test_list_jobs_requires_auth(self, client_no_auth):
        """Returns 401 without auth."""
        response = client_no_auth.get("/ingest")
        assert response.status_code == 401


class TestSingleDocumentIngestion:
    """Tests for POST /ingest/single endpoint."""

    def test_single_ingest_success(self, client, auth_headers):
        """Successfully ingests single document."""
        with patch("api.routes.ingest.process_document") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/single",
                json={
                    "source_type": "filesystem",
                    "source_id": "doc-001",
                    "source_config": {"path": "/data"},
                    "acl": {"tenant_id": "tenant-123"},
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            assert "job_id" in response.json()
