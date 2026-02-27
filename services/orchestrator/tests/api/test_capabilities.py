"""Tests for the capability discovery endpoint."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.routes.capabilities import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create test FastAPI application with the capabilities router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestCapabilitiesEndpoint:
    """Tests for GET /api/v1/capabilities."""

    def test_returns_200_with_schema_version(self, client, app):
        """Endpoint always returns 200 with a version field."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] == "1"

    def test_returns_features_dict(self, client, app):
        """Endpoint returns a features dictionary."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        data = response.json()
        assert "features" in data
        assert isinstance(data["features"], dict)

    def test_all_expected_feature_keys_present(self, client, app):
        """Endpoint returns all documented feature keys."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        data = response.json()
        expected_keys = {
            "streaming",
            "reranker",
            "llm",
            "workflow",
            "video_search",
            "query_expansion",
            "guardrails",
            "answer_verification",
            "session_memory",
            "feedback",
        }
        assert expected_keys == set(data["features"].keys())

    def test_all_feature_values_are_booleans(self, client, app):
        """Every feature value must be a boolean."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        data = response.json()
        for key, value in data["features"].items():
            assert isinstance(value, bool), f"Feature '{key}' is {type(value)}, expected bool"

    def test_video_search_always_false(self, client, app):
        """Video search is hardcoded to False (not production-ready)."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["video_search"] is False

    def test_query_expansion_always_false(self, client, app):
        """Query expansion is hardcoded to False (not implemented)."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["query_expansion"] is False

    def test_feedback_always_true(self, client, app):
        """Feedback is always available (DB-backed, no runtime dependency)."""
        app.state.start_time = time.time()

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["feedback"] is True

    def test_streaming_enabled_when_stream_manager_and_llm_available(self, client, app):
        """Streaming is True when stream_manager is initialised and LLM is healthy."""
        app.state.stream_manager = MagicMock()
        app.state.model_gateway = AsyncMock()
        app.state.model_gateway.health_check = AsyncMock(
            return_value={"llama": MagicMock(status="healthy")},
        )
        # Other state
        app.state.retrieval_client = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["streaming"] is True

    def test_streaming_disabled_when_no_stream_manager(self, client, app):
        """Streaming is False when stream_manager is not initialised."""
        app.state.stream_manager = None
        app.state.model_gateway = AsyncMock()
        app.state.model_gateway.health_check = AsyncMock(
            return_value={"llama": MagicMock(status="healthy")},
        )

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["streaming"] is False

    def test_streaming_disabled_when_llm_unhealthy(self, client, app):
        """Streaming is False when LLM gateway is unreachable."""
        app.state.stream_manager = MagicMock()
        app.state.model_gateway = AsyncMock()
        app.state.model_gateway.health_check = AsyncMock(
            side_effect=Exception("Connection refused"),
        )
        app.state.retrieval_client = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["streaming"] is False

    def test_reranker_enabled_when_retrieval_healthy(self, client, app):
        """Reranker is True when retrieval service health check passes."""
        retrieval_client = AsyncMock()
        retrieval_client.health_check = AsyncMock(
            return_value={"status": "healthy"},
        )
        app.state.retrieval_client = retrieval_client
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["reranker"] is True

    def test_reranker_disabled_when_retrieval_unavailable(self, client, app):
        """Reranker is False when retrieval client is None."""
        app.state.retrieval_client = None
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["reranker"] is False

    def test_reranker_disabled_when_retrieval_health_fails(self, client, app):
        """Reranker is False when retrieval health check throws."""
        retrieval_client = AsyncMock()
        retrieval_client.health_check = AsyncMock(
            side_effect=Exception("Connection refused"),
        )
        app.state.retrieval_client = retrieval_client
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["reranker"] is False

    def test_guardrails_enabled_when_pipeline_initialized(self, client, app):
        """Guardrails is True when guardrail pipeline is set."""
        app.state.guardrail_pipeline = MagicMock()
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.retrieval_client = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["guardrails"] is True

    def test_guardrails_disabled_when_pipeline_not_initialized(self, client, app):
        """Guardrails is False when guardrail pipeline is None."""
        app.state.guardrail_pipeline = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["guardrails"] is False

    def test_session_memory_enabled_when_manager_initialized(self, client, app):
        """Session memory is True when session manager is set."""
        app.state.session_manager = MagicMock()
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.retrieval_client = None
        app.state.guardrail_pipeline = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["session_memory"] is True

    def test_session_memory_disabled_when_manager_not_initialized(self, client, app):
        """Session memory is False when session manager is None."""
        app.state.session_manager = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["session_memory"] is False

    def test_workflow_enabled_when_initialized(self, client, app):
        """Workflow is True when RAG workflow is set."""
        app.state.workflow = MagicMock()
        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.retrieval_client = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["workflow"] is True

    def test_workflow_disabled_when_not_initialized(self, client, app):
        """Workflow is False when RAG workflow is None."""
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["workflow"] is False

    @patch("config.get_config")
    def test_answer_verification_reflects_config(self, mock_get_config, client, app):
        """answer_verification mirrors the config flag."""
        mock_config = MagicMock()
        mock_config.verification_enabled = True
        mock_get_config.return_value = mock_config

        app.state.model_gateway = None
        app.state.stream_manager = None
        app.state.retrieval_client = None
        app.state.guardrail_pipeline = None
        app.state.session_manager = None
        app.state.workflow = None

        response = client.get("/api/v1/capabilities")

        assert response.json()["features"]["answer_verification"] is True

    def test_conservative_defaults_when_nothing_initialized(self, client, app):
        """When no services are initialised, most features should be False."""
        # Don't set any app state at all
        response = client.get("/api/v1/capabilities")

        data = response.json()
        features = data["features"]

        # Only feedback should be True by default
        assert features["feedback"] is True
        assert features["streaming"] is False
        assert features["reranker"] is False
        assert features["llm"] is False
        assert features["video_search"] is False
        assert features["query_expansion"] is False
