"""Tests for OpenSearch audit backend."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from security.audit.backends.opensearch import OpenSearchAuditBackend
from security.audit.models import (
    AuditAction,
    AuditLogEntry,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
)


class TestOpenSearchAuditBackendInit:
    """Tests for OpenSearchAuditBackend initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        backend = OpenSearchAuditBackend()

        assert backend._opensearch_url == "http://localhost:9200"
        assert backend._index_prefix == "audit-logs"
        assert backend._username is None
        assert backend._password is None
        assert backend._use_ssl is False
        assert backend._verify_certs is True

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        backend = OpenSearchAuditBackend(
            opensearch_url="https://opensearch.example.com:9200",
            index_prefix="custom-audit",
            username="admin",
            password="secret",
            use_ssl=True,
            verify_certs=False,
        )

        assert backend._opensearch_url == "https://opensearch.example.com:9200"
        assert backend._index_prefix == "custom-audit"
        assert backend._username == "admin"
        assert backend._password == "secret"
        assert backend._use_ssl is True
        assert backend._verify_certs is False

    def test_init_from_env_vars(self):
        """Test initialization from environment variables."""
        env_vars = {
            "AUDIT_OPENSEARCH_URL": "https://audit-os.example.com:9200",
            "AUDIT_OPENSEARCH_INDEX_PREFIX": "env-audit",
            "AUDIT_OPENSEARCH_USERNAME": "env-user",
            "AUDIT_OPENSEARCH_PASSWORD": "env-pass",
            "AUDIT_OPENSEARCH_USE_SSL": "true",
            "AUDIT_OPENSEARCH_VERIFY_CERTS": "false",
        }

        with patch.dict("os.environ", env_vars):
            backend = OpenSearchAuditBackend()

            assert backend._opensearch_url == "https://audit-os.example.com:9200"
            assert backend._index_prefix == "env-audit"
            assert backend._username == "env-user"
            assert backend._password == "env-pass"
            assert backend._use_ssl is True
            assert backend._verify_certs is False


class TestGetIndexName:
    """Tests for daily index naming."""

    def test_get_index_name_produces_correct_format(self):
        """Test that index name follows the pattern {prefix}-{YYYY.MM.DD}."""
        backend = OpenSearchAuditBackend(index_prefix="audit-logs")

        # Test with a specific timestamp
        timestamp = datetime(2024, 3, 15, 10, 30, 0, tzinfo=UTC)
        index_name = backend._get_index_name(timestamp)

        assert index_name == "audit-logs-2024.03.15"

    def test_get_index_name_with_different_prefix(self):
        """Test index name with custom prefix."""
        backend = OpenSearchAuditBackend(index_prefix="my-custom-audit")

        timestamp = datetime(2024, 12, 1, 0, 0, 0, tzinfo=UTC)
        index_name = backend._get_index_name(timestamp)

        assert index_name == "my-custom-audit-2024.12.01"

    def test_get_index_name_uses_utc(self):
        """Test that index name is based on UTC date."""
        backend = OpenSearchAuditBackend()

        # Create a timestamp that's midnight UTC
        timestamp = datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC)
        index_name = backend._get_index_name(timestamp)

        # Should still be June 30th in UTC
        assert index_name == "audit-logs-2024.06.30"


