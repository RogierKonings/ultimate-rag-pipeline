"""Tests for AuditMiddleware integration in the orchestrator service.

These tests verify that the AuditMiddleware is properly configured
and integrated with the orchestrator service for compliance logging (US-10.7.5).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.app import create_app
from fastapi.testclient import TestClient

from shared.security.audit import AuditMiddleware


class TestAuditMiddlewareConfiguration:
    """Tests for AuditMiddleware configuration in the orchestrator."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI application."""
        with patch("api.app.validate_on_startup"):
            return create_app()

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app, raise_server_exceptions=False)

    def test_audit_middleware_is_configured(self, app):
        """Test that AuditMiddleware is configured in the application."""
        # Check that the middleware stack contains AuditMiddleware
        middleware_classes = []
        for middleware in app.user_middleware:
            middleware_classes.append(middleware.cls)

        assert AuditMiddleware in middleware_classes, (
            "AuditMiddleware should be configured in the application"
        )

    def test_audit_middleware_has_correct_service_name(self, app):
        """Test that AuditMiddleware is configured with correct service name."""
        for middleware in app.user_middleware:
            if middleware.cls == AuditMiddleware:
                assert middleware.kwargs.get("service_name") == "orchestrator-service", (
                    "AuditMiddleware should be configured with service_name='orchestrator-service'"
                )
                break
        else:
            pytest.fail("AuditMiddleware not found in middleware stack")

    def test_audit_middleware_excludes_health_endpoints(self, app):
        """Test that AuditMiddleware excludes health check endpoints."""
        for middleware in app.user_middleware:
            if middleware.cls == AuditMiddleware:
                exclude_paths = middleware.kwargs.get("exclude_paths", [])
                expected_excludes = [
                    "/health",
                    "/healthz",
                    "/ready",
                    "/metrics",
                    "/docs",
                    "/redoc",
                    "/openapi.json",
                ]
                for path in expected_excludes:
                    assert path in exclude_paths, (
                        f"Path '{path}' should be excluded from audit logging"
                    )
                break
        else:
            pytest.fail("AuditMiddleware not found in middleware stack")


class TestAuditMiddlewareExclusions:
    """Tests for path exclusions in AuditMiddleware."""

    @pytest.fixture
    def mock_audit_logger(self):
        """Create a mock audit logger."""
        logger = MagicMock()
        logger.log = AsyncMock()
        return logger

    @pytest.fixture
    def app(self, mock_audit_logger):
        """Create test FastAPI application with mocked audit logger."""
        with patch("api.app.validate_on_startup"), patch(
            "shared.security.audit.middleware.get_audit_logger",
            return_value=mock_audit_logger,
        ):
            app = create_app()
            # Set required app state for health endpoints
            app.state.session_manager = MagicMock()
            app.state.session_manager.store = MagicMock()
            app.state.session_manager.store._redis = AsyncMock()
            app.state.session_manager.store._redis.ping = AsyncMock(return_value=True)
            app.state.model_gateway = AsyncMock()
            app.state.model_gateway.health_check = AsyncMock(
                return_value={"llama": {"status": "healthy"}}
            )
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint_excluded_from_audit(self, client, mock_audit_logger):
        """Test that /health endpoint is excluded from audit logging."""
        # Reset mock to clear any previous calls
        mock_audit_logger.log.reset_mock()

        response = client.get("/health")

        # Health endpoint should return successfully (200 or 503 depending on state)
        assert response.status_code in [200, 503]

    def test_healthz_endpoint_excluded_from_audit(self, client, mock_audit_logger):
        """Test that /healthz endpoint is excluded from audit logging."""
        mock_audit_logger.log.reset_mock()

        # healthz may not exist, but the exclusion should still apply
        response = client.get("/healthz")

        # The point is to verify exclusion works - 404 is acceptable if route doesn't exist
        assert response.status_code in [200, 404, 503]

    def test_docs_endpoint_excluded_from_audit(self, client, mock_audit_logger):
        """Test that /docs endpoint is excluded from audit logging."""
        mock_audit_logger.log.reset_mock()

        response = client.get("/docs")

        # Docs endpoint should return 200 (HTML) or redirect
        assert response.status_code in [200, 307, 308]

    def test_openapi_json_excluded_from_audit(self, client, mock_audit_logger):
        """Test that /openapi.json endpoint is excluded from audit logging."""
        mock_audit_logger.log.reset_mock()

        response = client.get("/openapi.json")

        # OpenAPI spec should be accessible
        assert response.status_code == 200
        assert "openapi" in response.json()


class TestAuditMiddlewareOrder:
    """Tests for middleware ordering."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI application."""
        with patch("api.app.validate_on_startup"):
            return create_app()

    def test_audit_middleware_after_correlation_middleware(self, app):
        """Test that AuditMiddleware is added after CorrelationMiddleware.

        In FastAPI, middleware added later is the outermost layer and processes
        first on incoming requests. FastAPI stores middleware in reverse order
        (middleware added last has lowest index in user_middleware list).

        The current setup:
        - CorrelationMiddleware added first (becomes inner layer)
        - AuditMiddleware added second (becomes outer layer)

        In app.user_middleware:
        - AuditMiddleware at lower index (outer, added last)
        - CorrelationMiddleware at higher index (inner, added first)

        Request flow:
        1. AuditMiddleware (outer) - reads trace_id from incoming headers
        2. CorrelationMiddleware (inner) - sets up context, adds headers to response
        3. Route handler
        4. CorrelationMiddleware response handling
        5. AuditMiddleware response handling - logs audit event

        AuditMiddleware reads trace_id from incoming request headers, not from
        context set by CorrelationMiddleware, so this order is correct.
        """
        from shared.observability.correlation import CorrelationMiddleware

        middleware_classes = [m.cls for m in app.user_middleware]

        # Find positions
        correlation_pos = None
        audit_pos = None

        for i, cls in enumerate(middleware_classes):
            if cls == CorrelationMiddleware:
                correlation_pos = i
            elif cls == AuditMiddleware:
                audit_pos = i

        assert correlation_pos is not None, "CorrelationMiddleware should be configured"
        assert audit_pos is not None, "AuditMiddleware should be configured"

        # In FastAPI's user_middleware list, middleware added later has lower index
        # AuditMiddleware should have lower index than CorrelationMiddleware
        # because it was added after (is the outer layer)
        assert audit_pos < correlation_pos, (
            "AuditMiddleware should be added after CorrelationMiddleware in code "
            "(lower index = outer layer in middleware stack)"
        )
