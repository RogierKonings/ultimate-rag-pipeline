"""Integration tests for correlation propagation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from ..middleware import CorrelationMiddleware
from ..http_client import CorrelatedHttpClient
from ..context import (
    CorrelationContext,
    get_correlation_context,
    set_correlation_context,
    clear_correlation_context,
)
from ..celery import (
    inject_correlation_to_task,
    extract_correlation_from_task,
    cleanup_correlation_for_task,
)


class TestMiddlewareToHttpClientPropagation:
    """Tests for correlation propagation from middleware to HTTP client."""

    @pytest.fixture
    def downstream_app(self):
        """Create a downstream service that captures headers."""
        app = FastAPI()
        captured_headers = {}

        @app.post("/api/search")
        async def search(request):
            # Capture correlation headers
            captured_headers.update({
                "x-request-id": request.headers.get("x-request-id"),
                "x-trace-id": request.headers.get("x-trace-id"),
                "x-tenant-id": request.headers.get("x-tenant-id"),
            })
            return {"results": []}

        return app, captured_headers

    @pytest.mark.asyncio
    async def test_correlation_propagates_through_http_client(self):
        """Correlation from middleware should propagate via HTTP client."""
        # Simulate middleware setting context
        ctx = CorrelationContext(
            request_id="test-req-123",
            trace_id="test-trace-456",
            tenant_id="tenant-789",
        )
        set_correlation_context(ctx)

        captured_headers = {}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"results": []}
            return response

        with patch.object(httpx.AsyncClient, "post", side_effect=mock_post):
            client = CorrelatedHttpClient(base_url="http://downstream:8000")
            async with client:
                await client.post("/api/search", json={"query": "test"})

        assert captured_headers.get("X-Request-ID") == "test-req-123"
        assert captured_headers.get("X-Trace-ID") == "test-trace-456"
        assert captured_headers.get("X-Tenant-ID") == "tenant-789"

        clear_correlation_context()


class TestCeleryCorrelationPropagation:
    """Tests for correlation propagation through Celery tasks."""

    def test_full_celery_propagation_cycle(self):
        """Should propagate correlation through Celery task lifecycle."""
        # Set up parent context (e.g., from HTTP request)
        parent_ctx = CorrelationContext(
            request_id="http-req-123",
            trace_id="http-trace-456",
            tenant_id="tenant-789",
            user_id_hash="user-hash-abc",
        )
        set_correlation_context(parent_ctx)

        # Simulate before_task_publish signal
        task_headers = {}
        inject_correlation_to_task(task_headers)

        # Clear context (simulating different process/worker)
        clear_correlation_context()
        assert get_correlation_context() is None

        # Simulate task_prerun signal (worker receiving task)
        extract_correlation_from_task(task_headers, task_id="celery-task-001")

        # Verify context is restored
        restored_ctx = get_correlation_context()
        assert restored_ctx is not None
        assert restored_ctx.request_id == "http-req-123"
        assert restored_ctx.trace_id == "http-trace-456"
        assert restored_ctx.tenant_id == "tenant-789"

        # Simulate task_postrun signal
        cleanup_correlation_for_task()

        # Verify cleanup
        assert get_correlation_context() is None


class TestLogJoinability:
    """Tests to verify logs are joinable by request_id."""

    def test_logs_include_correlation_context(self, capfd):
        """Logs should include correlation context for joinability.

        This test verifies that the middleware properly binds correlation
        context to structlog, making logs joinable by request_id.
        """
        app = FastAPI()
        app.add_middleware(CorrelationMiddleware, service_name="test-service")

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get(
            "/test",
            headers={"X-Request-ID": "joinable-req-123"}
        )

        assert response.status_code == 200

        # Capture the log output
        captured = capfd.readouterr()

        # Verify logs include the request_id (proving structlog context binding)
        assert "request_id=joinable-req-123" in captured.out
        assert "trace_id=joinable-req-123" in captured.out
        assert "request_started" in captured.out
        assert "request_completed" in captured.out


class TestEndToEndCorrelation:
    """End-to-end correlation propagation tests."""

    def test_middleware_sets_and_clears_context(self):
        """Middleware should properly set and clear correlation context."""
        app = FastAPI()
        app.add_middleware(CorrelationMiddleware, service_name="test-service")

        context_during_request = None

        @app.get("/capture")
        async def capture_context():
            nonlocal context_during_request
            context_during_request = get_correlation_context()
            return {"captured": True}

        client = TestClient(app)

        # Clear any existing context
        clear_correlation_context()

        response = client.get(
            "/capture",
            headers={
                "X-Request-ID": "e2e-req-123",
                "X-Trace-ID": "e2e-trace-456",
                "X-Tenant-ID": "e2e-tenant-789",
            }
        )

        assert response.status_code == 200

        # Context should have been set during request
        assert context_during_request is not None
        assert context_during_request.request_id == "e2e-req-123"
        assert context_during_request.trace_id == "e2e-trace-456"
        assert context_during_request.tenant_id == "e2e-tenant-789"

        # Response should include correlation headers
        assert response.headers.get("X-Request-ID") == "e2e-req-123"
        assert response.headers.get("X-Trace-ID") == "e2e-trace-456"

    def test_correlation_generates_ids_if_missing(self):
        """Should generate correlation IDs if not provided in request."""
        app = FastAPI()
        app.add_middleware(CorrelationMiddleware, service_name="test-service")

        context_during_request = None

        @app.get("/generate")
        async def generate_context():
            nonlocal context_during_request
            context_during_request = get_correlation_context()
            return {"generated": True}

        client = TestClient(app)
        clear_correlation_context()

        response = client.get("/generate")

        assert response.status_code == 200

        # Context should have generated IDs
        assert context_during_request is not None
        assert context_during_request.request_id is not None
        assert len(context_during_request.request_id) == 36  # UUID format

        # Response headers should have the generated IDs
        assert response.headers.get("X-Request-ID") is not None
        assert len(response.headers.get("X-Request-ID")) == 36