class TestWrite:
    """Tests for write operation."""

    @pytest.fixture
    def sample_entry(self):
        """Create a sample audit log entry."""
        return AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 3, 15, 10, 30, 0, tzinfo=UTC),
            user_id=uuid4(),
            username="testuser",
            tenant_id=uuid4(),
            action=AuditAction.DOCUMENT_CREATE,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            resource_type="document",
            resource_id="doc-123",
            client_ip="192.168.1.100",
            request_method="POST",
            request_path="/api/v1/documents",
            status_code=201,
        )

    @pytest.mark.asyncio
    async def test_write_indexes_entry_correctly(self, sample_entry):
        """Test that write operation indexes the entry with correct index and document."""
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.indices.exists = MagicMock(return_value=True)
        mock_client.index = MagicMock(return_value={"result": "created"})

        # Use the setter method to inject the mock client
        backend._set_client(mock_client)

        await backend.write(sample_entry)

        # Verify index was called with correct parameters
        mock_client.index.assert_called_once()
        call_kwargs = mock_client.index.call_args.kwargs

        assert call_kwargs["index"] == "audit-logs-2024.03.15"
        assert call_kwargs["id"] == str(sample_entry.id)

        # Verify document body contains expected fields
        body = call_kwargs["body"]
        assert body["user_id"] == str(sample_entry.user_id)
        assert body["action"] == "document.create"
        assert body["outcome"] == "success"
        assert body["severity"] == "info"
        assert body["client_ip"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_write_handles_none_values(self):
        """Test that write handles entries with None optional fields."""
        entry = AuditLogEntry(
            action=AuditAction.SYSTEM_STARTUP,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
        )
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.indices.exists = MagicMock(return_value=True)
        mock_client.index = MagicMock(return_value={"result": "created"})

        backend._set_client(mock_client)

        await backend.write(entry)

        # Should not raise and should have called index
        mock_client.index.assert_called_once()


class TestQuery:
    """Tests for query operation."""

    @pytest.mark.asyncio
    async def test_query_builds_correct_opensearch_query(self):
        """Test that query builds correct OpenSearch query with filters."""
        backend = OpenSearchAuditBackend()

        query = AuditQuery(
            tenant_id=uuid4(),
            actions=[AuditAction.DOCUMENT_CREATE, AuditAction.DOCUMENT_READ],
            outcomes=[AuditOutcome.SUCCESS],
            start_time=datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC),
            end_time=datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC),
            limit=50,
            offset=0,
        )

        mock_client = MagicMock()
        mock_client.search = MagicMock(
            return_value={
                "hits": {
                    "hits": [],
                    "total": {"value": 0},
                }
            }
        )

        backend._set_client(mock_client)

        await backend.query(query)

        # Verify search was called
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs

        # Verify index pattern covers the time range
        assert "index" in call_kwargs

        # Verify body has the query structure
        body = call_kwargs["body"]
        assert "query" in body
        assert "bool" in body["query"]
        assert "filter" in body["query"]["bool"]

    @pytest.mark.asyncio
    async def test_query_with_full_text_search(self):
        """Test query with full-text search in details."""
        backend = OpenSearchAuditBackend()

        query = AuditQuery(
            search_text="login attempt",
            limit=100,
        )

        mock_client = MagicMock()
        mock_client.search = MagicMock(
            return_value={
                "hits": {
                    "hits": [],
                    "total": {"value": 0},
                }
            }
        )

        backend._set_client(mock_client)

        await backend.query(query)

        mock_client.search.assert_called_once()
        body = mock_client.search.call_args.kwargs["body"]

        # Should have a should clause with multi_match for full-text search
        assert "query" in body
        query_body = body["query"]["bool"]
        # Check that the query includes a must or should clause for text search
        assert "must" in query_body or "should" in query_body

    @pytest.mark.asyncio
    async def test_query_returns_audit_entries(self):
        """Test that query returns properly parsed AuditLogEntry objects."""
        backend = OpenSearchAuditBackend()

        entry_id = uuid4()
        user_id = uuid4()
        tenant_id = uuid4()
        timestamp = "2024-03-15T10:30:00+00:00"

        mock_client = MagicMock()
        mock_client.search = MagicMock(
            return_value={
                "hits": {
                    "hits": [
                        {
                            "_id": str(entry_id),
                            "_source": {
                                "id": str(entry_id),
                                "timestamp": timestamp,
                                "user_id": str(user_id),
                                "username": "testuser",
                                "tenant_id": str(tenant_id),
                                "action": "document.create",
                                "outcome": "success",
                                "severity": "info",
                                "resource_type": "document",
                                "resource_id": "doc-123",
                                "client_ip": "192.168.1.100",
                            },
                        }
                    ],
                    "total": {"value": 1},
                }
            }
        )

        backend._set_client(mock_client)

        results = await backend.query(AuditQuery())

        assert len(results) == 1
        entry = results[0]
        assert isinstance(entry, AuditLogEntry)
        assert entry.id == entry_id
        assert entry.action == AuditAction.DOCUMENT_CREATE
        assert entry.outcome == AuditOutcome.SUCCESS


