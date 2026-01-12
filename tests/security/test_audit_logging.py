"""
Tests for audit logging module.

This module tests audit log creation, hashing, middleware,
and repository functionality.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from services.shared.security.audit import (
    AuditAction,
    AuditLogEntry,
    AuditLogger,
    AuditMiddleware,
    AuditOutcome,
    AuditQuery,
    AuditSeverity,
    AuditStats,
    get_audit_logger,
    set_audit_logger,
)


class TestAuditLogEntry:
    """Tests for AuditLogEntry model."""

    def test_create_entry(self):
        """Test creating an audit entry."""
        entry = AuditLogEntry(
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
            user_id=uuid4(),
            username="test@example.com",
            client_ip="192.168.1.1",
        )

        assert entry.action == AuditAction.AUTH_LOGIN
        assert entry.outcome == AuditOutcome.SUCCESS
        assert entry.severity == AuditSeverity.INFO  # Default
        assert entry.timestamp is not None
        assert entry.id is not None

    def test_compute_hash(self):
        """Test hash computation."""
        entry = AuditLogEntry(
            action=AuditAction.DOCUMENT_READ,
            user_id=uuid4(),
        )

        hash1 = entry.compute_hash()
        hash2 = entry.compute_hash()

        # Same entry should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_compute_hash_with_previous(self):
        """Test hash chaining."""
        entry1 = AuditLogEntry(action=AuditAction.AUTH_LOGIN)
        entry2 = AuditLogEntry(action=AuditAction.DOCUMENT_READ)

        hash1 = entry1.compute_hash()
        hash2_no_chain = entry2.compute_hash()
        hash2_with_chain = entry2.compute_hash(hash1)

        # Chained hash should be different
        assert hash2_no_chain != hash2_with_chain

    def test_to_log_dict(self):
        """Test conversion to log dictionary."""
        user_id = uuid4()
        entry = AuditLogEntry(
            action=AuditAction.QUERY_SEARCH,
            outcome=AuditOutcome.SUCCESS,
            user_id=user_id,
            username="test@example.com",
            client_ip="10.0.0.1",
            status_code=200,
        )

        log_dict = entry.to_log_dict()

        assert log_dict["action"] == "query.search"
        assert log_dict["outcome"] == "success"
        assert log_dict["user_id"] == str(user_id)
        assert log_dict["username"] == "test@example.com"
        assert log_dict["client_ip"] == "10.0.0.1"
        assert log_dict["status_code"] == 200

    def test_to_safe_dict(self):
        """Test conversion to safe dictionary (for export)."""
        entry = AuditLogEntry(
            action=AuditAction.DATA_EXPORT,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.WARNING,
            resource_type="document",
            resource_id="doc-123",
            details={"sensitive": "data"},  # Should not be included
        )

        safe_dict = entry.to_safe_dict()

        assert "sensitive" not in str(safe_dict)
        assert safe_dict["action"] == "data.export"
        assert safe_dict["resource_type"] == "document"


class TestAuditLogger:
    """Tests for AuditLogger class."""

    @pytest.fixture
    def logger(self):
        """Create test logger."""
        return AuditLogger(service_name="test-service")

    @pytest.mark.asyncio
    async def test_log_basic(self, logger):
        """Test basic log entry creation."""
        entry = await logger.log(
            action=AuditAction.GENERIC_READ,
            outcome=AuditOutcome.SUCCESS,
        )

        assert entry.action == AuditAction.GENERIC_READ
        assert entry.outcome == AuditOutcome.SUCCESS
        assert entry.service_name == "test-service"
        assert entry.entry_hash is not None

    @pytest.mark.asyncio
    async def test_log_with_user(self, logger):
        """Test logging with user context."""
        user_id = uuid4()
        tenant_id = uuid4()

        entry = await logger.log(
            action=AuditAction.DOCUMENT_CREATE,
            user_id=user_id,
            username="john@example.com",
            tenant_id=tenant_id,
            resource_type="document",
            resource_id="doc-456",
        )

        assert entry.user_id == user_id
        assert entry.username == "john@example.com"
        assert entry.tenant_id == tenant_id
        assert entry.resource_type == "document"
        assert entry.resource_id == "doc-456"

    @pytest.mark.asyncio
    async def test_log_login_success(self, logger):
        """Test login success logging."""
        user_id = uuid4()

        entry = await logger.log_login(
            user_id=user_id,
            username="alice@example.com",
            success=True,
            client_ip="192.168.1.100",
            mfa_used=True,
        )

        assert entry.action == AuditAction.AUTH_LOGIN
        assert entry.outcome == AuditOutcome.SUCCESS
        assert entry.severity == AuditSeverity.INFO
        assert entry.details.get("mfa_used") is True

    @pytest.mark.asyncio
    async def test_log_login_failure(self, logger):
        """Test login failure logging."""
        entry = await logger.log_login(
            username="bob@example.com",
            success=False,
            client_ip="10.0.0.50",
            failure_reason="Invalid password",
        )

        assert entry.action == AuditAction.AUTH_LOGIN
        assert entry.outcome == AuditOutcome.FAILURE
        assert entry.severity == AuditSeverity.WARNING
        assert entry.error_message == "Invalid password"

    @pytest.mark.asyncio
    async def test_log_document_access(self, logger):
        """Test document access logging."""
        user_id = uuid4()
        doc_id = uuid4()

        entry = await logger.log_document_access(
            user_id=user_id,
            document_id=doc_id,
            action=AuditAction.DOCUMENT_READ,
            document_name="important.pdf",
        )

        assert entry.action == AuditAction.DOCUMENT_READ
        assert entry.resource_type == "document"
        assert entry.resource_id == str(doc_id)
        assert entry.resource_name == "important.pdf"

    @pytest.mark.asyncio
    async def test_log_query(self, logger):
        """Test query logging."""
        user_id = uuid4()

        entry = await logger.log_query(
            user_id=user_id,
            query_text="How do I configure X?",
            results_count=10,
            duration_ms=150.5,
        )

        assert entry.action == AuditAction.QUERY_SEARCH
        assert entry.details.get("query_length") == len("How do I configure X?")
        assert entry.details.get("results_count") == 10
        # Query text should NOT be in details (privacy)
        assert "How do I" not in str(entry.details)

    @pytest.mark.asyncio
    async def test_log_access_denied(self, logger):
        """Test access denied logging."""
        user_id = uuid4()

        entry = await logger.log_access_denied(
            user_id=user_id,
            resource_type="document",
            resource_id="secret-doc",
            action=AuditAction.DOCUMENT_READ,
            reason="User not in allowed_users",
        )

        assert entry.action == AuditAction.DOCUMENT_READ
        assert entry.outcome == AuditOutcome.DENIED
        assert entry.severity == AuditSeverity.WARNING
        assert entry.status_code == 403
        assert entry.error_message == "User not in allowed_users"

    @pytest.mark.asyncio
    async def test_log_unauthorized(self, logger):
        """Test unauthorized access logging."""
        entry = await logger.log_unauthorized(
            resource_type="api",
            resource_id="/admin/users",
            client_ip="1.2.3.4",
        )

        assert entry.outcome == AuditOutcome.UNAUTHORIZED
        assert entry.status_code == 401
        assert entry.client_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_log_error(self, logger):
        """Test error logging."""
        user_id = uuid4()

        entry = await logger.log_error(
            action=AuditAction.DOCUMENT_CREATE,
            error_message="Database connection failed",
            error_code="DB_CONN_ERR",
            user_id=user_id,
        )

        assert entry.outcome == AuditOutcome.ERROR
        assert entry.severity == AuditSeverity.ERROR
        assert entry.error_message == "Database connection failed"
        assert entry.error_code == "DB_CONN_ERR"

    @pytest.mark.asyncio
    async def test_log_admin_action(self, logger):
        """Test admin action logging."""
        admin_id = uuid4()
        target_user_id = uuid4()

        entry = await logger.log_admin_action(
            user_id=admin_id,
            action=AuditAction.ADMIN_USER_CREATE,
            target_type="user",
            target_id=str(target_user_id),
            target_name="newuser@example.com",
        )

        assert entry.action == AuditAction.ADMIN_USER_CREATE
        assert entry.severity == AuditSeverity.WARNING  # Admin actions
        assert entry.resource_type == "user"
        assert entry.resource_id == str(target_user_id)

    @pytest.mark.asyncio
    async def test_hash_chain(self, logger):
        """Test that entries form a hash chain."""
        entry1 = await logger.log(action=AuditAction.AUTH_LOGIN)
        entry2 = await logger.log(action=AuditAction.DOCUMENT_READ)
        entry3 = await logger.log(action=AuditAction.AUTH_LOGOUT)

        # Each entry should reference previous
        assert entry2.previous_hash == entry1.entry_hash
        assert entry3.previous_hash == entry2.entry_hash

    @pytest.mark.asyncio
    async def test_persist_callback(self):
        """Test persistence callback is called."""
        persist_mock = MagicMock()

        logger = AuditLogger(
            service_name="test",
            persist_callback=persist_mock,
        )

        await logger.log(action=AuditAction.GENERIC_READ)

        persist_mock.assert_called_once()
        call_args = persist_mock.call_args[0]
        assert isinstance(call_args[0], AuditLogEntry)


class TestAuditQuery:
    """Tests for AuditQuery model."""

    def test_default_query(self):
        """Test default query parameters."""
        query = AuditQuery()

        assert query.limit == 100
        assert query.offset == 0
        assert query.order_by == "timestamp"
        assert query.order_desc is True

    def test_filtered_query(self):
        """Test query with filters."""
        user_id = uuid4()
        start = datetime.now(UTC) - timedelta(days=7)
        end = datetime.now(UTC)

        query = AuditQuery(
            user_id=user_id,
            start_time=start,
            end_time=end,
            actions=[AuditAction.AUTH_LOGIN, AuditAction.AUTH_LOGOUT],
            outcomes=[AuditOutcome.SUCCESS, AuditOutcome.FAILURE],
            limit=50,
        )

        assert query.user_id == user_id
        assert len(query.actions) == 2
        assert len(query.outcomes) == 2
        assert query.limit == 50


class TestAuditStats:
    """Tests for AuditStats model."""

    def test_stats_model(self):
        """Test stats model creation."""
        stats = AuditStats(
            total_entries=1000,
            entries_by_action={
                "auth.login": 100,
                "document.read": 500,
                "query.search": 400,
            },
            entries_by_outcome={
                "success": 950,
                "failure": 30,
                "denied": 20,
            },
            unique_users=50,
            unique_resources=200,
        )

        assert stats.total_entries == 1000
        assert stats.entries_by_action["auth.login"] == 100
        assert stats.unique_users == 50


class TestAuditMiddleware:
    """Tests for AuditMiddleware."""

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        request = MagicMock()
        request.url.path = "/api/v1/documents/123"
        request.method = "GET"
        request.headers = {
            "user-agent": "test-agent",
            "x-forwarded-for": "192.168.1.1",
        }
        request.client.host = "127.0.0.1"
        request.state = MagicMock()
        request.state.user_id = str(uuid4())
        request.state.tenant_id = str(uuid4())
        return request

    @pytest.fixture
    def mock_response(self):
        """Create mock response."""
        response = MagicMock()
        response.status_code = 200
        return response

    def test_should_exclude_health(self):
        """Test health endpoints are excluded."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        assert middleware._should_exclude("/health") is True
        assert middleware._should_exclude("/healthz") is True
        assert middleware._should_exclude("/metrics") is True
        assert middleware._should_exclude("/api/documents") is False

    def test_get_client_ip_forwarded(self):
        """Test client IP extraction with forwarding."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}
        request.client.host = "127.0.0.1"

        ip = middleware._get_client_ip(request)
        assert ip == "10.0.0.1"  # First IP in chain

    def test_get_client_ip_direct(self):
        """Test client IP extraction without forwarding."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        request = MagicMock()
        request.headers = {}
        request.client.host = "192.168.1.100"

        ip = middleware._get_client_ip(request)
        assert ip == "192.168.1.100"

    def test_determine_action_auth(self):
        """Test action determination for auth endpoints."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        assert middleware._determine_action("POST", "/api/v1/auth/login") == AuditAction.AUTH_LOGIN
        assert (
            middleware._determine_action("POST", "/api/v1/auth/logout") == AuditAction.AUTH_LOGOUT
        )
        assert (
            middleware._determine_action("POST", "/api/v1/auth/refresh")
            == AuditAction.AUTH_TOKEN_REFRESH
        )

    def test_determine_action_documents(self):
        """Test action determination for document endpoints."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        assert (
            middleware._determine_action("POST", "/api/v1/documents") == AuditAction.DOCUMENT_CREATE
        )
        assert (
            middleware._determine_action("GET", "/api/v1/documents/123")
            == AuditAction.DOCUMENT_READ
        )
        assert (
            middleware._determine_action("PUT", "/api/v1/documents/123")
            == AuditAction.DOCUMENT_UPDATE
        )
        assert (
            middleware._determine_action("DELETE", "/api/v1/documents/123")
            == AuditAction.DOCUMENT_DELETE
        )

    def test_determine_action_search(self):
        """Test action determination for search endpoints."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        assert middleware._determine_action("POST", "/api/v1/search") == AuditAction.QUERY_SEARCH
        assert middleware._determine_action("POST", "/api/v1/retrieve") == AuditAction.QUERY_SEARCH
        assert middleware._determine_action("POST", "/api/v1/chat") == AuditAction.QUERY_CHAT

    def test_extract_resource(self):
        """Test resource extraction from path."""
        app = MagicMock()
        middleware = AuditMiddleware(app, service_name="test")

        resource_type, resource_id = middleware._extract_resource(
            "/api/v1/documents/abc-123-def",
        )
        assert resource_type == "document"
        assert resource_id == "abc-123-def"

        resource_type, resource_id = middleware._extract_resource(
            "/api/v1/users/456",
        )
        assert resource_type == "user"
        assert resource_id == "456"


class TestGlobalLogger:
    """Tests for global logger functions."""

    def test_get_audit_logger(self):
        """Test getting global logger."""
        # Reset global logger to test creating a new one
        set_audit_logger(None)
        logger = get_audit_logger("my-service")

        assert isinstance(logger, AuditLogger)
        assert logger.service_name == "my-service"

    def test_get_same_logger(self):
        """Test getting same logger instance."""
        # Reset global logger first
        set_audit_logger(None)
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        # Should return same instance
        assert logger1 is logger2


class TestAuditIntegration:
    """Integration tests for audit logging workflow."""

    @pytest.mark.asyncio
    async def test_full_audit_workflow(self):
        """Test complete audit workflow."""
        persist_entries = []

        def persist_callback(entry):
            persist_entries.append(entry)

        logger = AuditLogger(
            service_name="integration-test",
            persist_callback=persist_callback,
        )

        user_id = uuid4()
        tenant_id = uuid4()
        doc_id = uuid4()

        # Login
        login_entry = await logger.log_login(
            user_id=user_id,
            username="test@example.com",
            tenant_id=tenant_id,
            success=True,
            client_ip="10.0.0.1",
        )

        # Read document
        read_entry = await logger.log_document_access(
            user_id=user_id,
            document_id=doc_id,
            action=AuditAction.DOCUMENT_READ,
            tenant_id=tenant_id,
        )

        # Search
        search_entry = await logger.log_query(
            user_id=user_id,
            query_text="Find relevant documents",
            tenant_id=tenant_id,
            results_count=5,
        )

        # Logout
        logout_entry = await logger.log_logout(
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # Verify chain
        assert len(persist_entries) == 4
        assert read_entry.previous_hash == login_entry.entry_hash
        assert search_entry.previous_hash == read_entry.entry_hash
        assert logout_entry.previous_hash == search_entry.entry_hash

        # Verify all entries have hashes
        for entry in persist_entries:
            assert entry.entry_hash is not None
            assert len(entry.entry_hash) == 64

    @pytest.mark.asyncio
    async def test_security_events(self):
        """Test logging security-relevant events."""
        logger = AuditLogger(service_name="security-test")

        user_id = uuid4()

        # Failed login attempts
        for _i in range(3):
            await logger.log_login(
                username="attacker@example.com",
                success=False,
                client_ip="1.2.3.4",
                failure_reason="Invalid password",
            )

        # Access denied
        await logger.log_access_denied(
            user_id=user_id,
            resource_type="admin_panel",
            resource_id="/admin",
            action=AuditAction.GENERIC_READ,
            reason="Admin role required",
        )

        # Unauthorized
        await logger.log_unauthorized(
            resource_type="api",
            client_ip="5.6.7.8",
        )

        # All should be logged without errors
        # In real scenario, these would trigger alerts
