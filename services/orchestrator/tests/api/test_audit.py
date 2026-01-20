"""Tests for audit API endpoints.

Reference: US-10.7.5 - Comprehensive Audit Logging
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from api.routes.audit import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.shared.security.audit.models import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditSeverity,
    AuditStats,
)


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def sample_tenant_id():
    """Sample tenant ID for tests."""
    return uuid4()


@pytest.fixture
def sample_audit_entries(sample_tenant_id):
    """Create sample audit log entries."""
    now = datetime.now(UTC)
    entries = []

    for i in range(5):
        entry = AuditLogEntry(
            id=uuid4(),
            timestamp=now - timedelta(hours=i),
            tenant_id=sample_tenant_id,
            user_id=uuid4(),
            username=f"user{i}@example.com",
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            resource_type="document",
            resource_id=str(uuid4()),
            client_ip="192.168.1.1",
            request_method="GET",
            request_path=f"/api/v1/documents/{i}",
            status_code=200,
            entry_hash=f"hash_{i}" if i == 0 else f"hash_{i}",
            previous_hash=None if i == 0 else f"hash_{i - 1}",
        )
        entries.append(entry)

    return entries


class TestQueryAuditLogs:
    """Tests for GET /api/v1/audit/logs."""

    @pytest.mark.asyncio
    async def test_query_returns_entries(
        self, mock_db_session, sample_audit_entries, sample_tenant_id
    ):
        """Test that query returns audit entries."""
        from api.routes.audit import query_audit_logs

        # Mock the repository search
        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=sample_audit_entries)
            MockRepo.return_value = mock_repo

            response = await query_audit_logs(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert len(response.events) == 5
            assert response.limit == 100
            assert response.offset == 0
            mock_repo.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_with_filters(
        self, mock_db_session, sample_audit_entries, sample_tenant_id
    ):
        """Test query with various filters."""
        from api.routes.audit import query_audit_logs

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=sample_audit_entries[:2])
            MockRepo.return_value = mock_repo

            user_id = uuid4()
            response = await query_audit_logs(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
                user_id=user_id,
                action=AuditAction.DOCUMENT_READ,
                outcome=AuditOutcome.SUCCESS,
                severity=AuditSeverity.INFO,
                resource_type="document",
                limit=50,
                offset=10,
            )

            assert len(response.events) == 2
            assert response.limit == 50
            assert response.offset == 10

            # Verify the query was called with correct parameters
            call_args = mock_repo.search.call_args[0][0]
            assert call_args.tenant_id == sample_tenant_id
            assert call_args.user_id == user_id
            assert call_args.actions == [AuditAction.DOCUMENT_READ]
            assert call_args.outcomes == [AuditOutcome.SUCCESS]
            assert call_args.severities == [AuditSeverity.INFO]
            assert call_args.resource_type == "document"
            assert call_args.limit == 50
            assert call_args.offset == 10

    @pytest.mark.asyncio
    async def test_query_with_time_range(
        self, mock_db_session, sample_audit_entries, sample_tenant_id
    ):
        """Test query with time range filters."""
        from api.routes.audit import query_audit_logs

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=sample_audit_entries[:3])
            MockRepo.return_value = mock_repo

            start_time = datetime.now(UTC) - timedelta(days=1)
            end_time = datetime.now(UTC)

            await query_audit_logs(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
                start_time=start_time,
                end_time=end_time,
            )

            call_args = mock_repo.search.call_args[0][0]
            assert call_args.start_time == start_time
            assert call_args.end_time == end_time

    @pytest.mark.asyncio
    async def test_query_requires_tenant_id(self, client):
        """Test that tenant_id is required for queries."""
        response = client.get("/api/v1/audit/logs")
        assert response.status_code == 422  # Validation error


class TestGetAuditLogEntry:
    """Tests for GET /api/v1/audit/logs/{entry_id}."""

    @pytest.mark.asyncio
    async def test_get_entry_by_id(self, mock_db_session, sample_audit_entries, sample_tenant_id):
        """Test getting a single entry by ID."""
        from api.routes.audit import get_audit_log_entry

        entry = sample_audit_entries[0]

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=entry)
            MockRepo.return_value = mock_repo

            result = await get_audit_log_entry(
                entry_id=entry.id,
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert result.id == entry.id
            assert result.action == entry.action

    @pytest.mark.asyncio
    async def test_get_entry_not_found(self, mock_db_session, sample_tenant_id):
        """Test 404 when entry not found."""
        from api.routes.audit import get_audit_log_entry
        from fastapi import HTTPException

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=None)
            MockRepo.return_value = mock_repo

            with pytest.raises(HTTPException) as exc_info:
                await get_audit_log_entry(
                    entry_id=uuid4(),
                    tenant_id=sample_tenant_id,
                    db=mock_db_session,
                )

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_entry_tenant_mismatch(
        self, mock_db_session, sample_audit_entries, sample_tenant_id
    ):
        """Test 404 when entry exists but tenant doesn't match."""
        from api.routes.audit import get_audit_log_entry
        from fastapi import HTTPException

        entry = sample_audit_entries[0]
        different_tenant = uuid4()

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_by_id = AsyncMock(return_value=entry)
            MockRepo.return_value = mock_repo

            with pytest.raises(HTTPException) as exc_info:
                await get_audit_log_entry(
                    entry_id=entry.id,
                    tenant_id=different_tenant,  # Different tenant
                    db=mock_db_session,
                )

            assert exc_info.value.status_code == 404


