"""Test fixtures for API tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient


@pytest.fixture
def settings():
    """Test settings."""
    from config import Settings

    return Settings(
        jwt_secret="test-secret-key",
        jwt_algorithm="HS256",
        debug=True,
    )


@pytest.fixture
def app(settings):
    """Create test FastAPI app."""
    from api.main import create_app

    return create_app(settings)


@pytest.fixture
def mock_current_user():
    """Mock user returned by get_current_user."""
    return {
        "sub": "user-123",
        "tenant_id": "tenant-123",
        "groups": ["group-1"],
        "roles": ["user"],
        "permissions": ["read:documents", "write:documents"],
    }


@pytest.fixture
def client(app, mock_current_user):
    """Test client for API with auth dependency override."""
    from api.dependencies import get_current_user

    async def mock_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = mock_get_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth(app):
    """Test client without auth - for testing 401 responses."""
    return TestClient(app)


@pytest.fixture
def auth_token(settings):
    """Generate valid JWT token for testing (for 401 tests without override)."""
    return jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": "tenant-123",
            "groups": ["group-1"],
            "roles": ["user"],
            "permissions": ["read:documents", "write:documents"],
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest.fixture
def auth_headers(auth_token):
    """Authorization headers with valid token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def mock_job_tracker():
    """Mock JobStatusTracker."""
    tracker = AsyncMock()
    tracker.connect = AsyncMock()
    tracker.disconnect = AsyncMock()
    tracker.get_job_status = AsyncMock()
    tracker.cancel_job = AsyncMock(return_value=True)
    tracker.list_active_jobs = AsyncMock(return_value=[])
    return tracker


@pytest.fixture
def client_with_job_tracker(app, mock_current_user, mock_job_tracker):
    """Test client with both auth and job_tracker dependency overrides."""
    from api.dependencies import get_current_user, get_job_tracker

    async def mock_get_current_user():
        return mock_current_user

    async def mock_get_job_tracker():
        yield mock_job_tracker

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_job_tracker] = mock_get_job_tracker
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_job_tracker_no_auth(app, mock_job_tracker):
    """Test client with job_tracker override but WITHOUT auth override (for 401 tests)."""
    from api.dependencies import get_job_tracker

    async def mock_get_job_tracker():
        yield mock_job_tracker

    app.dependency_overrides[get_job_tracker] = mock_get_job_tracker
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mock_document_service():
    """Mock DocumentService."""
    service = AsyncMock()
    service.connect = AsyncMock()
    service.disconnect = AsyncMock()
    service.list_documents = AsyncMock()
    service.get_document = AsyncMock()
    service.delete_document = AsyncMock()
    service.reindex_document = AsyncMock()
    return service


@pytest.fixture
def sample_document_response():
    """Sample document response for testing."""
    from datetime import datetime

    from api.schemas import DocumentResponse

    return DocumentResponse(
        document_id=uuid4(),
        source_id="test-doc-001",
        source_type="filesystem",
        filename="test.pdf",
        mime_type="application/pdf",
        title="Test Document",
        author="Test Author",
        chunk_count=10,
        total_tokens=1500,
        tenant_id="tenant-123",
        visibility="private",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        indexed_at=datetime.utcnow(),
        status="indexed",
    )


@pytest.fixture
def sample_job_result():
    """Sample job result for testing."""
    from tasks.models import IngestJobResult, JobProgress, JobStatus

    return IngestJobResult(
        job_id=str(uuid4()),
        status=JobStatus.PROGRESS,
        progress=JobProgress(current=5, total=10, stage="embedding"),
        documents_processed=5,
        chunks_created=50,
    )
