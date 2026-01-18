"""Tests for CorrelationMiddleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..middleware import CorrelationMiddleware
from ..context import get_correlation_context, clear_correlation_context


@pytest.fixture
def app():
    """Create test FastAPI app with CorrelationMiddleware."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware, service_name="test-service")

    @app.get("/test")
    async def test_endpoint():
        ctx = get_correlation_context()
        return {
            "request_id": ctx.request_id if ctx else None,
            "tenant_id": ctx.tenant_id if ctx else None,
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestCorrelationMiddleware:
    """Tests for CorrelationMiddleware."""

    def test_generates_request_id_if_not_provided(self, client):
        """Should generate request_id when not in headers."""
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) == 36

    def test_preserves_existing_request_id(self, client):
        """Should preserve request_id from incoming headers."""
        response = client.get(
            "/test",
            headers={"X-Request-ID": "existing-req-123"}
        )

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "existing-req-123"
        data = response.json()
        assert data["request_id"] == "existing-req-123"

    def test_extracts_tenant_id_from_headers(self, client):
        """Should extract tenant_id from headers."""
        response = client.get(
            "/test",
            headers={
                "X-Request-ID": "req-123",
                "X-Tenant-ID": "tenant-456"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "tenant-456"

    def test_adds_trace_id_to_response(self, client):
        """Should add X-Trace-ID to response headers."""
        response = client.get(
            "/test",
            headers={"X-Request-ID": "req-123"}
        )

        assert "X-Trace-ID" in response.headers

    def test_clears_context_after_request(self, client):
        """Should clear context after request completes."""
        clear_correlation_context()

        response = client.get("/test")
        assert response.status_code == 200

        ctx = get_correlation_context()
        assert ctx is None

    def test_skips_excluded_paths(self, client):
        """Should not process excluded paths like /health."""
        response = client.get("/health")

        assert response.status_code == 200
        # Health endpoint should not have correlation headers
        # (middleware skips it)
        assert "X-Request-ID" not in response.headers

    def test_custom_excluded_paths(self):
        """Should support custom excluded paths."""
        app = FastAPI()
        app.add_middleware(
            CorrelationMiddleware,
            service_name="test-service",
            excluded_paths=["/custom-health", "/metrics"]
        )

        @app.get("/custom-health")
        async def custom_health():
            return {"status": "ok"}

        @app.get("/api/data")
        async def api_data():
            ctx = get_correlation_context()
            return {"request_id": ctx.request_id if ctx else None}

        client = TestClient(app)

        # Custom health should be excluded
        response = client.get("/custom-health")
        assert response.status_code == 200
        assert "X-Request-ID" not in response.headers

        # API endpoint should be processed
        response = client.get("/api/data")
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

    def test_propagates_trace_id_from_headers(self, client):
        """Should propagate trace_id from incoming headers."""
        response = client.get(
            "/test",
            headers={
                "X-Request-ID": "req-123",
                "X-Trace-ID": "trace-789"
            }
        )

        assert response.status_code == 200
        assert response.headers["X-Trace-ID"] == "trace-789"

    def test_uses_request_id_as_trace_id_if_not_provided(self, client):
        """Should use request_id as trace_id when not provided."""
        response = client.get(
            "/test",
            headers={"X-Request-ID": "req-123"}
        )

        assert response.status_code == 200
        # trace_id should default to request_id
        assert response.headers["X-Trace-ID"] == "req-123"
