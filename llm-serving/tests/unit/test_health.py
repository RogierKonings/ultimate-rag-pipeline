"""
Unit tests for Health Checking (US-5.6).

Tests health checkers for vLLM, embedding, and reranker services.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monitoring.health import (
    EmbeddingHealthChecker,
    HealthChecker,
    RerankerHealthChecker,
    VLLMHealthChecker,
)
from monitoring.models import ComponentHealth, HealthStatus, ServiceHealth


class TestHealthChecker:
    """Tests for base HealthChecker."""

    @pytest.fixture
    def health_checker(self):
        """Create a basic health checker."""
        return HealthChecker(service_name="test-service", model_name="test-model")

    def test_initialization(self, health_checker):
        """Test health checker initialization."""
        assert health_checker.service_name == "test-service"
        assert health_checker.model_name == "test-model"
        assert health_checker._is_model_loaded is False
        assert health_checker._running is False

    def test_liveness_check(self, health_checker):
        """Test liveness check always returns True."""
        assert health_checker.liveness_check() is True

    def test_readiness_check_model_not_loaded(self, health_checker):
        """Test readiness check when model not loaded."""
        assert health_checker.readiness_check() is False

    def test_readiness_check_model_loaded(self, health_checker):
        """Test readiness check when model loaded."""
        health_checker.set_model_loaded(True)
        assert health_checker.readiness_check() is True

    def test_set_model_loaded(self, health_checker):
        """Test setting model loaded status."""
        health_checker.set_model_loaded(True)
        assert health_checker._is_model_loaded is True

        health_checker.set_model_loaded(False)
        assert health_checker._is_model_loaded is False

    def test_record_request(self, health_checker):
        """Test recording a request."""
        assert health_checker._last_request_time is None

        health_checker.record_request()

        assert health_checker._last_request_time is not None
        assert isinstance(health_checker._last_request_time, datetime)

    def test_register_component(self, health_checker):
        """Test registering a component check."""

        def check_fn():
            return ComponentHealth(
                name="custom", status=HealthStatus.HEALTHY, message="OK",
            )

        health_checker.register_component("custom", check_fn)

        assert "custom" in health_checker._components
        assert health_checker._components["custom"] == check_fn

    def test_unregister_component(self, health_checker):
        """Test unregistering a component check."""
        health_checker.register_component("custom", lambda: None)
        health_checker.unregister_component("custom")

        assert "custom" not in health_checker._components

    def test_get_last_health_none(self, health_checker):
        """Test get_last_health when no checks run."""
        assert health_checker.get_last_health() is None

    @pytest.mark.asyncio
    async def test_start_stop(self, health_checker):
        """Test starting and stopping health checker."""
        await health_checker.start()
        assert health_checker.is_running() is True

        await health_checker.stop()
        assert health_checker.is_running() is False

    @pytest.mark.asyncio
    async def test_run_checks_model_not_loaded(self, health_checker):
        """Test running checks when model not loaded."""
        health = await health_checker.run_checks()

        assert isinstance(health, ServiceHealth)
        assert health.service_name == "test-service"
        assert health.model_loaded is False

        # Model component should be unhealthy
        model_component = next((c for c in health.components if c.name == "model"), None)
        assert model_component is not None
        assert model_component.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_run_checks_model_loaded(self, health_checker):
        """Test running checks when model loaded."""
        health_checker.set_model_loaded(True)

        health = await health_checker.run_checks()

        assert health.model_loaded is True

        # Model component should be healthy
        model_component = next((c for c in health.components if c.name == "model"), None)
        assert model_component is not None
        assert model_component.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_run_checks_with_custom_component(self, health_checker):
        """Test running checks with custom component."""

        def custom_check():
            return ComponentHealth(
                name="database", status=HealthStatus.HEALTHY, message="Connected",
            )

        health_checker.register_component("database", custom_check)

        health = await health_checker.run_checks()

        db_component = next((c for c in health.components if c.name == "database"), None)
        assert db_component is not None
        assert db_component.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_run_checks_custom_component_failure(self, health_checker):
        """Test running checks with failing custom component."""

        def failing_check():
            raise Exception("Connection failed")

        health_checker.register_component("database", failing_check)
        health_checker.set_model_loaded(True)  # Model is healthy

        health = await health_checker.run_checks()

        # Overall status should be degraded due to component failure
        assert health.status == HealthStatus.DEGRADED

        db_component = next((c for c in health.components if c.name == "database"), None)
        assert db_component is not None
        assert db_component.status == HealthStatus.UNHEALTHY
        assert "Connection failed" in db_component.message


class TestVLLMHealthChecker:
    """Tests for VLLMHealthChecker."""

    @pytest.fixture
    def vllm_checker(self):
        """Create a vLLM health checker."""
        return VLLMHealthChecker(
            vllm_url="http://localhost:8000", model_name="test-llm",
        )

    def test_initialization(self, vllm_checker):
        """Test vLLM health checker initialization."""
        assert vllm_checker.service_name == "vllm"
        assert vllm_checker.vllm_url == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_check_model_success(self, vllm_checker):
        """Test successful model check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "qwen2.5-7b-instruct"}],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await vllm_checker._check_model()

        assert health.status == HealthStatus.HEALTHY
        assert vllm_checker._is_model_loaded is True
        assert vllm_checker.model_name == "qwen2.5-7b-instruct"

    @pytest.mark.asyncio
    async def test_check_model_no_models(self, vllm_checker):
        """Test model check when no models loaded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await vllm_checker._check_model()

        assert health.status == HealthStatus.UNHEALTHY
        assert vllm_checker._is_model_loaded is False

    @pytest.mark.asyncio
    async def test_check_model_connection_error(self, vllm_checker):
        """Test model check with connection error."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await vllm_checker._check_model()

        assert health.status == HealthStatus.UNHEALTHY
        assert "Cannot connect" in health.message


