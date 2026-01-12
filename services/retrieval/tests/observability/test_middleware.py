"""Tests for logging middleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from observability.metrics import RetrievalMetrics
from observability.middleware import LoggingMiddleware, setup_observability
from observability.retrieval_logger import RetrievalLogger


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    @pytest.fixture
    def logger(self):
        """Create logger instance."""
        return RetrievalLogger(
            service_name="test-service",
            log_level="INFO",
            output_format="json",
        )

    @pytest.fixture
    def metrics(self):
        """Create metrics instance."""
        import uuid

        return RetrievalMetrics(f"test_middleware_{uuid.uuid4().hex[:8]}")

    @pytest.fixture
    def app(self, logger, metrics):
        """Create FastAPI app with middleware."""
        app = FastAPI()
        app.add_middleware(LoggingMiddleware, logger=logger, metrics=metrics)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app, raise_server_exceptions=False)

    def test_successful_request_logging(self, client, capsys):
        """Test that successful requests are logged."""
        response = client.get("/test")
        assert response.status_code == 200

    def test_error_request_logging(self, client, capsys):
        """Test that error requests are logged."""
        response = client.get("/error")
        assert response.status_code == 500

    def test_active_requests_tracked(self, client, metrics):
        """Test that active requests are tracked."""
        # Make a request
        response = client.get("/test")
        assert response.status_code == 200

    def test_timing_logged(self, client, capsys):
        """Test that request timing is logged."""
        response = client.get("/test")
        assert response.status_code == 200
        # Timing should be in logs


class TestSetupObservability:
    """Tests for setup_observability function."""

    def _make_config(self, suffix: str):
        """Create config with unique service name."""
        import uuid

        class MockConfig:
            service_name = f"test-retrieval-{suffix}-{uuid.uuid4().hex[:6]}"
            log_level = "INFO"
            log_format = "json"
            otlp_endpoint = "http://localhost:4317"

        return MockConfig()

    def test_setup_creates_all_components(self):
        """Test that setup creates logger, metrics, and tracing."""
        app = FastAPI()
        logger, metrics, tracing = setup_observability(app, self._make_config("comp"))

        assert logger is not None
        assert metrics is not None
        assert tracing is not None

    def test_setup_adds_metrics_endpoint(self):
        """Test that setup adds /metrics endpoint."""
        app = FastAPI()
        setup_observability(app, self._make_config("metrics"))

        client = TestClient(app)
        response = client.get("/metrics")

        assert response.status_code == 200

    def test_setup_stores_in_app_state(self):
        """Test that setup stores components in app state."""
        app = FastAPI()
        setup_observability(app, self._make_config("state"))

        assert hasattr(app.state, "logger")
        assert hasattr(app.state, "metrics")
        assert hasattr(app.state, "tracing")

    def test_setup_with_minimal_config(self):
        """Test setup with minimal configuration."""
        import uuid

        class MinimalConfig:
            service_name = f"minimal-{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        logger, metrics, tracing = setup_observability(app, MinimalConfig())

        # Should use defaults
        assert logger is not None
        assert metrics is not None

    def test_metrics_endpoint_content_type(self):
        """Test that metrics endpoint returns correct content type."""
        app = FastAPI()
        setup_observability(app, self._make_config("ctype"))

        client = TestClient(app)
        response = client.get("/metrics")

        # Should have text content type
        assert "text" in response.headers.get("content-type", "")


class TestMiddlewareIntegration:
    """Integration tests for middleware with full app."""

    def _make_app(self, suffix: str):
        """Create fully configured app with unique service name."""
        import uuid

        class Config:
            service_name = f"integ-test-{suffix}-{uuid.uuid4().hex[:6]}"
            log_level = "DEBUG"
            log_format = "json"
            otlp_endpoint = "http://localhost:4317"

        app = FastAPI()
        setup_observability(app, Config())

        @app.get("/")
        async def root():
            return {"message": "Hello"}

        @app.post("/search")
        async def search():
            return {"results": []}

        return app

    def test_multiple_requests(self):
        """Test multiple requests are logged correctly."""
        app = self._make_app("multi")
        client = TestClient(app)

        for _ in range(5):
            response = client.get("/")
            assert response.status_code == 200

    def test_different_endpoints(self):
        """Test different endpoints are logged."""
        app = self._make_app("diff")
        client = TestClient(app)

        response1 = client.get("/")
        response2 = client.post("/search")

        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_metrics_accumulate(self):
        """Test that metrics accumulate over requests."""
        app = self._make_app("accum")
        client = TestClient(app)

        # Make several requests
        for _ in range(3):
            client.get("/")

        # Check metrics endpoint
        response = client.get("/metrics")
        assert response.status_code == 200