class TestGetAuditStats:
    """Tests for GET /api/v1/audit/stats."""

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_db_session, sample_tenant_id):
        """Test getting audit statistics."""
        from api.routes.audit import get_audit_stats

        mock_stats = AuditStats(
            total_entries=100,
            entries_by_action={"document.read": 50, "document.create": 30, "auth.login": 20},
            entries_by_outcome={"success": 90, "failure": 10},
            entries_by_severity={"info": 85, "warning": 10, "error": 5},
            unique_users=15,
            unique_resources=25,
        )

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_stats = AsyncMock(return_value=mock_stats)
            MockRepo.return_value = mock_repo

            result = await get_audit_stats(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert result.total_entries == 100
            assert result.unique_users == 15
            mock_repo.get_stats.assert_called_once_with(
                tenant_id=sample_tenant_id,
                start_time=None,
                end_time=None,
            )

    @pytest.mark.asyncio
    async def test_get_stats_with_time_range(self, mock_db_session, sample_tenant_id):
        """Test getting stats with time range."""
        from api.routes.audit import get_audit_stats

        mock_stats = AuditStats(
            total_entries=50,
            entries_by_action={},
            entries_by_outcome={},
            entries_by_severity={},
            unique_users=5,
            unique_resources=10,
            time_range_start=datetime.now(UTC) - timedelta(days=7),
            time_range_end=datetime.now(UTC),
        )

        start_time = datetime.now(UTC) - timedelta(days=7)
        end_time = datetime.now(UTC)

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_stats = AsyncMock(return_value=mock_stats)
            MockRepo.return_value = mock_repo

            await get_audit_stats(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
                start_time=start_time,
                end_time=end_time,
            )

            mock_repo.get_stats.assert_called_once_with(
                tenant_id=sample_tenant_id,
                start_time=start_time,
                end_time=end_time,
            )


class TestExportAuditLogs:
    """Tests for GET /api/v1/audit/export."""

    @pytest.mark.asyncio
    async def test_json_export(self, mock_db_session, sample_audit_entries, sample_tenant_id):
        """Test JSON export of audit logs."""
        from api.routes.audit import export_audit_logs

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=sample_audit_entries)
            MockRepo.return_value = mock_repo

            start_time = datetime.now(UTC) - timedelta(days=7)
            end_time = datetime.now(UTC)

            response = await export_audit_logs(
                tenant_id=sample_tenant_id,
                start_time=start_time,
                end_time=end_time,
                db=mock_db_session,
                format="json",
                include_details=False,
            )

            assert response.total_entries == 5
            assert response.format == "json"
            assert len(response.entries) == 5

    @pytest.mark.asyncio
    async def test_csv_export(self, mock_db_session, sample_audit_entries, sample_tenant_id):
        """Test CSV export returns StreamingResponse."""
        from api.routes.audit import export_audit_logs
        from fastapi.responses import StreamingResponse

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=sample_audit_entries)
            MockRepo.return_value = mock_repo

            start_time = datetime.now(UTC) - timedelta(days=7)
            end_time = datetime.now(UTC)

            response = await export_audit_logs(
                tenant_id=sample_tenant_id,
                start_time=start_time,
                end_time=end_time,
                db=mock_db_session,
                format="csv",
            )

            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/csv"

    @pytest.mark.asyncio
    async def test_export_time_range_limit(self, mock_db_session, sample_tenant_id):
        """Test that export fails for time range exceeding 90 days."""
        from api.routes.audit import export_audit_logs
        from fastapi import HTTPException

        start_time = datetime.now(UTC) - timedelta(days=100)
        end_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await export_audit_logs(
                tenant_id=sample_tenant_id,
                start_time=start_time,
                end_time=end_time,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 400
        assert "90 days" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, mock_db_session, sample_tenant_id):
        """Test that export fails for invalid format."""
        from api.routes.audit import export_audit_logs
        from fastapi import HTTPException

        start_time = datetime.now(UTC) - timedelta(days=7)
        end_time = datetime.now(UTC)

        with pytest.raises(HTTPException) as exc_info:
            await export_audit_logs(
                tenant_id=sample_tenant_id,
                start_time=start_time,
                end_time=end_time,
                db=mock_db_session,
                format="xml",  # Invalid format
            )

        assert exc_info.value.status_code == 400
        assert (
            "json" in str(exc_info.value.detail).lower()
            or "csv" in str(exc_info.value.detail).lower()
        )


