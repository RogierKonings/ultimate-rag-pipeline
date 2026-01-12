"""Tests for sync and reembed API endpoints.

Tests for:
- POST /ingest/sync - incremental sync
- POST /ingest/reembed - re-embedding with new model
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4


class TestSyncEndpoint:
    """Tests for POST /ingest/sync endpoint."""

    def test_sync_requires_auth(self, client_no_auth):
        """Returns 401 without auth token."""
        response = client_no_auth.post("/ingest/sync", json={})
        assert response.status_code == 401

    def test_sync_success(self, client, auth_headers):
        """Successfully starts incremental sync job."""
        with patch("api.routes.ingest.batch_ingest") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/sync",
                json={
                    "tenant_id": "tenant-123",
                    "source_type": "database",
                    "source_config": {
                        "connection_string": "postgresql://localhost/db",
                        "table": "articles",
                        "updated_since": "2025-12-01T00:00:00Z",
                    },
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "queued"
            assert "sync" in data["message"].lower()

    def test_sync_tenant_isolation(self, client, auth_headers):
        """Returns 403 when syncing for different tenant."""
        response = client.post(
            "/ingest/sync",
            json={
                "tenant_id": "other-tenant",
                "source_type": "filesystem",
                "source_config": {"path": "/data"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_sync_invalid_payload(self, client, auth_headers):
        """Returns 422 for invalid source_config."""
        response = client.post(
            "/ingest/sync",
            json={
                "tenant_id": "tenant-123",
                "source_type": "database",
                "source_config": {
                    # Missing required connection_string and table for DATABASE
                    "path": "/data",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_sync_filesystem_source(self, client, auth_headers):
        """Successfully syncs filesystem source."""
        with patch("api.routes.ingest.batch_ingest") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/sync",
                json={
                    "tenant_id": "tenant-123",
                    "source_type": "filesystem",
                    "source_config": {
                        "path": "/data/documents",
                        "updated_since": "2025-12-01T00:00:00Z",
                    },
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            mock_task.delay.assert_called_once()


class TestReembedEndpoint:
    """Tests for POST /ingest/reembed endpoint."""

    def test_reembed_requires_auth(self, client_no_auth):
        """Returns 401 without auth token."""
        response = client_no_auth.post("/ingest/reembed", json={})
        assert response.status_code == 401

    def test_reembed_success(self, client, auth_headers):
        """Successfully starts re-embedding job."""
        with patch("api.routes.ingest.reembed_collection") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/reembed",
                json={
                    "embedding_model": "BAAI/bge-m3",
                    "target_scope": {
                        "tenant_id": "tenant-123",
                        "source_types": ["filesystem", "web"],
                    },
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            data = response.json()
            assert "job_id" in data
            assert "embedding_job_id" in data
            assert data["status"] == "pending"
            assert "bge-m3" in data["message"]

    def test_reembed_tenant_isolation(self, client, auth_headers):
        """Returns 403 when re-embedding for different tenant."""
        response = client.post(
            "/ingest/reembed",
            json={
                "embedding_model": "BAAI/bge-large-en-v1.5",
                "target_scope": {"tenant_id": "other-tenant"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_reembed_without_tenant_scope(self, client, auth_headers):
        """Re-embed without tenant in scope uses current user's tenant."""
        with patch("api.routes.ingest.reembed_collection") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/reembed",
                json={
                    "embedding_model": "BAAI/bge-m3",
                    "target_scope": {},  # No tenant specified
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            # Verify the task was called with current user's tenant
            mock_task.delay.assert_called_once()
            call_kwargs = mock_task.delay.call_args.kwargs
            assert call_kwargs["tenant_id"] == "tenant-123"

    def test_reembed_custom_batch_size(self, client, auth_headers):
        """Re-embed with custom batch size."""
        with patch("api.routes.ingest.reembed_collection") as mock_task:
            mock_task.delay.return_value = MagicMock(id=str(uuid4()))

            response = client.post(
                "/ingest/reembed",
                json={
                    "embedding_model": "BAAI/bge-large-en-v1.5",
                    "target_scope": {"tenant_id": "tenant-123"},
                    "batch_size": 500,
                },
                headers=auth_headers,
            )

            assert response.status_code == 202
            call_kwargs = mock_task.delay.call_args.kwargs
            assert call_kwargs["batch_size"] == 500

    def test_reembed_invalid_batch_size(self, client, auth_headers):
        """Returns 422 for invalid batch size."""
        response = client.post(
            "/ingest/reembed",
            json={
                "embedding_model": "BAAI/bge-m3",
                "target_scope": {"tenant_id": "tenant-123"},
                "batch_size": 5,  # Below minimum of 10
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
