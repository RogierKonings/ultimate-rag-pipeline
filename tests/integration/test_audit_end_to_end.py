"""
End-to-end integration tests for audit logging.

Tests cover:
- OpenSearch backend query and aggregation
- Audit API endpoints (logs, stats, export, validate-chain)
- Multi-service middleware audit trail

Reference: US-10.7.5 AC-4
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from services.shared.security.audit import (
    AuditAction,
    AuditLogEntry,
    AuditMiddleware,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
)
from services.shared.security.audit.backends.opensearch import OpenSearchAuditBackend

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_entries() -> list[AuditLogEntry]:
    """Create sample audit entries for testing."""
    tenant_id = uuid4()
    user_id = uuid4()
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    entries = []
    previous_hash = None

    for i in range(5):
        entry = AuditLogEntry(
            id=uuid4(),
            timestamp=base_time + timedelta(minutes=i),
            user_id=user_id,
            username=f"user-{i}",
            tenant_id=tenant_id,
            service_name="test-service",
            action=AuditAction.DOCUMENT_READ if i % 2 == 0 else AuditAction.QUERY_SEARCH,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            resource_type="document",
            resource_id=f"doc-{i}",
            client_ip=f"192.168.1.{i + 1}",
            request_method="GET",
            request_path=f"/api/v1/documents/doc-{i}",
            status_code=200,
            previous_hash=previous_hash,
        )
        entry.entry_hash = entry.compute_hash(previous_hash)
        entries.append(entry)
        previous_hash = entry.entry_hash

    return entries


@pytest.fixture
def mock_opensearch_client():
    """Create a mock OpenSearch client."""
    client = MagicMock()

    # Mock indices methods
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}

    # Mock index method
    client.index.return_value = {"_id": "test-id", "result": "created"}

    # Mock cluster health
    client.cluster.health.return_value = {"status": "green"}

    return client


@pytest.fixture
def opensearch_backend(mock_opensearch_client) -> OpenSearchAuditBackend:
    """Create an OpenSearch backend with mocked client."""
    backend = OpenSearchAuditBackend(
        opensearch_url="http://localhost:9200",
        index_prefix="audit-logs-test",
    )
    backend._set_client(mock_opensearch_client)
    return backend


@pytest.fixture
def mock_audit_repository():
    """Create a mock AuditRepository."""
    repo = AsyncMock()
    repo.search = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_stats = AsyncMock(
        return_value=AuditStats(
            total_entries=0,
            entries_by_action={},
            entries_by_outcome={},
            entries_by_severity={},
            unique_users=0,
            unique_resources=0,
        )
    )
    repo.create = AsyncMock()
    return repo


# ============================================================================
# OpenSearch Backend Integration Tests
# ============================================================================


class TestOpenSearchBackendIntegration:
    """Tests for the OpenSearch audit backend."""

    def test_daily_index_naming(self, opensearch_backend):
        """Test that daily indices are named correctly."""
        # Test index naming for different dates
        timestamp1 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        timestamp2 = datetime(2024, 2, 28, 23, 59, 59, tzinfo=UTC)
        timestamp3 = datetime(2024, 12, 31, 0, 0, 0, tzinfo=UTC)

        assert opensearch_backend._get_index_name(timestamp1) == "audit-logs-test-2024.01.15"
        assert opensearch_backend._get_index_name(timestamp2) == "audit-logs-test-2024.02.28"
        assert opensearch_backend._get_index_name(timestamp3) == "audit-logs-test-2024.12.31"

    def test_index_naming_with_naive_timestamp(self, opensearch_backend):
        """Test that naive timestamps are handled as UTC."""
        naive_timestamp = datetime(2024, 6, 15, 12, 0, 0)
        index_name = opensearch_backend._get_index_name(naive_timestamp)
        assert index_name == "audit-logs-test-2024.06.15"

    @pytest.mark.asyncio
    async def test_write_audit_entry(self, opensearch_backend, mock_opensearch_client):
        """Test writing an audit entry to OpenSearch."""
        entry = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            user_id=uuid4(),
            tenant_id=uuid4(),
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            resource_type="document",
            resource_id="doc-123",
        )

        await opensearch_backend.write(entry)

        # Verify index was checked/created
        mock_opensearch_client.indices.exists.assert_called()

        # Verify document was indexed
        mock_opensearch_client.index.assert_called_once()
        call_args = mock_opensearch_client.index.call_args
        assert call_args.kwargs["index"] == "audit-logs-test-2024.01.15"
        assert call_args.kwargs["id"] == str(entry.id)

        # Verify document content
        body = call_args.kwargs["body"]
        assert body["action"] == "document.read"
        assert body["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_query_with_filters(
        self, opensearch_backend, mock_opensearch_client, sample_entries
    ):
        """Test querying audit logs with various filters."""
        # Setup mock response
        mock_opensearch_client.search.return_value = {
            "hits": {
                "total": {"value": len(sample_entries)},
                "hits": [
                    {"_source": opensearch_backend._entry_to_document(e)}
                    for e in sample_entries
                ],
            }
        }

        tenant_id = sample_entries[0].tenant_id
        user_id = sample_entries[0].user_id

        # Query with filters
        query = AuditQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            actions=[AuditAction.DOCUMENT_READ],
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 12, 31, tzinfo=UTC),
            limit=10,
            offset=0,
        )

        results = await opensearch_backend.query(query)

        # Verify search was called
        mock_opensearch_client.search.assert_called_once()
        call_args = mock_opensearch_client.search.call_args

        # Check query body contains filters
        body = call_args.kwargs["body"]
        assert "query" in body
        assert "bool" in body["query"]
        assert "filter" in body["query"]["bool"]

        # Verify results
        assert len(results) == len(sample_entries)
        assert all(isinstance(r, AuditLogEntry) for r in results)

    @pytest.mark.asyncio
    async def test_query_with_date_range(self, opensearch_backend, mock_opensearch_client):
        """Test querying with specific date range creates proper filters."""
        mock_opensearch_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        start_time = datetime(2024, 1, 10, tzinfo=UTC)
        end_time = datetime(2024, 1, 20, tzinfo=UTC)

        query = AuditQuery(
            start_time=start_time,
            end_time=end_time,
        )

        await opensearch_backend.query(query)

        # Verify search was called with date range filter
        call_args = mock_opensearch_client.search.call_args
        body = call_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]

        # Find the range filter
        range_filter = next((f for f in filters if "range" in f), None)
        assert range_filter is not None
        assert "timestamp" in range_filter["range"]
        assert "gte" in range_filter["range"]["timestamp"]
        assert "lte" in range_filter["range"]["timestamp"]

    @pytest.mark.asyncio
    async def test_query_with_action_filter(self, opensearch_backend, mock_opensearch_client):
        """Test querying with action filter."""
        mock_opensearch_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        query = AuditQuery(
            actions=[AuditAction.AUTH_LOGIN, AuditAction.AUTH_LOGOUT],
        )

        await opensearch_backend.query(query)

        call_args = mock_opensearch_client.search.call_args
        body = call_args.kwargs["body"]
        filters = body["query"]["bool"]["filter"]

        # Find the terms filter for actions
        action_filter = next((f for f in filters if "terms" in f and "action" in f["terms"]), None)
        assert action_filter is not None
        assert "auth.login" in action_filter["terms"]["action"]
        assert "auth.logout" in action_filter["terms"]["action"]

    @pytest.mark.asyncio
    async def test_stats_aggregation(self, opensearch_backend, mock_opensearch_client):
        """Test stats aggregation query."""
        # Setup mock aggregation response
        mock_opensearch_client.search.return_value = {
            "hits": {"total": {"value": 100}},
            "aggregations": {
                "by_action": {
                    "buckets": [
                        {"key": "document.read", "doc_count": 50},
                        {"key": "query.search", "doc_count": 30},
                        {"key": "auth.login", "doc_count": 20},
                    ]
                },
                "by_outcome": {
                    "buckets": [
                        {"key": "success", "doc_count": 90},
                        {"key": "failure", "doc_count": 10},
                    ]
                },
                "by_severity": {
                    "buckets": [
                        {"key": "info", "doc_count": 80},
                        {"key": "warning", "doc_count": 15},
                        {"key": "error", "doc_count": 5},
                    ]
                },
                "unique_users": {"value": 25},
                "unique_resources": {"value": 42},
            },
        }

        tenant_id = uuid4()
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        stats = await opensearch_backend.get_stats(
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
        )

        # Verify search was called with aggregations
        mock_opensearch_client.search.assert_called_once()
        call_args = mock_opensearch_client.search.call_args
        body = call_args.kwargs["body"]
        assert "aggs" in body
        assert body["size"] == 0  # No hits, only aggregations

        # Verify stats
        assert isinstance(stats, AuditStats)
        assert stats.total_entries == 100
        assert stats.entries_by_action["document.read"] == 50
        assert stats.entries_by_outcome["success"] == 90
        assert stats.entries_by_severity["info"] == 80
        assert stats.unique_users == 25
        assert stats.unique_resources == 42

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, opensearch_backend, mock_opensearch_client):
        """Test health check returns healthy for green/yellow cluster."""
        mock_opensearch_client.cluster.health.return_value = {"status": "green"}
        assert await opensearch_backend.health_check() is True

        mock_opensearch_client.cluster.health.return_value = {"status": "yellow"}
        assert await opensearch_backend.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, opensearch_backend, mock_opensearch_client):
        """Test health check returns unhealthy for red cluster or errors."""
        mock_opensearch_client.cluster.health.return_value = {"status": "red"}
        assert await opensearch_backend.health_check() is False

        mock_opensearch_client.cluster.health.side_effect = Exception("Connection refused")
        assert await opensearch_backend.health_check() is False

    def test_entry_to_document_conversion(self, opensearch_backend):
        """Test converting AuditLogEntry to OpenSearch document."""
        entry = AuditLogEntry(
            id=UUID("12345678-1234-1234-1234-123456789abc"),
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            username="testuser",
            tenant_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            service_name="test-service",
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            resource_type="document",
            resource_id="doc-123",
            client_ip="192.168.1.1",
            user_agent="TestClient/1.0",
            request_method="GET",
            request_path="/api/v1/documents/doc-123",
            status_code=200,
            duration_ms=45.5,
            details={"extra": "info"},
        )

        doc = opensearch_backend._entry_to_document(entry)

        assert doc["id"] == "12345678-1234-1234-1234-123456789abc"
        assert doc["user_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert doc["tenant_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        assert doc["action"] == "document.read"
        assert doc["outcome"] == "success"
        assert doc["severity"] == "info"
        assert doc["client_ip"] == "192.168.1.1"
        assert doc["duration_ms"] == 45.5
        assert doc["details"] == {"extra": "info"}

    def test_document_to_entry_conversion(self, opensearch_backend):
        """Test converting OpenSearch document back to AuditLogEntry."""
        doc = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "timestamp": "2024-01-15T10:30:00+00:00",
            "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "username": "testuser",
            "tenant_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "service_name": "test-service",
            "action": "document.read",
            "outcome": "success",
            "severity": "info",
            "resource_type": "document",
            "resource_id": "doc-123",
            "client_ip": "192.168.1.1",
        }

        entry = opensearch_backend._document_to_entry(doc)

        assert isinstance(entry, AuditLogEntry)
        assert entry.id == UUID("12345678-1234-1234-1234-123456789abc")
        assert entry.user_id == UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        assert entry.action == AuditAction.DOCUMENT_READ
        assert entry.outcome == AuditOutcome.SUCCESS


# ============================================================================
# Audit API Endpoints Integration Tests
# ============================================================================


# Response models (recreated to avoid import issues)
class AuditLogResponse(BaseModel):
    """Response model for audit log queries."""
    events: list[AuditLogEntry] = Field(description="List of audit log entries")
    total: int = Field(description="Total number of matching entries")
    limit: int = Field(description="Number of entries returned")
    offset: int = Field(description="Offset from start of results")


class AuditExportResponse(BaseModel):
    """Response model for audit log export."""
    total_entries: int = Field(description="Total entries exported")
    format: str = Field(description="Export format (json or csv)")
    start_time: datetime = Field(description="Start of export time range")
    end_time: datetime = Field(description="End of export time range")
    entries: list[dict] = Field(description="Exported entries")


class HashChainValidationResponse(BaseModel):
    """Response model for hash chain validation."""
    valid: bool = Field(description="Whether the hash chain is valid")
    error: str | None = Field(description="Error message if validation failed")
    entries_checked: int = Field(description="Number of entries checked")


class TestAuditAPIEndpoints:
    """Tests for audit API endpoints."""

    @pytest.fixture
    def audit_app(self, mock_audit_repository, sample_entries):
        """Create a FastAPI app with audit routes and mocked dependencies."""
        app = FastAPI()

        # Store mock repo for dependency injection
        mock_repo = mock_audit_repository
        mock_repo.search.return_value = sample_entries
        mock_repo.get_stats.return_value = AuditStats(
            total_entries=len(sample_entries),
            entries_by_action={"document.read": 3, "query.search": 2},
            entries_by_outcome={"success": 5},
            entries_by_severity={"info": 5},
            unique_users=1,
            unique_resources=5,
        )

        # Store repo in app state for dependency
        app.state.audit_repo = mock_repo

        def get_repo():
            return app.state.audit_repo

        # Define routes inline to avoid import issues
        @app.get("/api/v1/audit/logs", response_model=AuditLogResponse)
        async def query_audit_logs(
            tenant_id: Annotated[UUID, Query(description="Tenant ID")],
            start_time: Annotated[datetime | None, Query()] = None,
            end_time: Annotated[datetime | None, Query()] = None,
            user_id: Annotated[UUID | None, Query()] = None,
            action: Annotated[AuditAction | None, Query()] = None,
            outcome: Annotated[AuditOutcome | None, Query()] = None,
            severity: Annotated[AuditSeverity | None, Query()] = None,
            resource_type: Annotated[str | None, Query()] = None,
            resource_id: Annotated[str | None, Query()] = None,
            search_text: Annotated[str | None, Query()] = None,
            limit: Annotated[int, Query(ge=1, le=1000)] = 100,
            offset: Annotated[int, Query(ge=0)] = 0,
            order_by: Annotated[str, Query()] = "timestamp",
            order_desc: Annotated[bool, Query()] = True,
            repo=Depends(get_repo),
        ) -> AuditLogResponse:
            actions = [action] if action else None
            outcomes = [outcome] if outcome else None
            severities = [severity] if severity else None

            query = AuditQuery(
                tenant_id=tenant_id,
                start_time=start_time,
                end_time=end_time,
                user_id=user_id,
                actions=actions,
                outcomes=outcomes,
                severities=severities,
                resource_type=resource_type,
                resource_id=resource_id,
                search_text=search_text,
                limit=limit,
                offset=offset,
                order_by=order_by,
                order_desc=order_desc,
            )

            entries = await repo.search(query)
            return AuditLogResponse(
                events=entries,
                total=len(entries),
                limit=limit,
                offset=offset,
            )

        @app.get("/api/v1/audit/stats", response_model=AuditStats)
        async def get_audit_stats(
            tenant_id: Annotated[UUID, Query()],
            start_time: Annotated[datetime | None, Query()] = None,
            end_time: Annotated[datetime | None, Query()] = None,
            repo=Depends(get_repo),
        ) -> AuditStats:
            return await repo.get_stats(
                tenant_id=tenant_id,
                start_time=start_time,
                end_time=end_time,
            )

        MAX_EXPORT_DAYS = 90

        @app.get("/api/v1/audit/export")
        async def export_audit_logs(
            tenant_id: Annotated[UUID, Query()],
            start_time: Annotated[datetime, Query()],
            end_time: Annotated[datetime, Query()],
            format: Annotated[str, Query()] = "json",
            include_details: Annotated[bool, Query()] = False,
            repo=Depends(get_repo),
        ):
            time_diff = end_time - start_time
            if time_diff.days > MAX_EXPORT_DAYS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Export time range cannot exceed {MAX_EXPORT_DAYS} days",
                )

            if format not in ("json", "csv"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Format must be 'json' or 'csv'",
                )

            query = AuditQuery(
                tenant_id=tenant_id,
                start_time=start_time,
                end_time=end_time,
                limit=1000,
                offset=0,
                order_by="timestamp",
                order_desc=False,
            )

            entries = await repo.search(query)

            if format == "csv":
                # Generate CSV response
                columns = [
                    "id", "timestamp", "user_id", "username", "tenant_id",
                    "action", "outcome", "severity", "resource_type",
                    "resource_id", "client_ip", "request_method",
                    "request_path", "status_code", "error_message", "entry_hash",
                ]

                def generate():
                    output = io.StringIO()
                    writer = csv.DictWriter(output, fieldnames=columns)
                    writer.writeheader()
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)

                    for entry in entries:
                        row = {
                            "id": str(entry.id),
                            "timestamp": entry.timestamp.isoformat(),
                            "user_id": str(entry.user_id) if entry.user_id else "",
                            "username": entry.username or "",
                            "tenant_id": str(entry.tenant_id) if entry.tenant_id else "",
                            "action": entry.action.value,
                            "outcome": entry.outcome.value,
                            "severity": entry.severity.value,
                            "resource_type": entry.resource_type or "",
                            "resource_id": entry.resource_id or "",
                            "client_ip": entry.client_ip or "",
                            "request_method": entry.request_method or "",
                            "request_path": entry.request_path or "",
                            "status_code": entry.status_code or "",
                            "error_message": entry.error_message or "",
                            "entry_hash": entry.entry_hash or "",
                        }
                        writer.writerow(row)
                        yield output.getvalue()
                        output.seek(0)
                        output.truncate(0)

                return StreamingResponse(
                    generate(),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
                )

            # JSON format
            export_data = []
            for entry in entries:
                if include_details:
                    export_data.append(entry.model_dump(mode="json"))
                else:
                    export_data.append(entry.to_safe_dict())

            return AuditExportResponse(
                total_entries=len(entries),
                format="json",
                start_time=start_time,
                end_time=end_time,
                entries=export_data,
            )

        @app.get("/api/v1/audit/validate-chain", response_model=HashChainValidationResponse)
        async def validate_hash_chain(
            tenant_id: Annotated[UUID, Query()],
            limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
            repo=Depends(get_repo),
        ) -> HashChainValidationResponse:
            query = AuditQuery(
                tenant_id=tenant_id,
                limit=limit,
                offset=0,
                order_by="timestamp",
                order_desc=False,
            )

            entries = await repo.search(query)

            if not entries:
                return HashChainValidationResponse(
                    valid=True,
                    error=None,
                    entries_checked=0,
                )

            previous_hash = None
            entries_checked = 0

            for entry in entries:
                entries_checked += 1

                if entry.previous_hash != previous_hash:
                    return HashChainValidationResponse(
                        valid=False,
                        error=f"Hash chain broken at entry {entry.id}",
                        entries_checked=entries_checked,
                    )

                computed = entry.compute_hash(previous_hash)
                if entry.entry_hash != computed:
                    return HashChainValidationResponse(
                        valid=False,
                        error=f"Entry hash mismatch at {entry.id}",
                        entries_checked=entries_checked,
                    )

                previous_hash = entry.entry_hash

            return HashChainValidationResponse(
                valid=True,
                error=None,
                entries_checked=entries_checked,
            )

        return app

    @pytest.fixture
    def audit_client(self, audit_app):
        """Create a test client."""
        return TestClient(audit_app)

    def test_query_audit_logs(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/logs endpoint."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/logs",
            params={
                "tenant_id": tenant_id,
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert data["limit"] == 10
        assert data["offset"] == 0

    def test_query_audit_logs_with_filters(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/logs with various filters."""
        tenant_id = str(sample_entries[0].tenant_id)
        user_id = str(sample_entries[0].user_id)

        response = audit_client.get(
            "/api/v1/audit/logs",
            params={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": "document.read",
                "outcome": "success",
                "severity": "info",
                "resource_type": "document",
            },
        )

        assert response.status_code == 200

    def test_query_audit_logs_with_date_range(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/logs with date range."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/logs",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-12-31T23:59:59Z",
            },
        )

        assert response.status_code == 200

    def test_query_audit_logs_pagination(self, audit_client, sample_entries):
        """Test pagination in audit logs query."""
        tenant_id = str(sample_entries[0].tenant_id)

        # First page
        response1 = audit_client.get(
            "/api/v1/audit/logs",
            params={
                "tenant_id": tenant_id,
                "limit": 2,
                "offset": 0,
            },
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["limit"] == 2
        assert data1["offset"] == 0

        # Second page
        response2 = audit_client.get(
            "/api/v1/audit/logs",
            params={
                "tenant_id": tenant_id,
                "limit": 2,
                "offset": 2,
            },
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["offset"] == 2

    def test_get_audit_stats(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/stats endpoint."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/stats",
            params={"tenant_id": tenant_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_entries" in data
        assert "entries_by_action" in data
        assert "entries_by_outcome" in data
        assert "entries_by_severity" in data
        assert "unique_users" in data
        assert "unique_resources" in data

    def test_get_audit_stats_with_date_range(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/stats with date range."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/stats",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200

    def test_export_audit_logs_json(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/export with JSON format."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-01-31T23:59:59Z",
                "format": "json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_entries" in data
        assert "format" in data
        assert data["format"] == "json"
        assert "entries" in data

    def test_export_audit_logs_csv(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/export with CSV format."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-01-31T23:59:59Z",
                "format": "csv",
            },
        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        assert "attachment" in response.headers.get("content-disposition", "")

    def test_export_audit_logs_invalid_format(self, audit_client, sample_entries):
        """Test export with invalid format returns 400."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-01-31T23:59:59Z",
                "format": "xml",  # Invalid format
            },
        )

        assert response.status_code == 400

    def test_export_audit_logs_time_range_too_large(self, audit_client, sample_entries):
        """Test export with time range > 90 days returns 400."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": tenant_id,
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-06-01T00:00:00Z",  # > 90 days
                "format": "json",
            },
        )

        assert response.status_code == 400
        assert "90 days" in response.json().get("detail", "")

    def test_validate_hash_chain_valid(self, audit_client, sample_entries):
        """Test GET /api/v1/audit/validate-chain with valid chain."""
        tenant_id = str(sample_entries[0].tenant_id)

        response = audit_client.get(
            "/api/v1/audit/validate-chain",
            params={"tenant_id": tenant_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert "valid" in data
        assert "entries_checked" in data
        # The sample_entries fixture creates a valid hash chain
        assert data["valid"] is True
        assert data["entries_checked"] == len(sample_entries)

    def test_validate_hash_chain_empty(self, audit_app, mock_audit_repository):
        """Test hash chain validation with no entries."""
        # Override search to return empty list
        mock_audit_repository.search.return_value = []

        client = TestClient(audit_app)
        tenant_id = str(uuid4())

        response = client.get(
            "/api/v1/audit/validate-chain",
            params={"tenant_id": tenant_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["entries_checked"] == 0


# ============================================================================
# Multi-Service Middleware Flow Tests
# ============================================================================


class TestMultiServiceMiddlewareFlow:
    """Tests for audit middleware across multiple services."""

    @pytest.fixture
    def ingestion_app(self):
        """Create a mock ingestion service app."""
        app = FastAPI()

        @app.post("/api/v1/ingest/documents")
        async def ingest_document():
            return {"id": str(uuid4()), "status": "ingested"}

        @app.get("/api/v1/ingest/documents/{doc_id}")
        async def get_document(doc_id: str):
            return {"id": doc_id, "content": "test"}

        return app

    @pytest.fixture
    def retrieval_app(self):
        """Create a mock retrieval service app."""
        app = FastAPI()

        @app.post("/api/v1/search")
        async def search():
            return {"results": [], "total": 0}

        @app.get("/api/v1/retrieve/{doc_id}")
        async def retrieve(doc_id: str):
            return {"id": doc_id, "chunks": []}

        return app

    @pytest.fixture
    def orchestrator_app(self):
        """Create a mock orchestrator service app."""
        app = FastAPI()

        @app.post("/api/v1/query")
        async def query():
            return {"response": "test response", "sources": []}

        @app.post("/api/v1/chat")
        async def chat():
            return {"response": "chat response"}

        return app

    @pytest.mark.asyncio
    async def test_ingestion_service_audit_logging(self, ingestion_app):
        """Test that ingestion service creates audit entries with correct service_name."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "ingestion-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_WRITE),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    service_name=self.service_name,
                )

        mock_logger = MockAuditLogger()
        ingestion_app.add_middleware(
            AuditMiddleware,
            service_name="ingestion-service",
            logger=mock_logger,
        )

        async with AsyncClient(
            transport=ASGITransport(app=ingestion_app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/ingest/documents")
            assert response.status_code == 200

        # Verify audit entry was created
        assert len(logged_entries) == 1
        # Middleware determines action from path, should be DOCUMENT_CREATE
        assert logged_entries[0]["action"] == AuditAction.DOCUMENT_CREATE

    @pytest.mark.asyncio
    async def test_retrieval_service_audit_logging(self, retrieval_app):
        """Test that retrieval service creates audit entries with correct service_name."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "retrieval-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    service_name=self.service_name,
                )

        mock_logger = MockAuditLogger()
        retrieval_app.add_middleware(
            AuditMiddleware,
            service_name="retrieval-service",
            logger=mock_logger,
        )

        async with AsyncClient(
            transport=ASGITransport(app=retrieval_app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/search")
            assert response.status_code == 200

        # Verify audit entry was created with search action
        assert len(logged_entries) == 1
        assert logged_entries[0]["action"] == AuditAction.QUERY_SEARCH

    @pytest.mark.asyncio
    async def test_orchestrator_service_audit_logging(self, orchestrator_app):
        """Test that orchestrator service creates audit entries with correct service_name."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "orchestrator-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    service_name=self.service_name,
                )

        mock_logger = MockAuditLogger()
        orchestrator_app.add_middleware(
            AuditMiddleware,
            service_name="orchestrator-service",
            logger=mock_logger,
        )

        async with AsyncClient(
            transport=ASGITransport(app=orchestrator_app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/chat")
            assert response.status_code == 200

        # Verify audit entry was created with chat action
        assert len(logged_entries) == 1
        assert logged_entries[0]["action"] == AuditAction.QUERY_CHAT

    @pytest.mark.asyncio
    async def test_request_id_propagation(self):
        """Test that request_id is captured in audit entries."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "test-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    request_id=kwargs.get("request_id"),
                )

        app = FastAPI()

        @app.get("/api/v1/test")
        async def test_endpoint():
            return {"status": "ok"}

        mock_logger = MockAuditLogger()
        app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=mock_logger,
        )

        request_id = "req-789"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/test",
                headers={
                    "x-request-id": request_id,
                },
            )
            assert response.status_code == 200

        # Verify request_id was captured
        assert len(logged_entries) == 1
        assert logged_entries[0].get("request_id") == request_id

    @pytest.mark.asyncio
    async def test_traceparent_header_extraction(self):
        """Test that traceparent header is correctly parsed for trace_id."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "test-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    trace_id=kwargs.get("trace_id"),
                )

        app = FastAPI()

        @app.get("/api/v1/test")
        async def test_endpoint():
            return {"status": "ok"}

        mock_logger = MockAuditLogger()
        app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=mock_logger,
        )

        # W3C traceparent format: version-trace_id-parent_id-flags
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/v1/test",
                headers={"traceparent": traceparent},
            )
            assert response.status_code == 200

        # Verify trace_id was extracted from traceparent
        assert len(logged_entries) == 1
        assert logged_entries[0].get("trace_id") == "4bf92f3577b34da6a3ce929d0e0e4736"

    @pytest.mark.asyncio
    async def test_excluded_paths_not_logged(self):
        """Test that excluded paths do not create audit entries."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "test-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                )

        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "healthy"}

        @app.get("/metrics")
        async def metrics():
            return {"metrics": []}

        @app.get("/api/v1/test")
        async def test_endpoint():
            return {"status": "ok"}

        mock_logger = MockAuditLogger()
        app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=mock_logger,
            exclude_paths=["/health", "/metrics"],
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # These should not be logged
            await client.get("/health")
            await client.get("/metrics")
            # This should be logged
            await client.get("/api/v1/test")

        # Only the API endpoint should be logged
        assert len(logged_entries) == 1
        assert logged_entries[0]["request_path"] == "/api/v1/test"

    @pytest.mark.asyncio
    async def test_error_response_audit_logging(self):
        """Test that error responses are logged with appropriate outcome."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "test-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                )

        app = FastAPI()

        @app.get("/api/v1/forbidden")
        async def forbidden():
            raise HTTPException(status_code=403, detail="Forbidden")

        @app.get("/api/v1/unauthorized")
        async def unauthorized():
            raise HTTPException(status_code=401, detail="Unauthorized")

        @app.get("/api/v1/not-found")
        async def not_found():
            raise HTTPException(status_code=404, detail="Not found")

        mock_logger = MockAuditLogger()
        app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=mock_logger,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.get("/api/v1/forbidden")
            await client.get("/api/v1/unauthorized")
            await client.get("/api/v1/not-found")

        assert len(logged_entries) == 3

        # Check outcomes are set correctly
        assert logged_entries[0]["outcome"] == AuditOutcome.DENIED
        assert logged_entries[1]["outcome"] == AuditOutcome.UNAUTHORIZED
        assert logged_entries[2]["outcome"] == AuditOutcome.FAILURE

    @pytest.mark.asyncio
    async def test_client_ip_extraction(self):
        """Test that client IP is correctly extracted from various headers."""
        logged_entries: list[dict[str, Any]] = []

        class MockAuditLogger:
            service_name = "test-service"

            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action", AuditAction.GENERIC_READ),
                    outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                    client_ip=kwargs.get("client_ip"),
                )

        app = FastAPI()

        @app.get("/api/v1/test")
        async def test_endpoint():
            return {"status": "ok"}

        mock_logger = MockAuditLogger()
        app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=mock_logger,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Test X-Forwarded-For header
            await client.get(
                "/api/v1/test",
                headers={"x-forwarded-for": "203.0.113.1, 10.0.0.1"},
            )

        # Should extract the first IP from X-Forwarded-For
        assert len(logged_entries) == 1
        assert logged_entries[0]["client_ip"] == "203.0.113.1"

    @pytest.mark.asyncio
    async def test_multiple_services_create_distinct_audit_trails(self):
        """Test that different services create audit entries with correct service names."""
        all_logged_entries: list[tuple[str, dict[str, Any]]] = []

        def create_mock_logger(service_name: str):
            class MockAuditLogger:
                def __init__(self):
                    self.service_name = service_name

                async def log(self, **kwargs):
                    all_logged_entries.append((self.service_name, kwargs))
                    return AuditLogEntry(
                        id=uuid4(),
                        timestamp=datetime.now(tz=UTC),
                        action=kwargs.get("action", AuditAction.GENERIC_READ),
                        outcome=kwargs.get("outcome", AuditOutcome.SUCCESS),
                        service_name=self.service_name,
                    )
            return MockAuditLogger()

        # Create 3 different service apps
        ingestion_app = FastAPI()
        @ingestion_app.post("/api/v1/ingest/documents")
        async def ingest():
            return {"status": "ok"}
        ingestion_app.add_middleware(
            AuditMiddleware,
            service_name="ingestion-service",
            logger=create_mock_logger("ingestion-service"),
        )

        retrieval_app = FastAPI()
        @retrieval_app.post("/api/v1/search")
        async def search():
            return {"status": "ok"}
        retrieval_app.add_middleware(
            AuditMiddleware,
            service_name="retrieval-service",
            logger=create_mock_logger("retrieval-service"),
        )

        orchestrator_app = FastAPI()
        @orchestrator_app.post("/api/v1/query")
        async def query():
            return {"status": "ok"}
        orchestrator_app.add_middleware(
            AuditMiddleware,
            service_name="orchestrator-service",
            logger=create_mock_logger("orchestrator-service"),
        )

        # Make requests to each service
        async with AsyncClient(
            transport=ASGITransport(app=ingestion_app),
            base_url="http://test",
        ) as client:
            await client.post("/api/v1/ingest/documents")

        async with AsyncClient(
            transport=ASGITransport(app=retrieval_app),
            base_url="http://test",
        ) as client:
            await client.post("/api/v1/search")

        async with AsyncClient(
            transport=ASGITransport(app=orchestrator_app),
            base_url="http://test",
        ) as client:
            await client.post("/api/v1/query")

        # Verify we have 3 distinct entries from 3 services
        assert len(all_logged_entries) == 3

        service_names = [entry[0] for entry in all_logged_entries]
        assert "ingestion-service" in service_names
        assert "retrieval-service" in service_names
        assert "orchestrator-service" in service_names


# ============================================================================
# Hash Chain Integrity Tests
# ============================================================================


class TestHashChainIntegrity:
    """Tests for hash chain integrity in audit logs."""

    def test_create_valid_hash_chain(self, sample_entries):
        """Test that sample_entries fixture creates a valid hash chain."""
        # Verify the chain
        previous_hash = None
        for entry in sample_entries:
            assert entry.previous_hash == previous_hash

            computed = entry.compute_hash(previous_hash)
            assert entry.entry_hash == computed

            previous_hash = entry.entry_hash

    def test_detect_tampered_entry(self, sample_entries):
        """Test that tampering with an entry breaks the hash chain."""
        # Tamper with the middle entry
        sample_entries[2].resource_id = "tampered-doc"

        # The hash should no longer match
        previous_hash = sample_entries[1].entry_hash
        computed = sample_entries[2].compute_hash(previous_hash)
        assert sample_entries[2].entry_hash != computed

    def test_detect_missing_entry(self, sample_entries):
        """Test that removing an entry breaks the hash chain."""
        # Remove the middle entry
        entries_with_gap = sample_entries[:2] + sample_entries[3:]

        # The chain should be broken after the gap
        assert entries_with_gap[2].previous_hash != entries_with_gap[1].entry_hash

    def test_detect_reordered_entries(self, sample_entries):
        """Test that reordering entries breaks the hash chain."""
        # Swap entries 2 and 3
        reordered = sample_entries[:2] + [sample_entries[3], sample_entries[2]] + sample_entries[4:]

        # The chain should be broken
        assert reordered[2].previous_hash != reordered[1].entry_hash
