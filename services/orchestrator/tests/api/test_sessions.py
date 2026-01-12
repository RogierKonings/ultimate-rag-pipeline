"""Tests for session management endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.routes.sessions import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memory.models import ConversationSession, Message, MessageRole


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
def sample_session():
    """Create a sample session for testing."""
    session_id = uuid4()
    user_id = uuid4()
    tenant_id = uuid4()
    now = datetime.now(tz=UTC)

    return ConversationSession(
        id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        messages=[
            Message(
                id=uuid4(),
                role=MessageRole.USER,
                content="Hello, how are you?",
                timestamp=now,
            ),
            Message(
                id=uuid4(),
                role=MessageRole.ASSISTANT,
                content="I'm doing well, thank you!",
                timestamp=now,
                sources=["doc1.md", "doc2.md"],
            ),
        ],
        created_at=now,
        updated_at=now,
        last_activity=now,
        total_messages=2,
        total_tokens=50,
    )


@pytest.fixture
def mock_session_manager(sample_session):
    """Create mock session manager."""
    manager = AsyncMock()
    manager.create_session = AsyncMock(return_value=sample_session)
    manager.get_session = AsyncMock(return_value=sample_session)
    manager.delete_session = AsyncMock(return_value=True)
    manager.clear_session = AsyncMock(return_value=True)
    return manager


class TestCreateSession:
    """Tests for POST /api/v1/sessions endpoint."""

    def test_create_session_success(self, client, app, mock_session_manager):
        """Test successful session creation."""
        app.state.session_manager = mock_session_manager

        response = client.post(
            "/api/v1/sessions",
            json={},
        )

        assert response.status_code == 201
        data = response.json()
        assert "session" in data
        assert "id" in data["session"]
        assert data["message"] == "Session created successfully"

    def test_create_session_with_user_and_tenant(
        self, client, app, mock_session_manager,
    ):
        """Test session creation with user_id and tenant_id."""
        app.state.session_manager = mock_session_manager
        user_id = str(uuid4())
        tenant_id = str(uuid4())

        response = client.post(
            "/api/v1/sessions",
            json={
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        )

        assert response.status_code == 201
        mock_session_manager.create_session.assert_called_once()
        call_kwargs = mock_session_manager.create_session.call_args.kwargs
        assert str(call_kwargs["user_id"]) == user_id
        assert str(call_kwargs["tenant_id"]) == tenant_id

    def test_create_session_with_system_prompt(self, client, app, mock_session_manager):
        """Test session creation with custom system prompt."""
        app.state.session_manager = mock_session_manager
        system_prompt = "You are a helpful assistant."

        response = client.post(
            "/api/v1/sessions",
            json={"system_prompt": system_prompt},
        )

        assert response.status_code == 201
        mock_session_manager.create_session.assert_called_once()
        call_kwargs = mock_session_manager.create_session.call_args.kwargs
        assert call_kwargs["system_prompt"] == system_prompt

    def test_create_session_service_unavailable(self, client, app):
        """Test session creation when service is unavailable."""
        # No session_manager set on app.state
        response = client.post(
            "/api/v1/sessions",
            json={},
        )

        assert response.status_code == 503
        assert "Session manager not available" in response.json()["detail"]


class TestGetSession:
    """Tests for GET /api/v1/sessions/{id} endpoint."""

    def test_get_session_success(self, client, app, mock_session_manager, sample_session):
        """Test successful session retrieval."""
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{sample_session.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["session"]["id"] == str(sample_session.id)
        assert data["session"]["message_count"] == 2
        assert data["session"]["total_tokens"] == 50

    def test_get_session_not_found(self, client, app, mock_session_manager):
        """Test session retrieval when session doesn't exist."""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        app.state.session_manager = mock_session_manager

        session_id = uuid4()
        response = client.get(f"/api/v1/sessions/{session_id}")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_get_session_invalid_uuid(self, client, app, mock_session_manager):
        """Test session retrieval with invalid UUID."""
        app.state.session_manager = mock_session_manager

        response = client.get("/api/v1/sessions/invalid-uuid")

        assert response.status_code == 422  # Validation error

    def test_get_session_service_unavailable(self, client, app):
        """Test session retrieval when service is unavailable."""
        session_id = uuid4()
        response = client.get(f"/api/v1/sessions/{session_id}")

        assert response.status_code == 503


