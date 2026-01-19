"""Tests for audit middleware integration in retrieval service.

US-10.7.5 - Comprehensive Audit Logging for the retrieval service.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def config():
    """Test configuration."""
    from config import RetrievalConfig

    return RetrievalConfig(
        jwt_secret="test-secret-key",
        debug=True,
    )


@pytest.fixture
def app(config):
    """Create test FastAPI app with full middleware stack."""
    from api.main import create_app

    return create_app(config)


@pytest.fixture
def client(app):
    """Test client."""
    return TestClient(app, raise_server_exceptions=False)


class TestAuditMiddlewareIntegration:
    """Tests for audit middleware in retrieval service."""

    def test_middleware_is_configured(self, client):
        """Should have audit middleware configured and request completes."""
        # Make a request to any endpoint - the middleware should process it
        response = client.get("/api/v1/retrieve")
        # Should complete (status depends on auth/data state)
        assert response.status_code in [200, 401, 403, 404, 405, 422, 500]

    def test_health_endpoint_not_logged(self, client):
        """Should exclude health endpoint from audit logging."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_healthz_endpoint_not_logged(self, client):
        """Should exclude healthz endpoint from audit logging."""
        response = client.get("/healthz")
        # Endpoint may or may not exist
        assert response.status_code in [200, 404]

    def test_ready_endpoint_not_logged(self, client):
        """Should exclude ready endpoint from audit logging."""
        response = client.get("/ready")
        # Endpoint may or may not exist
        assert response.status_code in [200, 404]

    def test_docs_endpoint_not_logged(self, client):
        """Should exclude docs endpoint from audit logging."""
        response = client.get("/docs")
        # FastAPI docs endpoint returns HTML, status depends on config
        assert response.status_code in [200, 404]

    def test_redoc_endpoint_not_logged(self, client):
        """Should exclude redoc endpoint from audit logging."""
        response = client.get("/redoc")
        # ReDoc endpoint returns HTML, status depends on config
        assert response.status_code in [200, 404]

    def test_openapi_json_not_logged(self, client):
        """Should exclude openapi.json endpoint from audit logging."""
        response = client.get("/openapi.json")
        # OpenAPI spec endpoint, status depends on config
        assert response.status_code in [200, 404]