class TestGetStats:
    """Tests for get_stats operation."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_aggregations(self):
        """Test that get_stats returns correct statistics from aggregations."""
        backend = OpenSearchAuditBackend()

        tenant_id = uuid4()
        start_time = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)

        mock_client = MagicMock()
        mock_client.search = MagicMock(
            return_value={
                "hits": {"total": {"value": 150}},
                "aggregations": {
                    "by_action": {
                        "buckets": [
                            {"key": "document.create", "doc_count": 50},
                            {"key": "document.read", "doc_count": 80},
                            {"key": "auth.login", "doc_count": 20},
                        ]
                    },
                    "by_outcome": {
                        "buckets": [
                            {"key": "success", "doc_count": 140},
                            {"key": "failure", "doc_count": 10},
                        ]
                    },
                    "by_severity": {
                        "buckets": [
                            {"key": "info", "doc_count": 130},
                            {"key": "warning", "doc_count": 15},
                            {"key": "error", "doc_count": 5},
                        ]
                    },
                    "unique_users": {"value": 25},
                    "unique_resources": {"value": 42},
                },
            }
        )

        backend._set_client(mock_client)

        stats = await backend.get_stats(tenant_id, start_time, end_time)

        assert stats.total_entries == 150
        assert stats.entries_by_action["document.create"] == 50
        assert stats.entries_by_action["document.read"] == 80
        assert stats.entries_by_outcome["success"] == 140
        assert stats.entries_by_severity["info"] == 130
        assert stats.unique_users == 25
        assert stats.unique_resources == 42


class TestHealthCheck:
    """Tests for health_check operation."""

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self):
        """Test that health_check returns True when OpenSearch is healthy."""
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.cluster = MagicMock()
        mock_client.cluster.health = MagicMock(return_value={"status": "green"})

        backend._set_client(mock_client)

        result = await backend.health_check()

        assert result is True
        mock_client.cluster.health.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_yellow(self):
        """Test that health_check returns True when cluster status is yellow."""
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.cluster = MagicMock()
        mock_client.cluster.health = MagicMock(return_value={"status": "yellow"})

        backend._set_client(mock_client)

        result = await backend.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_red(self):
        """Test that health_check returns False when cluster status is red."""
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.cluster = MagicMock()
        mock_client.cluster.health = MagicMock(return_value={"status": "red"})

        backend._set_client(mock_client)

        result = await backend.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        """Test that health_check returns False when an exception occurs."""
        backend = OpenSearchAuditBackend()

        mock_client = MagicMock()
        mock_client.cluster = MagicMock()
        mock_client.cluster.health = MagicMock(side_effect=Exception("Connection refused"))

        backend._set_client(mock_client)

        result = await backend.health_check()

        assert result is False


class TestIndexMapping:
    """Tests for index mapping creation."""

    def test_get_index_mapping_contains_required_fields(self):
        """Test that index mapping contains all required field types."""
        backend = OpenSearchAuditBackend()

        mapping = backend._get_index_mapping()

        properties = mapping["mappings"]["properties"]

        # Check keyword fields
        assert properties["id"]["type"] == "keyword"
        assert properties["user_id"]["type"] == "keyword"
        assert properties["tenant_id"]["type"] == "keyword"
        assert properties["action"]["type"] == "keyword"
        assert properties["outcome"]["type"] == "keyword"
        assert properties["severity"]["type"] == "keyword"
        assert properties["resource_type"]["type"] == "keyword"
        assert properties["resource_id"]["type"] == "keyword"

        # Check date field
        assert properties["timestamp"]["type"] == "date"

        # Check ip field
        assert properties["client_ip"]["type"] == "ip"

        # Check text fields
        assert properties["error_message"]["type"] == "text"

        # Check object fields
        assert properties["details"]["type"] == "object"