class TestGetSessionHistory:
    """Tests for GET /api/v1/sessions/{id}/history endpoint."""

    def test_get_history_success(self, client, app, mock_session_manager, sample_session):
        """Test successful history retrieval."""
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{sample_session.id}/history")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == str(sample_session.id)
        assert len(data["messages"]) == 2

        # Check message structure
        user_msg = data["messages"][0]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "Hello, how are you?"

        assistant_msg = data["messages"][1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "I'm doing well, thank you!"
        assert assistant_msg["sources"] == ["doc1.md", "doc2.md"]

    def test_get_history_with_summary(self, client, app, mock_session_manager):
        """Test history retrieval when session has summary."""
        session = ConversationSession(
            id=uuid4(),
            messages=[],
            summary="Previous conversation about Python.",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        mock_session_manager.get_session = AsyncMock(return_value=session)
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{session.id}/history")

        assert response.status_code == 200
        data = response.json()
        assert data["has_summary"] is True
        assert data["summary"] == "Previous conversation about Python."

    def test_get_history_not_found(self, client, app, mock_session_manager):
        """Test history retrieval when session doesn't exist."""
        mock_session_manager.get_session = AsyncMock(return_value=None)
        app.state.session_manager = mock_session_manager

        session_id = uuid4()
        response = client.get(f"/api/v1/sessions/{session_id}/history")

        assert response.status_code == 404

    def test_get_history_empty_session(self, client, app, mock_session_manager):
        """Test history retrieval for session with no messages."""
        session = ConversationSession(
            id=uuid4(),
            messages=[],
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        mock_session_manager.get_session = AsyncMock(return_value=session)
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{session.id}/history")

        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 0
        assert data["has_summary"] is False


class TestDeleteSession:
    """Tests for DELETE /api/v1/sessions/{id} endpoint."""

    def test_delete_session_success(
        self, client, app, mock_session_manager, sample_session,
    ):
        """Test successful session deletion."""
        app.state.session_manager = mock_session_manager

        response = client.delete(f"/api/v1/sessions/{sample_session.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == str(sample_session.id)
        assert data["message"] == "Session deleted successfully"

    def test_delete_session_not_found(self, client, app, mock_session_manager):
        """Test session deletion when session doesn't exist."""
        mock_session_manager.delete_session = AsyncMock(return_value=False)
        app.state.session_manager = mock_session_manager

        session_id = uuid4()
        response = client.delete(f"/api/v1/sessions/{session_id}")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_delete_session_service_unavailable(self, client, app):
        """Test session deletion when service is unavailable."""
        session_id = uuid4()
        response = client.delete(f"/api/v1/sessions/{session_id}")

        assert response.status_code == 503


class TestClearSession:
    """Tests for POST /api/v1/sessions/{id}/clear endpoint."""

    def test_clear_session_success(
        self, client, app, mock_session_manager, sample_session,
    ):
        """Test successful session clearing."""
        app.state.session_manager = mock_session_manager

        response = client.post(f"/api/v1/sessions/{sample_session.id}/clear")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["session_id"] == str(sample_session.id)
        assert data["message"] == "Session cleared successfully"

    def test_clear_session_not_found(self, client, app, mock_session_manager):
        """Test session clearing when session doesn't exist."""
        mock_session_manager.clear_session = AsyncMock(return_value=False)
        app.state.session_manager = mock_session_manager

        session_id = uuid4()
        response = client.post(f"/api/v1/sessions/{session_id}/clear")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_clear_session_service_unavailable(self, client, app):
        """Test session clearing when service is unavailable."""
        session_id = uuid4()
        response = client.post(f"/api/v1/sessions/{session_id}/clear")

        assert response.status_code == 503

    def test_clear_session_verifies_clear_was_called(
        self, client, app, mock_session_manager, sample_session,
    ):
        """Test that clear_session is called with correct arguments."""
        app.state.session_manager = mock_session_manager

        client.post(f"/api/v1/sessions/{sample_session.id}/clear")

        mock_session_manager.clear_session.assert_called_once_with(sample_session.id)


class TestSessionResponseModel:
    """Tests for session response model structure."""

    def test_session_response_includes_all_fields(
        self, client, app, mock_session_manager, sample_session,
    ):
        """Test that session response includes all expected fields."""
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{sample_session.id}")

        data = response.json()
        session = data["session"]

        assert "id" in session
        assert "user_id" in session
        assert "tenant_id" in session
        assert "created_at" in session
        assert "updated_at" in session
        assert "message_count" in session
        assert "total_tokens" in session

    def test_session_response_datetime_format(
        self, client, app, mock_session_manager, sample_session,
    ):
        """Test that datetime fields are properly formatted."""
        app.state.session_manager = mock_session_manager

        response = client.get(f"/api/v1/sessions/{sample_session.id}")

        data = response.json()
        session = data["session"]

        # Datetime should be ISO format
        created_at = datetime.fromisoformat(session["created_at"].replace("Z", "+00:00"))
        assert created_at is not None