class TestEmbeddingHealthChecker:
    """Tests for EmbeddingHealthChecker."""

    @pytest.fixture
    def embedding_checker(self):
        """Create an embedding health checker."""
        return EmbeddingHealthChecker(
            embedding_url="http://localhost:8001", model_name="bge-large",
        )

    def test_initialization(self, embedding_checker):
        """Test embedding health checker initialization."""
        assert embedding_checker.service_name == "embedding"
        assert embedding_checker.embedding_url == "http://localhost:8001"

    @pytest.mark.asyncio
    async def test_check_model_success(self, embedding_checker):
        """Test successful model check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model_loaded": True,
            "embedding_dim": 1024,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await embedding_checker._check_model()

        assert health.status == HealthStatus.HEALTHY
        assert embedding_checker._is_model_loaded is True
        assert health.details["embedding_dim"] == 1024

    @pytest.mark.asyncio
    async def test_check_model_not_loaded(self, embedding_checker):
        """Test model check when not loaded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"model_loaded": False}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await embedding_checker._check_model()

        assert health.status == HealthStatus.UNHEALTHY
        assert embedding_checker._is_model_loaded is False


class TestRerankerHealthChecker:
    """Tests for RerankerHealthChecker."""

    @pytest.fixture
    def reranker_checker(self):
        """Create a reranker health checker."""
        return RerankerHealthChecker(
            reranker_url="http://localhost:8002", model_name="bge-reranker",
        )

    def test_initialization(self, reranker_checker):
        """Test reranker health checker initialization."""
        assert reranker_checker.service_name == "reranker"
        assert reranker_checker.reranker_url == "http://localhost:8002"

    @pytest.mark.asyncio
    async def test_check_model_success(self, reranker_checker):
        """Test successful model check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"model_loaded": True}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            health = await reranker_checker._check_model()

        assert health.status == HealthStatus.HEALTHY
        assert reranker_checker._is_model_loaded is True