class TestValidateHashChain:
    """Tests for GET /api/v1/audit/validate-chain."""

    @pytest.mark.asyncio
    async def test_validate_chain_valid(self, mock_db_session, sample_tenant_id):
        """Test hash chain validation with valid chain."""
        from api.routes.audit import validate_hash_chain

        # Create entries with valid hash chain
        entries = []
        previous_hash = None
        for i in range(3):
            entry = AuditLogEntry(
                id=uuid4(),
                timestamp=datetime.now(UTC) + timedelta(seconds=i),
                tenant_id=sample_tenant_id,
                action=AuditAction.DOCUMENT_READ,
                outcome=AuditOutcome.SUCCESS,
                severity=AuditSeverity.INFO,
                previous_hash=previous_hash,
            )
            entry.entry_hash = entry.compute_hash(previous_hash)
            previous_hash = entry.entry_hash
            entries.append(entry)

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=entries)
            MockRepo.return_value = mock_repo

            result = await validate_hash_chain(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert result.valid is True
            assert result.error is None
            assert result.entries_checked == 3

    @pytest.mark.asyncio
    async def test_validate_chain_broken(self, mock_db_session, sample_tenant_id):
        """Test hash chain validation with broken chain."""
        from api.routes.audit import validate_hash_chain

        # Create entries with broken hash chain (wrong previous_hash)
        entries = []
        for i in range(3):
            entry = AuditLogEntry(
                id=uuid4(),
                timestamp=datetime.now(UTC) + timedelta(seconds=i),
                tenant_id=sample_tenant_id,
                action=AuditAction.DOCUMENT_READ,
                outcome=AuditOutcome.SUCCESS,
                severity=AuditSeverity.INFO,
                previous_hash="wrong_hash" if i > 0 else None,  # Broken chain
                entry_hash=f"hash_{i}",
            )
            entries.append(entry)

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=entries)
            MockRepo.return_value = mock_repo

            result = await validate_hash_chain(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert result.valid is False
            assert result.error is not None
            # Error can be "Hash chain broken" or "Entry hash mismatch"
            assert "broken" in result.error.lower() or "mismatch" in result.error.lower()

    @pytest.mark.asyncio
    async def test_validate_chain_empty(self, mock_db_session, sample_tenant_id):
        """Test hash chain validation with no entries."""
        from api.routes.audit import validate_hash_chain

        with patch("api.routes.audit.AuditRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.search = AsyncMock(return_value=[])
            MockRepo.return_value = mock_repo

            result = await validate_hash_chain(
                tenant_id=sample_tenant_id,
                db=mock_db_session,
            )

            assert result.valid is True
            assert result.error is None
            assert result.entries_checked == 0


class TestTenantIdRequired:
    """Test that tenant_id is required on all endpoints."""

    def test_query_requires_tenant_id(self, client):
        """Test /logs requires tenant_id."""
        response = client.get("/api/v1/audit/logs")
        assert response.status_code == 422

    def test_get_entry_requires_tenant_id(self, client):
        """Test /logs/{id} requires tenant_id."""
        response = client.get(f"/api/v1/audit/logs/{uuid4()}")
        assert response.status_code == 422

    def test_stats_requires_tenant_id(self, client):
        """Test /stats requires tenant_id."""
        response = client.get("/api/v1/audit/stats")
        assert response.status_code == 422

    def test_export_requires_tenant_id(self, client):
        """Test /export requires tenant_id."""
        start_time = datetime.now(UTC) - timedelta(days=7)
        end_time = datetime.now(UTC)
        response = client.get(
            "/api/v1/audit/export",
            params={
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        assert response.status_code == 422

    def test_validate_chain_requires_tenant_id(self, client):
        """Test /validate-chain requires tenant_id."""
        response = client.get("/api/v1/audit/validate-chain")
        assert response.status_code == 422
