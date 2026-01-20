"""Tests for Celery correlation integration."""

from unittest.mock import MagicMock, patch

import pytest

from ..celery import (
    cleanup_correlation_for_task,
    extract_correlation_from_task,
    inject_correlation_to_task,
)
from ..context import (
    CorrelationContext,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)


@pytest.fixture
def correlation_context():
    """Set up correlation context."""
    ctx = CorrelationContext(
        request_id="req-123",
        trace_id="trace-456",
        tenant_id="tenant-789",
        user_id_hash="abc123",
    )
    set_correlation_context(ctx)
    yield ctx
    clear_correlation_context()


class TestInjectCorrelationToTask:
    """Tests for inject_correlation_to_task."""

    def test_injects_correlation_into_headers(self, correlation_context):
        """Should inject correlation context into task headers."""
        headers = {}
        inject_correlation_to_task(headers)

        assert "correlation_context" in headers
        data = headers["correlation_context"]
        assert data["request_id"] == "req-123"
        assert data["trace_id"] == "trace-456"
        assert data["tenant_id"] == "tenant-789"
        assert data["user_id_hash"] == "abc123"

    def test_handles_no_correlation_context(self):
        """Should handle case when no correlation context is set."""
        clear_correlation_context()
        headers = {}
        inject_correlation_to_task(headers)
        assert "correlation_context" not in headers

    def test_preserves_existing_headers(self, correlation_context):
        """Should preserve existing headers."""
        headers = {"existing": "value"}
        inject_correlation_to_task(headers)
        assert headers["existing"] == "value"
        assert "correlation_context" in headers


class TestExtractCorrelationFromTask:
    """Tests for extract_correlation_from_task."""

    def test_extracts_correlation_from_headers(self):
        """Should extract and set correlation context from headers."""
        clear_correlation_context()
        headers = {
            "correlation_context": {
                "request_id": "req-123",
                "trace_id": "trace-456",
                "tenant_id": "tenant-789",
                "user_id_hash": "abc123",
            }
        }

        extract_correlation_from_task(headers, task_id="task-001")

        ctx = get_correlation_context()
        assert ctx is not None
        assert ctx.request_id == "req-123"
        assert ctx.trace_id == "trace-456"
        assert ctx.tenant_id == "tenant-789"
        clear_correlation_context()

    def test_generates_context_from_task_id_when_no_headers(self):
        """Should generate context using task_id when no correlation headers."""
        clear_correlation_context()
        headers = {}

        extract_correlation_from_task(headers, task_id="task-001")

        ctx = get_correlation_context()
        assert ctx is not None
        assert ctx.request_id == "task-001"
        assert ctx.trace_id == "task-001"
        clear_correlation_context()

    def test_uses_tenant_id_from_kwargs_as_fallback(self):
        """Should use tenant_id from kwargs if not in headers."""
        clear_correlation_context()
        headers = {}

        extract_correlation_from_task(headers, task_id="task-001", tenant_id="fallback-tenant")

        ctx = get_correlation_context()
        assert ctx.tenant_id == "fallback-tenant"
        clear_correlation_context()

    def test_header_tenant_id_takes_precedence(self):
        """Should prefer tenant_id from headers over kwargs."""
        clear_correlation_context()
        headers = {
            "correlation_context": {
                "request_id": "req-123",
                "trace_id": "trace-456",
                "tenant_id": "header-tenant",
            }
        }

        extract_correlation_from_task(headers, task_id="task-001", tenant_id="fallback-tenant")

        ctx = get_correlation_context()
        assert ctx.tenant_id == "header-tenant"
        clear_correlation_context()

    def test_extracts_user_id_hash_from_headers(self):
        """Should extract user_id_hash from headers."""
        clear_correlation_context()
        headers = {
            "correlation_context": {
                "request_id": "req-123",
                "trace_id": "trace-456",
                "user_id_hash": "hash-abc",
            }
        }

        extract_correlation_from_task(headers, task_id="task-001")

        ctx = get_correlation_context()
        assert ctx.user_id_hash == "hash-abc"
        clear_correlation_context()


class TestCleanupCorrelationForTask:
    """Tests for cleanup_correlation_for_task."""

    def test_clears_correlation_context(self, correlation_context):
        """Should clear the correlation context."""
        cleanup_correlation_for_task()
        assert get_correlation_context() is None

    def test_handles_no_context_gracefully(self):
        """Should handle cleanup when no context is set."""
        clear_correlation_context()
        # Should not raise
        cleanup_correlation_for_task()
        assert get_correlation_context() is None


class TestSetupCeleryCorrelationSignals:
    """Tests for setup_celery_correlation_signals."""

    def test_registers_signals(self):
        """Should register Celery signals for correlation propagation."""
        from ..celery import setup_celery_correlation_signals

        mock_app = MagicMock()

        with patch("celery.signals.before_task_publish") as mock_before_publish, \
             patch("celery.signals.task_prerun") as mock_prerun, \
             patch("celery.signals.task_postrun") as mock_postrun:

            setup_celery_correlation_signals(mock_app)

            # Verify signals were connected
            mock_before_publish.connect.assert_called_once()
            mock_prerun.connect.assert_called_once()
            mock_postrun.connect.assert_called_once()
