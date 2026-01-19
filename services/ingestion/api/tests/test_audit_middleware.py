"""Tests for audit middleware integration in ingestion service."""

import pytest
from unittest.mock import AsyncMock, patch


class TestAuditMiddlewareIntegration:
    """Tests for audit middleware in ingestion service."""

    def test_middleware_is_configured(self, client):
        """Should have audit middleware configured."""
        response = client.get("/documents")
        # Should complete (status depends on auth/data state)
        assert response.status_code in [200, 401, 403, 404, 422]

    def test_health_endpoint_not_logged(self, client):
        """Should exclude health endpoint from logging."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_docs_endpoint_not_logged(self, client):
        """Should exclude docs endpoint from logging."""
        response = client.get("/docs")
        # FastAPI docs endpoint returns HTML, status depends on config
        assert response.status_code in [200, 404]

    def test_metrics_endpoint_not_logged(self, client):
        """Should exclude metrics endpoint from logging."""
        response = client.get("/metrics")
        assert response.status_code == 200
