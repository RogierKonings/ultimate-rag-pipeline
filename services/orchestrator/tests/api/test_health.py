"""Tests for health check endpoints."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from api.routes.health import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create test FastAPI application."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_session_manager():
    """Create mock session manager."""
    manager = MagicMock()
    manager.store = MagicMock()
    manager.store._redis = AsyncMock()
    manager.store._redis.ping = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_model_gateway():
    """Create mock model gateway."""
    gateway = AsyncMock()
    gateway.health_check = AsyncMock(
        return_value={"llama": {"status": "healthy", "latency_ms": 10}},
    )
    return gateway


class TestLivenessProbe:
    """Tests for the liveness probe endpoint."""

    def test_liveness_returns_200(self, client):
        """Test that liveness probe returns 200 OK."""
        response = client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_liveness_works_without_app_state(self, client):
        """Test that liveness probe works without any app state."""
        # Liveness should work even if services aren't initialized
        response = client.get("/health/live")

        assert response.status_code == 200


class TestReadinessProbe:
    """Tests for the readiness probe endpoint."""

    def test_readiness_returns_503_without_session_manager(self, client, app):
        """Test readiness returns 503 when session manager is not initialized."""
        # No app state set
        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert "Session manager not initialized" in data["reasons"]

    def test_readiness_returns_503_without_model_gateway(
        self, client, app, mock_session_manager,
    ):
        """Test readiness returns 503 when model gateway is not initialized."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = None

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert "Model gateway not initialized" in data["reasons"]

    def test_readiness_returns_200_when_all_services_ready(
        self, client, app, mock_session_manager, mock_model_gateway,
    ):
        """Test readiness returns 200 when all services are ready."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = mock_model_gateway

        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_readiness_returns_503_when_redis_unavailable(
        self, client, app, mock_model_gateway,
    ):
        """Test readiness returns 503 when Redis is unavailable."""
        manager = MagicMock()
        manager.store = MagicMock()
        manager.store._redis = AsyncMock()
        manager.store._redis.ping = AsyncMock(side_effect=Exception("Connection refused"))

        app.state.session_manager = manager
        app.state.model_gateway = mock_model_gateway

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert any("Redis not available" in reason for reason in data["reasons"])


class TestDetailedHealthCheck:
    """Tests for the detailed health check endpoint."""

    def test_health_returns_healthy_when_all_components_healthy(
        self, client, app, mock_session_manager, mock_model_gateway,
    ):
        """Test health returns healthy when all components are healthy."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = mock_model_gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "orchestrator-service"
        assert "uptime_seconds" in data
        assert "components" in data
        assert "timestamp" in data

    def test_health_includes_component_details(
        self, client, app, mock_session_manager, mock_model_gateway,
    ):
        """Test health response includes component details."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = mock_model_gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        components = {c["name"]: c for c in data["components"]}

        assert "redis" in components
        assert components["redis"]["status"] == "healthy"

        assert "llm_gateway" in components
        assert components["llm_gateway"]["status"] == "healthy"

    def test_health_returns_degraded_when_gateway_unhealthy(
        self, client, app, mock_session_manager,
    ):
        """Test health returns degraded when gateway is unhealthy."""
        app.state.session_manager = mock_session_manager

        # Mock unhealthy gateway
        unhealthy_gateway = AsyncMock()
        unhealthy_gateway.health_check = AsyncMock(
            return_value={"llama": {"status": "unhealthy"}},
        )
        app.state.model_gateway = unhealthy_gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        # Should be degraded since one component is not fully healthy
        assert data["status"] in ["degraded", "unhealthy"]

    def test_health_returns_unknown_for_uninitialized_components(self, client, app):
        """Test health returns unknown for uninitialized components."""
        # No services initialized
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        components = {c["name"]: c for c in data["components"]}

        assert components["redis"]["status"] == "unknown"
        assert components["llm_gateway"]["status"] == "unknown"

    def test_health_calculates_uptime_correctly(
        self, client, app, mock_session_manager, mock_model_gateway,
    ):
        """Test health correctly calculates uptime."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = mock_model_gateway
        app.state.start_time = time.time() - 60  # Started 60 seconds ago

        response = client.get("/health")

        data = response.json()
        # Uptime should be approximately 60 seconds
        assert data["uptime_seconds"] >= 59
        assert data["uptime_seconds"] < 65

    def test_health_includes_latency_measurements(
        self, client, app, mock_session_manager, mock_model_gateway,
    ):
        """Test health includes latency measurements for components."""
        app.state.session_manager = mock_session_manager
        app.state.model_gateway = mock_model_gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        components = {c["name"]: c for c in data["components"]}

        # Both healthy components should have latency measurements
        assert "latency_ms" in components["redis"]
        assert components["redis"]["latency_ms"] is not None

        assert "latency_ms" in components["llm_gateway"]
        assert components["llm_gateway"]["latency_ms"] is not None

    def test_health_handles_redis_connection_error(self, client, app, mock_model_gateway):
        """Test health handles Redis connection errors gracefully."""
        manager = MagicMock()
        manager.store = MagicMock()
        manager.store._redis = AsyncMock()
        manager.store._redis.ping = AsyncMock(
            side_effect=Exception("Connection refused"),
        )

        app.state.session_manager = manager
        app.state.model_gateway = mock_model_gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        components = {c["name"]: c for c in data["components"]}

        assert components["redis"]["status"] == "unhealthy"
        assert "Connection refused" in components["redis"]["message"]

    def test_health_handles_gateway_error(self, client, app, mock_session_manager):
        """Test health handles gateway errors gracefully."""
        gateway = AsyncMock()
        gateway.health_check = AsyncMock(side_effect=Exception("Gateway timeout"))

        app.state.session_manager = mock_session_manager
        app.state.model_gateway = gateway
        app.state.start_time = time.time()

        response = client.get("/health")

        data = response.json()
        components = {c["name"]: c for c in data["components"]}

        assert components["llm_gateway"]["status"] == "unhealthy"
        assert "Gateway timeout" in components["llm_gateway"]["message"]
