"""Tests for CorrelationContext."""

from ..context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)


class TestCorrelationContext:
    """Tests for CorrelationContext dataclass."""

    def test_generate_creates_valid_context(self):
        """Should generate context with valid UUIDs."""
        ctx = CorrelationContext.generate(tenant_id="tenant-123")

        assert ctx.request_id is not None
        assert len(ctx.request_id) == 36  # UUID format
        assert ctx.trace_id == ctx.request_id  # Default: trace_id equals request_id
        assert ctx.tenant_id == "tenant-123"
        assert ctx.user_id_hash is None

    def test_generate_with_user_id_hashes_it(self):
        """Should hash user ID for privacy."""
        ctx = CorrelationContext.generate(tenant_id="tenant-123", user_id="user-456")

        assert ctx.user_id_hash is not None
        assert ctx.user_id_hash != "user-456"
        assert len(ctx.user_id_hash) == 16  # Truncated SHA256

    def test_from_headers_extracts_all_fields(self):
        """Should extract context from HTTP headers."""
        headers = {
            "x-request-id": "req-123",
            "x-trace-id": "trace-456",
            "x-tenant-id": "tenant-789",
            "x-user-id-hash": "abc123",
        }

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.request_id == "req-123"
        assert ctx.trace_id == "trace-456"
        assert ctx.tenant_id == "tenant-789"
        assert ctx.user_id_hash == "abc123"

    def test_from_headers_generates_missing_request_id(self):
        """Should generate request_id if not provided."""
        headers = {}

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.request_id is not None
        assert len(ctx.request_id) == 36
        assert ctx.trace_id == ctx.request_id

    def test_from_headers_uses_request_id_as_trace_id_if_missing(self):
        """Should use request_id as trace_id if trace_id not provided."""
        headers = {"x-request-id": "req-123"}

        ctx = CorrelationContext.from_headers(headers)

        assert ctx.trace_id == "req-123"

    def test_to_headers_produces_correct_format(self):
        """Should convert to HTTP headers for propagation."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
            tenant_id="tenant-789",
            user_id_hash="abc123",
        )

        headers = ctx.to_headers()

        assert headers["X-Request-ID"] == "req-123"
        assert headers["X-Trace-ID"] == "trace-456"
        assert headers["X-Tenant-ID"] == "tenant-789"
        assert headers["X-User-ID-Hash"] == "abc123"

    def test_to_headers_omits_none_values(self):
        """Should not include None values in headers."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
        )

        headers = ctx.to_headers()

        assert "X-Tenant-ID" not in headers
        assert "X-User-ID-Hash" not in headers


class TestCorrelationContextVar:
    """Tests for context variable management."""

    def test_set_and_get_correlation_context(self):
        """Should store and retrieve context."""
        ctx = CorrelationContext(
            request_id="req-123",
            trace_id="trace-456",
        )

        set_correlation_context(ctx)
        retrieved = get_correlation_context()

        assert retrieved is not None
        assert retrieved.request_id == "req-123"

        # Cleanup
        clear_correlation_context()

    def test_get_returns_none_when_not_set(self):
        """Should return None when context not set."""
        clear_correlation_context()

        result = get_correlation_context()

        assert result is None

    def test_clear_removes_context(self):
        """Should clear the context."""
        ctx = CorrelationContext(request_id="req-123", trace_id="trace-456")
        set_correlation_context(ctx)

        clear_correlation_context()

        assert get_correlation_context() is None
